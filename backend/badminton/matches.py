"""Matches: upload plus names starts one job; then confirm names and read results.

A match is a video (the match id is the video id) with player names entered at
upload. One job ingests the upload (or reuses the same video already stored),
runs full-match processing including the persons stage, and builds the
MatchAnalysis document. After the job the match waits for the names to be
confirmed (state ``needs_names``), then it is ``ready``.

A match started from a YouTube link has no video id until the video is
downloaded, which is the job's first stage. Until then it is kept under a link
id (16 hex digits of the link's hash, see ``link_id``); after the download the
match moves to the video id and the link record points there (``moved_to``).

Per-video files, next to match_analysis.json in the data folder (local data,
never inside the package, so no perception cache key changes):

- ``match.json``: the match record (mode, entered names, confirmed names, jobs).
- ``match_overrides.json``: the user's swaps of two persons in one rally.

Neither file edits pipeline artifacts, the persons document or annotations; the
builder applies names and swaps when it writes the document.
"""

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Literal

from pydantic import Field

from .match_analysis import (
    PersonId,
    PersonSwap,
    Rally,
    Team,
    build_match_analysis,
    load_match_inputs,
    match_analysis_path,
    read_match_analysis,
    write_match_analysis,
)
from .schemas import StrictModel
from .video import timestamps_for, write_json

RECORD = "match.json"
OVERRIDES = "match_overrides.json"
NAME_LENGTH = 100
MatchState = Literal["queued", "running", "needs_names", "ready", "failed", "paused"]
# The settings full-match processing runs with for a match.
SETTINGS = {"player_model": "small", "auto_calibrate": True, "recognize": True}

# One progress value for the whole job: ingest, processing, building.
INGEST_SHARE = 0.03
BUILD_SHARE = 0.02
# A link match downloads first; the download takes this share of the job.
DOWNLOAD_SHARE = 0.1
DOWNLOADING = "Downloading the video"
PREPARING = "Preparing the video"
BUILDING = "Building the analysis"
WAITING = "Waiting to start"
PAUSING = "Pausing"
LABELS = {
    "segments": "Scanning the video",
    "players": "Finding players",
    "shuttle": "Tracking the shuttle",
    "contacts": "Reading strokes",
    "rallies": "Reading strokes",
    "recognition": "Reading strokes",
    "identities": "Recognising players",
    "persons": "Recognising players",
    "outcomes": "Reading rally outcomes",
}
# Rough relative running time of each stage, so the single progress value moves
# with time rather than with the count of stages.
WEIGHTS = {
    "segments": 2.0,
    "players": 10.0,
    "shuttle": 8.0,
    "contacts": 1.0,
    "rallies": 0.5,
    "recognition": 1.0,
    "identities": 0.5,
    "persons": 2.0,
    # About 80 s for an 8-minute match, most of it fitting every shot's flight.
    "outcomes": 10.0,
}


class NotReady(Exception):
    """The match has no results document yet (or no longer)."""


# Serializes record/override edits and the rebuilds they trigger in one process.
_lock = threading.Lock()


def lock():
    """The lock that serializes match record/override edits and rebuilds."""
    return _lock


# API shapes -----------------------------------------------------------------


class MatchCreated(StrictModel):
    match_id: str
    # None for a link match until its video is downloaded.
    video_id: str | None
    job_id: str
    reused_video: bool


class MatchStatus(StrictModel):
    # A link match's id changes to the video id once the video is downloaded;
    # asking with the old id answers with the new one.
    match_id: str
    video_id: str | None
    mode: Literal["singles", "doubles"]
    name: str | None = None
    # The YouTube link a link match was started from, else None.
    source_url: str | None = None
    state: MatchState
    # The whole job, 0..1: ingest, every processing stage, and the build.
    progress: float = Field(ge=0, le=1)
    stage: str
    job_id: str | None = None
    error: str | None = None
    names_confirmed: bool
    warnings: list[str]


class MatchPlayer(StrictModel):
    id: PersonId
    team: Team
    name: str
    name_source: Literal["guessed", "confirmed"]
    thumbnail_url: str | None = None


class MatchPlayers(StrictModel):
    match_id: str
    state: MatchState
    names_confirmed: bool
    # The names as entered at upload, by team (partners together).
    teams: dict[Team, list[str]]
    players: list[MatchPlayer]


class NameConfirmation(StrictModel):
    # Every person id with the entered name that belongs to it.
    names: dict[PersonId, str]


class SwapRequest(StrictModel):
    persons: tuple[PersonId, PersonId]


class SwapResult(StrictModel):
    # False when this swap undid an identical earlier swap of the rally.
    applied: bool
    rally: Rally
    overrides: list[PersonSwap]


class MatchSummary(StrictModel):
    match_id: str
    mode: Literal["singles", "doubles"]
    name: str | None = None
    created_at: float


# Names ----------------------------------------------------------------------


def entered_names(mode, team1, team2):
    """Validated names by team: one per team in singles, two in doubles."""
    size = 1 if mode == "singles" else 2
    teams = {}
    for team, names in (("T1", team1), ("T2", team2)):
        names = [str(n).strip() for n in names or ()]
        if len(names) != size:
            raise ValueError(
                f"{mode.capitalize()} needs {size} name{'s' if size > 1 else ''} per team"
            )
        if any(not n or len(n) > NAME_LENGTH for n in names):
            raise ValueError(f"Names must be 1 to {NAME_LENGTH} characters")
        teams[team] = names
    flat = [n.casefold() for names in teams.values() for n in names]
    if len(set(flat)) != len(flat):
        raise ValueError("Each player needs a different name")
    return teams


def guessed_names(entered, players):
    """The entered names as a first guess at person ids: team 1's names go to
    team T1's persons in id order, team 2's to T2 (partners stay together)."""
    guess = {}
    for team in ("T1", "T2"):
        ids = sorted(p.id for p in players if p.team == team)
        guess.update(zip(ids, entered[team], strict=True))
    return guess


def check_confirmation(mode, entered, players, names):
    """Confirmed names must be the entered names, each on one person, with
    doubles partners on the same team. Returns the stripped mapping."""
    names = {pid: str(n).strip() for pid, n in names.items()}
    if set(names) != {p.id for p in players}:
        raise ValueError("Confirm a name for every player")
    wanted = sorted(n for team in entered.values() for n in team)
    if sorted(names.values()) != wanted:
        raise ValueError("Use each name entered at upload exactly once")
    if mode == "doubles":
        pairs = {frozenset(team) for team in entered.values()}
        for team in ("T1", "T2"):
            if frozenset(names[p.id] for p in players if p.team == team) not in pairs:
                raise ValueError("Partners must stay on the same team")
    return names


# Files ----------------------------------------------------------------------


def _path(data, video_id, name):
    return match_analysis_path(data, video_id).with_name(name)


def read_record(data, video_id):
    path = _path(data, video_id, RECORD)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def resolve(data, match_id):
    """The match's record, following a downloaded link match to its video."""
    record = read_record(data, match_id)
    if record is not None and record.get("moved_to"):
        record = read_record(data, record["moved_to"])
    return record


def link_id(url):
    """A link match's id until its video is downloaded: 16 hex digits like a
    video id, from the canonical link, so the same link gets the same id."""
    return hashlib.sha256(f"youtube:{url}".encode()).hexdigest()[:16]


def write_record(data, record):
    record["updated_at"] = time.time()
    write_json(_path(data, record["video_id"], RECORD), record)


def new_record(video_id, mode, entered, name, source_url=None, link=False):
    """``link``: a link match still waiting for its download (``video_id`` is
    then the link id)."""
    return {
        "schema_version": 1,
        "video_id": video_id,
        "mode": mode,
        "name": name,
        "source_url": source_url,
        "link": link,
        "entered": entered,
        "confirmed": None,
        "job_id": None,
        "jobs": [],
        "created_at": time.time(),
    }


def read_overrides(data, video_id):
    path = _path(data, video_id, OVERRIDES)
    if not path.is_file():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    return [PersonSwap.model_validate(o) for o in document["overrides"]]


def move_to_video(data, link, video):
    """After a link match's download: the match carries on under the video id
    (``video`` is the stored video document) and the link record points there.
    Earlier jobs of the same video are kept with the link's."""
    with _lock:
        record = read_record(data, link)
        previous = read_record(data, video["id"]) or {}
        jobs = previous.get("jobs", [])
        moved = {
            **record,
            "video_id": video["id"],
            "name": video.get("name") or record.get("name"),
            "link": False,
            "link_id": link,
            "jobs": [*jobs, *(j for j in record.get("jobs", []) if j not in jobs)],
        }
        write_record(data, moved)
        record["moved_to"] = video["id"]
        write_record(data, record)
    return video["id"]


def write_overrides(data, video_id, overrides):
    write_json(
        _path(data, video_id, OVERRIDES),
        {
            "schema_version": 1,
            "meaning": "User swaps of two persons over a rally's frames; applied "
            "in order by the MatchAnalysis builder",
            "overrides": [o.model_dump(mode="json") for o in overrides],
        },
    )


def thumbnail_file(data, video_id, relative):
    """A player thumbnail path from the document, kept inside the video's data
    folder. Returns the file, or None when it is missing or not allowed."""
    if not relative or not isinstance(relative, str):
        return None
    folder = match_analysis_path(data, video_id).parent.resolve()
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.drive or ".." in candidate.parts:
        return None
    path = (folder / candidate).resolve()
    if (
        not path.is_relative_to(folder)
        or path.suffix.lower() not in (".jpg", ".jpeg", ".png")
        or not path.is_file()
    ):
        return None
    return path


# Building -------------------------------------------------------------------


def rebuild(store, video_id, analysis_key=None, identity=None):
    """Build and store the document with the match's names and overrides.

    Without an analysis key it keeps the plan the stored document was built
    from (so a name or swap edit never switches processing silently), else the
    newest completed plan.
    """
    if analysis_key is None:
        current = read_match_analysis(store.data, video_id)
        analysis_key = current.provenance.analysis_key if current else None
    record = read_record(store.data, video_id) or {}
    document = build_match_analysis(
        load_match_inputs(store, video_id, analysis_key),
        identity,
        names=record.get("confirmed"),
        overrides=read_overrides(store.data, video_id),
    )
    write_match_analysis(store.data, document)
    return document


def confirm_names(store, video_id, names):
    with _lock:
        record = read_record(store.data, video_id)
        document = read_match_analysis(store.data, video_id)
        if record is None or document is None:
            raise NotReady("This match has no results yet")
        record["confirmed"] = check_confirmation(
            record["mode"], record["entered"], document.players, names
        )
        record["confirmed_at"] = time.time()
        write_record(store.data, record)
        return rebuild(store, video_id)


def swap(store, video_id, rally_id, persons=None):
    """Swap two persons for one rally, or undo: an identical second swap, or
    persons=None, removes the rally's swaps. Returns (applied, document)."""
    with _lock:
        document = read_match_analysis(store.data, video_id)
        if document is None:
            raise NotReady("This match has no results yet")
        rally = next((r for r in document.rallies if r.id == rally_id), None)
        if rally is None:
            raise KeyError(rally_id)
        overrides = read_overrides(store.data, video_id)
        inside = [
            o
            for o in overrides
            if o.start_frame <= rally.end_frame and o.end_frame >= rally.start_frame
        ]
        if persons is None:
            applied = False
            overrides = [o for o in overrides if o not in inside]
        else:
            known = {p.id for p in document.players}
            if len(set(persons)) != 2 or not set(persons) <= known:
                raise ValueError("Swap two different players of this match")
            same = next(
                (
                    o
                    for o in inside
                    if set(o.persons) == set(persons)
                    and (o.start_frame, o.end_frame)
                    == (rally.start_frame, rally.end_frame)
                ),
                None,
            )
            applied = same is None
            if same is not None:
                overrides.remove(same)
            else:
                overrides.append(
                    PersonSwap(
                        persons=tuple(persons),
                        start_frame=rally.start_frame,
                        end_frame=rally.end_frame,
                        rally_id=rally.id,
                    )
                )
        write_overrides(store.data, video_id, overrides)
        return applied, rally, rebuild(store, video_id)


# Status ---------------------------------------------------------------------


def status(store, match_id):
    """The match's state, one progress value and a stage label."""
    record = resolve(store.data, match_id)
    if record is None:
        raise KeyError(match_id)
    video_id = record["video_id"]
    link = bool(record.get("link"))
    job = None
    if record.get("job_id"):
        try:
            job = store.job(record["job_id"])
        except KeyError:
            job = None
    document = read_match_analysis(store.data, video_id)
    error = None
    progress = 0.0
    stage = WAITING
    if job is None:
        state = "queued" if record.get("job_id") is None else "failed"
        if state == "failed":
            error = "The processing job record is missing; resume the match"
    elif job["status"] == "queued":
        state = "queued"
    elif job["status"] == "running":
        state, progress = "running", job.get("progress") or 0.0
        # Before run_match sets its first label the job says "Processing".
        message = job.get("message")
        first = DOWNLOADING if link else PREPARING
        stage = first if message in (None, "", "Processing") else message
        stage = PAUSING if job.get("cancel_requested") else stage
    elif job["status"] == "interrupted":
        state, progress = "paused", job.get("progress") or 0.0
        stage, error = "Paused", job.get("message")
    elif job["status"] == "completed" and document is not None:
        progress = 1.0
        state = "ready" if record.get("confirmed") else "needs_names"
        stage = "Done" if state == "ready" else "Confirm the player names"
    else:
        state, progress = "failed", job.get("progress") or 0.0
        stage = "Failed"
        error = (
            job.get("message")
            if job["status"] == "failed"
            else "The analysis document is missing; resume the match to rebuild it"
        )
    return MatchStatus(
        match_id=video_id,
        video_id=None if link else video_id,
        mode=record["mode"],
        name=record.get("name"),
        source_url=record.get("source_url"),
        state=state,
        progress=round(min(1.0, max(0.0, progress)), 3),
        stage=stage,
        job_id=record.get("job_id"),
        error=error,
        names_confirmed=bool(record.get("confirmed")) and document is not None,
        warnings=document.warnings if document is not None else [],
    )


def players(store, video_id, thumbnail_url):
    record = read_record(store.data, video_id)
    document = read_match_analysis(store.data, video_id)
    if record is None:
        raise KeyError(video_id)
    if document is None:
        raise NotReady("This match has no results yet")
    confirmed = record.get("confirmed")
    names = confirmed or guessed_names(record["entered"], document.players)
    return MatchPlayers(
        match_id=video_id,
        state=status(store, video_id).state,
        names_confirmed=bool(confirmed),
        teams=record["entered"],
        players=[
            MatchPlayer(
                id=p.id,
                team=p.team,
                name=names[p.id],
                name_source="confirmed" if confirmed else "guessed",
                thumbnail_url=thumbnail_url(p.id)
                if thumbnail_file(store.data, video_id, p.thumbnail)
                else None,
            )
            for p in document.players
        ],
    )


def matches(store):
    """Every match in the data folder, newest first."""
    found = []
    for path in store.data.glob(f"*/{RECORD}"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("moved_to"):
            continue  # a downloaded link match, listed under its video
        found.append(
            MatchSummary(
                match_id=record["video_id"],
                mode=record["mode"],
                name=record.get("name"),
                created_at=record["created_at"],
            )
        )
    return sorted(found, key=lambda m: -m.created_at)


# The job --------------------------------------------------------------------


class ProcessingProgress:
    """Map full-match processing's stage-count progress to a time-weighted
    fraction and a stage label.

    process_match reports (completed stages + fraction of the current one) /
    total, with the stages in this order: segments, then per window players,
    shuttle, contacts, rallies, recognition, then identities, persons and
    outcomes.
    """

    def __init__(self, windows):
        from . import pipeline

        self.sequence = ["segments", *pipeline.STAGES * windows]
        self.sequence += ["identities", "persons", "outcomes"]
        self.before, total = [], 0.0
        for name in self.sequence:
            self.before.append(total)
            total += WEIGHTS[name]
        self.total = total

    def __call__(self, value):
        # Processing reports progress rounded down to 1/1000; read it as the
        # top of that step so a stage that has just started gets its label.
        value = min(1.0, max(0.0, value + 0.000999)) if value > 0 else 0.0
        position = value * len(self.sequence)
        index = min(len(self.sequence) - 1, int(position))
        name = self.sequence[index]
        part = min(1.0, position - index)
        return (self.before[index] + WEIGHTS[name] * part) / self.total, LABELS[name]


def run_match(store, root, video_id, job, progress, *, ingest=None, fetch=None):
    """The match job: download (a link match), ingest (when the video is new),
    processing, the build.

    ``job`` is the caller's admitted analysis job document; its ``message``
    carries the stage label and its ``details`` the processing key. For a link
    match ``video_id`` is the link id and ``fetch(downloading, preparing)``
    downloads and stores the video, reporting each part's progress 0..1, and
    returns the stored video document; the match then moves to its id.
    """
    from . import pipeline

    last = [0.0]

    def report(value, label):
        job["message"] = label
        last[0] = max(last[0], min(1.0, value))
        progress(last[0])

    start = DOWNLOAD_SHARE if fetch is not None else 0.0
    if fetch is not None:
        report(0, DOWNLOADING)
        video = fetch(
            lambda value: report(start * value, DOWNLOADING),
            lambda value: report(start + INGEST_SHARE * value, PREPARING),
        )
        video_id = move_to_video(store.data, video_id, video)
        # Processing checks that the job is this video's (report saves it).
        job["video_id"] = video_id
        report(start + INGEST_SHARE, PREPARING)
    else:
        report(0, PREPARING)
    if ingest is not None:
        ingest(lambda value: report(INGEST_SHARE * value, PREPARING))
    video = store.video(video_id)
    times = timestamps_for(store.data, video_id)
    snapshot = store.annotations(video_id)
    settings = dict(SETTINGS)
    key = pipeline.digest(pipeline.processing_recipe(video, times, snapshot, settings))
    job["details"] = {"analysis_key": key, "settings": settings, "match": True}
    weights = ProcessingProgress(len(pipeline.plan_windows(video, times)))
    span = 1 - start - INGEST_SHARE - BUILD_SHARE

    def processing(value):
        fraction, label = weights(value)
        report(start + INGEST_SHARE + span * fraction, label)

    summary = pipeline.process_match(
        video,
        root,
        store,
        snapshot,
        job["id"],
        processing,
        settings,
        expected_key=key,
    )
    report(1 - BUILD_SHARE, BUILDING)
    with _lock:
        document = rebuild(store, video_id, analysis_key=key)
    shots = [s for r in document.rallies for s in r.shots]
    return {
        **summary,
        "match_id": video_id,
        "identity": document.identity.source,
        "rallies": len(document.rallies),
        "shots": len(shots),
        "shots_with_hitter": sum(s.hitter_id is not None for s in shots),
        "warnings": document.warnings,
    }
