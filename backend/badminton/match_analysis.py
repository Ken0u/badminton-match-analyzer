"""One results document per match: ``MatchAnalysis``.

The new match page and every clip statistic read only this document; none of
them read pipeline plans, stage runs or annotations. The builder assembles it
from what a completed full-match processing plan stored (see pipeline.py) and
an optional identity input. It never runs inference and never edits
annotations.

Rules the document keeps:

- A value the pipeline did not measure is ``null``, never a guess. The last
  shot's landing, the rally outcome and each shot's fitted 3D flight (initial
  speed) come from the pipeline's outcomes stage (rally_outcomes.py); this
  builder only reads them, rates each flight's fit and turns court ends into
  teams. There is no shuttle 3D position track.
- Court coordinates are metres on the court floor: x across the court from the
  far-left outer (doubles) sideline, 0 to 6.1; y along the court from the far
  baseline, 0 to 13.4; the net is at y = 6.7. "Far" is the end away from the
  camera. Player positions are the bottom centre of the person box (the feet),
  projected through the court homography of the camera view.
- The shuttle stays in normalized image coordinates (0..1 of width/height).

docs/MATCH_ANALYSIS_FORMAT.md describes the format for UI and statistics code.
"""

import bisect
import itertools
import json
import os
import statistics
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .identity import validate_assignments
from .schemas import StrictModel

SCHEMA_VERSION = 4
BUILDER = "match analysis builder v4"
FILENAME = "match_analysis.json"

COURT_WIDTH_M = 6.1
COURT_LENGTH_M = 13.4
NET_Y_M = 6.7
SINGLES_SIDELINES_M = (0.46, 5.64)
SHORT_SERVICE_LINES_M = (4.72, 8.68)  # 1.98 m either side of the net
DOUBLES_LONG_SERVICE_LINES_M = (0.76, 12.64)  # 0.76 m inside each baseline
# Projected positions farther than this outside the outer lines are reported as
# unseen (null), never clamped onto a line.
COURT_MARGIN_M = 2.0
# Fixed sampling rate of the per-person court tracks.
TRACK_RATE_HZ = 10
# Rounding: centimetres for court metres, 1/10000 of the frame for the image.
COURT_DECIMALS = 2
IMAGE_DECIMALS = 4
# A contact's hitter or shuttle may be missing on the exact contact frame;
# these source-frame offsets are tried in order.
CONTACT_SEARCH = (0, -1, 1, -2, 2, -3, 3)
SHUTTLE_SEARCH = (0, -1, 1, -2, 2)
# Rally boundaries come first from the rallies stage's serve and rally-end
# proposals. Where none falls between two contacts, a new rally starts at a
# predicted serve, after this long without a contact, or at a camera cut.
RALLY_BREAK_S = 4.0
# A serve proposal this close to a contact opens the rally at that contact.
SERVE_MATCH_S = 0.5
RallyStart = Literal[
    "proposed_serve",
    "after_proposed_end",
    "predicted_serve",
    "contact_gap",
    "camera_cut",
    "first_contact",
]
RallyEnd = Literal["landing", "proposed_rally_end", "last_contact"]
CourtEnd = Literal["far", "near"]
# A game ends at 21 points with a two-point lead, or at 30.
GAME_POINTS, GAME_CAP = 21, 30
# Per-view fallback identity: a track group must be seen this often, standing
# (by median) within this margin of the outer lines, to be given a person.
FALLBACK_MINIMUM_FRAMES = 5
FALLBACK_COURT_MARGIN_M = 0.5
PERSONS_NOTE = (
    "Person ids come from the persons stage, which groups every camera view's "
    "players by how they look, for the whole video. They are unreviewed: "
    "confirm the names, and swap two persons in a rally where they are mixed up."
)

# A shot's fitted flight is "poor_fit" when its image residual (inliers, image
# heights) is above FLIGHT_RMS_MAX or fewer than FLIGHT_INLIERS_MIN points
# agree with it, and "speed_bound" when its initial speed reached the fit's
# bound (shuttle_flight.MAX_SPEED_M_S, 450 km/h): at 30 frames per second
# the first frames after a hard hit do not fix the speed at the racket.
FLIGHT_RMS_MAX = 0.01
FLIGHT_INLIERS_MIN = 5
FLIGHT_SPEED_BOUND_KMH = 440.0

PersonId = Literal["P1", "P2", "P3", "P4"]
Team = Literal["T1", "T2"]
ShotFamily = Literal[
    "clear",
    "drive",
    "smash",
    "net",
    "drop",
    "lift",
    "block",
    "push",
    "net_kill",
    "other",
]
# Model class names to document families; anything else stays null.
FAMILY_NAMES = {
    "clear": "clear",
    "drive": "drive",
    "smash": "smash",
    "net": "net",
    "drop": "drop",
    "lift": "lift",
    "block": "block",
    "push": "push",
    "net kill": "net_kill",
    "other": "other",
}


def _finite(**kwargs):
    return Field(allow_inf_nan=False, **kwargs)


class ImagePoint(StrictModel):
    """Normalized image coordinates: 0..1 of the oriented frame width/height."""

    x: float = _finite()
    y: float = _finite()


class CourtPoint(StrictModel):
    """Metres on the court floor (see the module docstring for the frame)."""

    x: float = _finite(ge=-COURT_MARGIN_M, le=COURT_WIDTH_M + COURT_MARGIN_M)
    y: float = _finite(ge=-COURT_MARGIN_M, le=COURT_LENGTH_M + COURT_MARGIN_M)


class VideoInfo(StrictModel):
    id: str = Field(min_length=1)
    name: str | None = None
    mode: Literal["singles", "doubles"]
    fps: float = _finite(gt=0)
    frame_count: int = Field(gt=0)
    duration_s: float = _finite(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Person(StrictModel):
    id: PersonId
    name: str = Field(default="", max_length=100)
    team: Team
    handedness: Literal["left", "right"] | None = None
    thumbnail: str | None = Field(default=None, max_length=512)


class IdentityInfo(StrictModel):
    # persons_stage: the pipeline's whole-video persons stage; supplied: an
    # identity given to the builder; per_view_fallback: not persistent.
    source: Literal["persons_stage", "supplied", "per_view_fallback"]
    method: str
    persistent: bool
    note: str
    assignment_count: int = Field(ge=0)
    # Share of published player observations (in calibrated views) that carry a
    # person id; null when there were no observations.
    assigned_observation_share: float | None = _finite(default=None, ge=0, le=1)


class CourtGeometry(StrictModel):
    units: Literal["metres"] = "metres"
    width: float = COURT_WIDTH_M
    length: float = COURT_LENGTH_M
    net_y: float = NET_Y_M
    singles_sidelines_x: tuple[float, float] = SINGLES_SIDELINES_M
    short_service_lines_y: tuple[float, float] = SHORT_SERVICE_LINES_M
    doubles_long_service_lines_y: tuple[float, float] = DOUBLES_LONG_SERVICE_LINES_M


class CourtView(StrictModel):
    """One camera range with one court fit. Frames are half-open."""

    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    # Outer court corners, order far left, far right, near right, near left.
    corners: list[ImagePoint] = Field(min_length=4, max_length=4)
    # Row-major 3x3; (x, y, 1) in normalized image coordinates maps to court
    # metres after dividing by the third component.
    homography: list[list[float]] = Field(min_length=3, max_length=3)
    source: Literal["automatic", "reviewed"]

    @model_validator(mode="after")
    def valid(self):
        if self.end_frame <= self.start_frame:
            raise ValueError("Court view end must follow its start")
        if any(len(row) != 3 for row in self.homography):
            raise ValueError("A homography is a 3x3 matrix")
        return self


class Court(StrictModel):
    geometry: CourtGeometry = Field(default_factory=CourtGeometry)
    views: list[CourtView] = Field(default_factory=list)


class Landing(StrictModel):
    """Where the last shot came down, from the shuttle's image track.

    ``position`` is the floor point under the image point where the shuttle
    stopped descending, through the camera recovered from the court view
    (the shuttle's centre is taken a few centimetres above the floor), or
    where the fitted 3D flight meets the floor when the track ended in the
    air (null when it lies more than COURT_MARGIN_M outside the court); ``kind`` is rest (it then lay still), descent (it
    stopped going down) or track_end (its track ended in the air, so the
    position is unreliable). ``in_court`` uses the rally lines: singles or
    doubles sidelines and the full length.
    """

    frame: int = Field(ge=0)
    time_s: float = _finite(ge=0)
    image: ImagePoint
    position: CourtPoint | None = None
    in_court: bool | None = None
    kind: Literal["rest", "descent", "track_end"]
    source: str


class RallyOutcome(StrictModel):
    """Who won the rally and how, from the outcomes stage.

    The reason is the last hitter's: ``winner`` when the last hitter won (the
    shot landed in), ``error`` when the last hitter lost it (``out``, or
    ``net``: it did not get over). ``winner_end`` is the court end of the
    winning side when the rally ended; ``winner_team`` is the team found at
    that end (null when no identified player was seen there).
    """

    winner_team: Team | None = None
    winner_end: CourtEnd
    last_hitter_end: CourtEnd | None = None
    reason: Literal["winner", "error"]
    detail: Literal["in", "out", "net"] | None = None
    # Uncalibrated: the rule's or the model's support for the call.
    confidence: float | None = _finite(default=None, ge=0, le=1)
    source: str


class TeamScore(StrictModel):
    T1: int = Field(default=0, ge=0)
    T2: int = Field(default=0, ge=0)


class RallyScore(StrictModel):
    """Points counted from the start of the video, not the official score.

    A rally whose winning team is unknown leaves the score unchanged. A game
    ends at 21 (two clear, at most 30); the next rally starts game + 1.
    """

    game: int = Field(ge=1)
    before: TeamScore
    after: TeamScore


class ShotFlight(StrictModel):
    """The shot's 3D flight fitted to the shuttle's image track (outcomes stage).

    Gravity plus air drag from the hitter to the next contact (the last shot:
    to its landing), through the camera recovered from the court view. Only
    ``quality == "good"`` speeds are measurements; ``speed_bound`` fits hit the
    fit's speed limit and their speed is not known (see FLIGHT_SPEED_BOUND_KMH).
    """

    # Speed leaving the racket, km/h (as fitted; see quality).
    initial_speed_kmh: float = _finite(ge=0)
    # Speed 0.1 s after the contact, km/h: well fixed even for hard hits, but
    # drag caps it near 120 km/h, so it does not separate the fastest shots.
    speed_settled_kmh: float | None = _finite(default=None, ge=0)
    # Highest point of the fitted flight above the floor, metres.
    apex_m: float | None = _finite(default=None)
    quality: Literal["good", "poor_fit", "speed_bound"]
    # Fit diagnostics: residual of the inliers (image heights), points fitted
    # and points within 3 residual scales, seconds of track observed.
    rms: float = _finite(ge=0)
    points: int = Field(ge=0)
    inliers: int = Field(ge=0)
    observed_s: float | None = _finite(default=None)


class PlayerPosition(StrictModel):
    person_id: PersonId | None = None
    position: CourtPoint


class Shot(StrictModel):
    id: str = Field(min_length=1)
    frame: int = Field(ge=0)
    time_s: float = _finite(ge=0)
    kind: Literal["serve", "shot"] | None = None
    hitter_id: PersonId | None = None
    family: ShotFamily | None = None
    side: Literal["forehand", "backhand"] | None = None
    serve_type: Literal["short", "long"] | None = None
    # Uncalibrated model scores; not probabilities of being right.
    confidence: float | None = _finite(default=None, ge=0, le=1)
    family_score: float | None = _finite(default=None, ge=0, le=1)
    side_score: float | None = _finite(default=None, ge=0, le=1)
    hitter_position: CourtPoint | None = None
    players: list[PlayerPosition] = Field(default_factory=list)
    shuttle: ImagePoint | None = None
    landing: Landing | None = None
    # Null when the outcomes stage fitted no flight for this shot.
    flight: ShotFlight | None = None

    @model_validator(mode="after")
    def consistent(self):
        if self.kind == "serve" and self.family is not None:
            raise ValueError("A serve has a serve type, not a shot family")
        if self.kind != "serve" and self.serve_type is not None:
            raise ValueError("Only a serve has a serve type")
        return self


class Rally(StrictModel):
    id: str = Field(min_length=1)
    # Inclusive. The start is the serve (proposed or predicted) or the first
    # contact; the end is a proposed rally end (the shuttle settling) or the
    # last contact. start_source and end_source say which.
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    start_s: float = _finite(ge=0)
    end_s: float = _finite(ge=0)
    start_source: RallyStart
    end_source: RallyEnd
    server_id: PersonId | None = None
    shots: list[Shot] = Field(min_length=1)
    outcome: RallyOutcome | None = None
    score: RallyScore | None = None

    @model_validator(mode="after")
    def ordered(self):
        frames = [s.frame for s in self.shots]
        if frames != sorted(set(frames)):
            raise ValueError("Rally shots must be in strictly increasing frame order")
        if not self.start_frame <= frames[0] or not frames[-1] <= self.end_frame:
            raise ValueError("A rally spans all of its contacts")
        if self.end_source == "last_contact" and self.end_frame != frames[-1]:
            raise ValueError("A rally without a proposed end ends at its last contact")
        if self.end_s < self.start_s:
            raise ValueError("Rally end must not precede its start")
        return self


class PersonTrack(StrictModel):
    person_id: PersonId
    # One value per sample in Tracks.sample_frames; null when unseen.
    x: list[float | None]
    y: list[float | None]


class ShuttleTrack(StrictModel):
    # One value per source frame (index = frame); null when not detected.
    x: list[float | None]
    y: list[float | None]


class Tracks(StrictModel):
    rate_hz: float = _finite(gt=0)
    # Source frame shown at each sample time k / rate_hz.
    sample_frames: list[int]
    persons: list[PersonTrack]
    shuttle: ShuttleTrack

    @model_validator(mode="after")
    def aligned(self):
        n = len(self.sample_frames)
        if any(len(p.x) != n or len(p.y) != n for p in self.persons):
            raise ValueError("Person tracks must align with the sample frames")
        if len(self.shuttle.x) != len(self.shuttle.y):
            raise ValueError("Shuttle track coordinates must align")
        return self


class ModelRef(StrictModel):
    stage: str
    name: str | None = None
    checkpoint_sha256: str | None = None


class PartRuns(StrictModel):
    core_start_frame: int = Field(ge=0)
    core_end_frame: int = Field(gt=0)
    players_run_id: str
    shuttle_run_id: str
    contacts_run_id: str
    rallies_run_id: str | None = None
    recognition_run_id: str | None = None


class PersonSwap(StrictModel):
    """A user correction: two persons swapped over a frame range (inclusive)."""

    kind: Literal["swap"] = "swap"
    persons: tuple[PersonId, PersonId]
    start_frame: int = Field(ge=0)
    end_frame: int = Field(ge=0)
    # The rally the swap was made on, at the time it was made.
    rally_id: str | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.persons[0] == self.persons[1]:
            raise ValueError("A swap needs two different persons")
        if self.end_frame < self.start_frame:
            raise ValueError("A swap range must not end before it starts")
        return self


class Provenance(StrictModel):
    builder: str = BUILDER
    created_at: str
    analysis_key: str
    segments_run_id: str | None = None
    identities_run_id: str | None = None
    persons_run_id: str | None = None
    outcomes_run_id: str | None = None
    # True when the outcomes stage fitted every shot's flight; otherwise every
    # shots[].flight is null because it was not attempted.
    shot_flights: bool = False
    parts: list[PartRuns]
    models: list[ModelRef]


class MatchAnalysis(StrictModel):
    schema_version: Literal[4] = 4
    video: VideoInfo
    players: list[Person]
    # True once a person confirmed which name belongs to which player; until
    # then every players[].name is empty.
    names_confirmed: bool = False
    identity: IdentityInfo
    court: Court
    rallies: list[Rally]
    tracks: Tracks
    # User corrections applied to person ids, in the order they apply.
    overrides: list[PersonSwap] = Field(default_factory=list)
    # Plain sentences about limits of this document (e.g. identity fallback).
    warnings: list[str] = Field(default_factory=list)
    provenance: Provenance

    @model_validator(mode="after")
    def consistent(self):
        expected = 2 if self.video.mode == "singles" else 4
        ids = [p.id for p in self.players]
        if len(ids) != expected or len(set(ids)) != expected:
            raise ValueError(f"{self.video.mode} has {expected} distinct players")
        if any(
            sum(p.team == t for p in self.players) != expected // 2
            for t in ("T1", "T2")
        ):
            raise ValueError("Teams must have equal player counts")
        known = set(ids)
        if self.names_confirmed and not all(p.name for p in self.players):
            raise ValueError("Confirmed names must not be empty")
        if any(p not in known for o in self.overrides for p in o.persons):
            raise ValueError("Override refers to an unlisted player")
        frames = []
        for rally in self.rallies:
            if rally.server_id is not None and rally.server_id not in known:
                raise ValueError("Rally server is not a listed player")
            for shot in rally.shots:
                frames.append(shot.frame)
                people = [shot.hitter_id] + [p.person_id for p in shot.players]
                if any(p is not None and p not in known for p in people):
                    raise ValueError("Shot refers to an unlisted player")
                if shot.frame >= self.video.frame_count:
                    raise ValueError("Shot frame exceeds the video")
        if frames != sorted(set(frames)):
            raise ValueError("Shots must be unique and ordered across rallies")
        if any(
            a.end_frame >= b.start_frame for a, b in itertools.pairwise(self.rallies)
        ):
            raise ValueError("Rallies must not overlap")
        if any(t.person_id not in known for t in self.tracks.persons):
            raise ValueError("Track refers to an unlisted player")
        if len(self.tracks.shuttle.x) != self.video.frame_count:
            raise ValueError("The shuttle track has one value per source frame")
        views = sorted(self.court.views, key=lambda v: v.start_frame)
        if any(a.end_frame > b.start_frame for a, b in itertools.pairwise(views)):
            raise ValueError("Court views must not overlap")
        return self


# Identity input -------------------------------------------------------------


class IdentityPerson(BaseModel):
    """A roster entry supplied with the identity. Unknown extra keys are ignored."""

    model_config = ConfigDict(extra="ignore")
    id: PersonId
    team: Team
    name: str = Field(default="", max_length=100)
    handedness: Literal["left", "right"] | None = None
    thumbnail: str | None = None


class IdentityAssignment(BaseModel):
    """TrackAssignment shape; extra keys (such as a certainty) are ignored."""

    model_config = ConfigDict(extra="ignore")
    run_id: str = Field(min_length=1, max_length=64)
    track_id: int = Field(ge=0)
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    player_id: PersonId


class IdentityInput(BaseModel):
    """Persistent identity: player-run tracks mapped to person ids.

    ``assignments`` have the TrackAssignment shape (run_id, track_id,
    start_frame, end_frame half-open, player_id). Step 2a stores this shape in
    a per-video artifact; extra keys there are ignored here, and its
    ``provenance.method`` names the method when ``method`` is absent.
    """

    model_config = ConfigDict(extra="ignore")
    persons: list[IdentityPerson]
    assignments: list[IdentityAssignment]
    method: str = "supplied track assignments"

    @model_validator(mode="before")
    @classmethod
    def method_from_provenance(cls, value):
        if isinstance(value, dict) and "method" not in value:
            method = (value.get("provenance") or {}).get("method")
            if isinstance(method, str) and method:
                value = {**value, "method": method}
        return value


def default_persons(mode):
    """P1..P2 (singles) or P1..P4 (doubles); P1(+P2) are team T1. No names."""
    if mode == "singles":
        return [Person(id="P1", team="T1"), Person(id="P2", team="T2")]
    return [Person(id=f"P{i}", team="T1" if i <= 2 else "T2") for i in range(1, 5)]


class _Resolver:
    """Look up a person for (run, track, frame) from half-open assignments,
    then apply the user's swaps (inclusive frame ranges) in order."""

    def __init__(self, records, swaps=()):
        self.index = {}
        for r in records:
            self.index.setdefault((r["run_id"], r["track_id"]), []).append(
                (r["start_frame"], r["end_frame"], r["player_id"])
            )
        self.swaps = [(s.start_frame, s.end_frame, *s.persons) for s in swaps]

    def __call__(self, run_id, track_id, frame):
        if track_id is None:
            return None
        person = None
        for start, end, candidate in self.index.get((run_id, track_id), ()):
            if start <= frame < end:
                person = candidate
                break
        for start, end, a, b in self.swaps:
            if start <= frame <= end and person in (a, b):
                person = b if person == a else a
        return person


# Court geometry -------------------------------------------------------------


def court_homography(corners):
    """Normalized image corners (far left, far right, near right, near left)
    to court metres. Returns a 3x3 list, or None for a degenerate quad."""
    target = [
        (0.0, 0.0),
        (COURT_WIDTH_M, 0.0),
        (COURT_WIDTH_M, COURT_LENGTH_M),
        (0.0, COURT_LENGTH_M),
    ]
    rows, values = [], []
    for (x, y), (u, v) in zip(corners, target):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        values += [u, v]
    try:
        solved = np.linalg.solve(np.asarray(rows, float), np.asarray(values, float))
    except np.linalg.LinAlgError:
        return None
    matrix = np.append(solved, 1.0).reshape(3, 3)
    if not np.isfinite(matrix).all():
        return None
    denominators = [matrix[2] @ (x, y, 1) for x, y in corners]
    if (
        any(abs(d) < 1e-9 for d in denominators)
        or len({d > 0 for d in denominators}) != 1
    ):
        return None
    if denominators[0] < 0:
        matrix = -matrix
    for (x, y), (u, v) in zip(corners, target):
        point = project(matrix, x, y)
        if point is None or abs(point[0] - u) > 1e-6 or abs(point[1] - v) > 1e-6:
            return None
    return matrix.tolist()


def project(matrix, x, y):
    """Normalized image point to court metres; None behind the horizon."""
    m = matrix
    divisor = m[2][0] * x + m[2][1] * y + m[2][2]
    if divisor < 1e-9:
        return None
    px = (m[0][0] * x + m[0][1] * y + m[0][2]) / divisor
    py = (m[1][0] * x + m[1][1] * y + m[1][2]) / divisor
    if not (np.isfinite(px) and np.isfinite(py)):
        return None
    return float(px), float(py)


def on_court(point, margin=COURT_MARGIN_M):
    return (
        point is not None
        and -margin <= point[0] <= COURT_WIDTH_M + margin
        and -margin <= point[1] <= COURT_LENGTH_M + margin
    )


def feet_point(person, width, height):
    """Bottom centre of the person box, normalized; None for a bad box."""
    box = person.get("box")
    if not box or len(box) != 4 or not all(np.isfinite(v) for v in box):
        return None
    x1, _y1, x2, y2 = box
    if x2 <= x1:
        return None
    return ((x1 + x2) / 2 / width, y2 / height)


# Loading stored outputs -----------------------------------------------------


@dataclass
class MatchInputs:
    """Everything the builder reads, already loaded from the Store."""

    video: dict
    times: list
    plan: dict
    runs: dict  # run_id -> parsed stage artifact
    # The persons stage's document (IdentityInput shape), when it ran.
    identity: dict | None = None


def latest_analysis_key(store, video_id):
    """The newest completed full-match processing plan of a video."""
    from .pipeline import read_plan

    for job in store.jobs(video_id):  # newest first
        key = (job.get("details") or {}).get("analysis_key")
        if job.get("kind") != "analysis" or job.get("status") != "completed" or not key:
            continue
        try:
            plan = read_plan(store, video_id, key)
        except FileNotFoundError:
            continue
        if plan.get("processing_complete"):
            return key
    return None


def load_match_inputs(store, video_id, analysis_key=None):
    """Read a completed plan and the stage runs it lists, checking their hashes."""
    from .pipeline import read_plan
    from .video import timestamps_for

    video = store.video(video_id)
    key = analysis_key or latest_analysis_key(store, video_id)
    if key is None:
        raise ValueError("This video has no completed full-match processing")
    plan = read_plan(store, video_id, key)
    if not plan.get("processing_complete") or plan.get("video_id") != video_id:
        raise ValueError("The processing plan is not complete for this video")
    runs = load_plan_runs(store, video_id, plan)
    identity = None
    if plan.get("persons"):
        from .person_identity import load_document

        identity = load_document(store.data, video_id, plan["persons"])
    return MatchInputs(
        video, list(timestamps_for(store.data, video_id)), plan, runs, identity
    )


def load_plan_runs(store, video_id, plan, outcomes=True):
    """The stage runs a plan lists, by run id, each checked against its hash."""
    from .pipeline import file_sha

    runs = {}

    def load(checkpoint, stage, required=True):
        if not checkpoint:
            if required:
                raise ValueError(f"The processing plan lacks its {stage} stage")
            return
        path = store.data / video_id / "runs" / f"{checkpoint['run_id']}.json"
        if not path.is_file() or file_sha(path) != checkpoint["sha256"]:
            raise ValueError(f"The stored {stage} output is missing or changed")
        run = json.loads(path.read_text(encoding="utf-8"))
        if run.get("stage") != stage or run.get("video_id") != video_id:
            raise ValueError(f"The stored {stage} output does not match its video")
        runs[checkpoint["run_id"]] = run

    for part in plan["parts"]:
        for stage in ("players", "shuttle", "contacts"):
            load(part["stages"].get(stage), stage)
        for stage in ("rallies", "recognition"):
            load(part["stages"].get(stage), stage, required=False)
    load(plan.get("segments"), "segments", required=False)
    load(plan.get("identities"), "identities", required=False)
    if outcomes:
        load(plan.get("outcomes"), "outcomes", required=False)
    return runs


# Building -------------------------------------------------------------------


def _court_point(point):
    return CourtPoint(
        x=round(point[0], COURT_DECIMALS), y=round(point[1], COURT_DECIMALS)
    )


def _court_views(parts, runs):
    """Calibrations each window used, clipped to its core and merged."""
    pieces = []
    for part in parts:
        run = runs[part["players"]]
        automatic = {
            (
                c["start_frame"],
                c["end_frame"],
                tuple((p["x"], p["y"]) for p in c["corners"]),
            )
            for c in run.get("automatic_calibrations", [])
        }
        for start, end, corners in run.get("calibration_signature", []):
            corners = tuple((float(x), float(y)) for x, y in corners)
            first, last = max(start, part["core_start"]), min(end, part["core_end"])
            if first >= last:
                continue
            source = "automatic" if (start, end, corners) in automatic else "reviewed"
            pieces.append([first, last, corners, source])
    pieces.sort(key=lambda p: p[0])
    merged = []
    for piece in pieces:
        if merged and merged[-1][1] == piece[0] and merged[-1][2:] == piece[2:]:
            merged[-1][1] = piece[1]
        elif merged and merged[-1][1] > piece[0]:
            raise ValueError("Stored court calibrations overlap")
        else:
            merged.append(piece)
    views = []
    for start, end, corners, source in merged:
        matrix = court_homography(corners)
        if matrix is None:
            continue
        views.append(
            CourtView(
                start_frame=start,
                end_frame=end,
                corners=[ImagePoint(x=x, y=y) for x, y in corners],
                homography=matrix,
                source=source,
            )
        )
    return views


def _observations(inputs, parts, views):
    """Per source frame: the owning window's player observations with positions.

    Returns (observations, segments): observations[frame] is a list of
    (run_id, track_id, court_xy_or_None); segments[frame] is the
    camera segment start frame (or None outside every window).
    """
    video = inputs.video
    width, height = video["width"], video["height"]
    count = video["frame_count"]
    view_at = [None] * count
    for view in views:
        for frame in range(view.start_frame, min(view.end_frame, count)):
            view_at[frame] = view
    observations = [[] for _ in range(count)]
    segments = [None] * count
    for part in parts:
        run_id = part["players"]
        run = inputs.runs[run_id]
        rows = run["frames"]
        for frame in range(part["core_start"], min(part["core_end"], count)):
            row = rows[frame - run["start_frame"]]
            if row["frame"] != frame:
                raise ValueError("Stored player rows are not contiguous")
            segments[frame] = row.get("camera_segment_start_frame")
            view = view_at[frame] if row.get("calibration_valid") else None
            for person in row.get("players", []):
                image = feet_point(person, width, height)
                court = (
                    project(view.homography, *image)
                    if view is not None and image is not None
                    else None
                )
                observations[frame].append(
                    (
                        run_id,
                        person.get("track_id"),
                        court if on_court(court) else None,
                    )
                )
    return observations, segments


def per_view_identity(mode, observations, segments, identities_run=None):
    """Fallback identity from per-view track continuity and court end.

    Not persistent: in each camera view (between cuts) the far-end player(s)
    become P1 (and P2) and the near-end player(s) P2 (singles) or P3 and P4
    (doubles). After an end change, or in another view, the same id names a
    different human. Within one end of a doubles view, partners are kept apart
    by track continuity and a free slot; a third simultaneous group stays
    unassigned. Tracks are grouped by the identities stage's continuity id
    when it is available. Returns TrackAssignment-shaped records.
    """
    continuity = {}
    for track in (identities_run or {}).get("tracks", []):
        group = track.get("continuity_id") or track.get("actor_id")
        if group:
            continuity[(track["run_id"], track["track_id"])] = group
    groups = {}
    for frame, items in enumerate(observations):
        for run_id, track_id, court in items:
            if track_id is None:
                continue
            base = continuity.get((run_id, track_id), f"{run_id}:{track_id}")
            group = groups.setdefault(
                (segments[frame], base), {"members": {}, "xs": [], "ys": []}
            )
            span = group["members"].setdefault((run_id, track_id), [frame, frame])
            span[0], span[1] = min(span[0], frame), max(span[1], frame)
            if court is not None:
                group["xs"].append(court[0])
                group["ys"].append(court[1])
    slots = (
        {"far": ["P1"], "near": ["P2"]}
        if mode == "singles"
        else {"far": ["P1", "P2"], "near": ["P3", "P4"]}
    )
    occupancy = {}  # (segment, end) -> slot -> {"spans": [...], "x": last x}
    records = []
    margin = FALLBACK_COURT_MARGIN_M
    ordered = sorted(
        groups.items(),
        key=lambda item: (
            min(s[0] for s in item[1]["members"].values()),
            str(item[0][1]),
        ),
    )
    for (segment, _base), group in ordered:
        if len(group["ys"]) < FALLBACK_MINIMUM_FRAMES:
            continue
        x, y = statistics.median(group["xs"]), statistics.median(group["ys"])
        if not (
            -margin <= x <= COURT_WIDTH_M + margin
            and -margin <= y <= COURT_LENGTH_M + margin
        ):
            continue
        end = "far" if y < NET_Y_M else "near"
        first = min(s[0] for s in group["members"].values())
        last = max(s[1] for s in group["members"].values())
        state = occupancy.setdefault(
            (segment, end), {slot: {"spans": [], "x": None} for slot in slots[end]}
        )
        free = [
            slot
            for slot in slots[end]
            if all(b < first or a > last for a, b in state[slot]["spans"])
        ]
        if not free:
            continue
        if len(free) > 1:
            known = [s for s in free if state[s]["x"] is not None]
            if len(known) == len(free):
                free.sort(key=lambda s: abs(state[s]["x"] - x))
            elif x >= COURT_WIDTH_M / 2:
                free.reverse()
        slot = free[0]
        state[slot]["spans"].append((first, last))
        state[slot]["x"] = x
        for (run_id, track_id), (start, stop) in sorted(group["members"].items()):
            records.append(
                {
                    "run_id": run_id,
                    "track_id": track_id,
                    "start_frame": start,
                    "end_frame": stop + 1,
                    "player_id": slot,
                }
            )
    return validate_assignments(records)


def _parts(plan):
    return [
        {
            "index": part["window"]["index"],
            "core_start": part["window"]["core_start_frame"],
            "core_end": part["window"]["core_end_frame"],
            **{
                stage: (part["stages"].get(stage) or {}).get("run_id")
                for stage in (
                    "players",
                    "shuttle",
                    "contacts",
                    "rallies",
                    "recognition",
                )
            },
        }
        for part in plan["parts"]
    ]


def _owned(run, part):
    return [
        c
        for c in run.get("candidates", [])
        if part["core_start"] <= c["frame"] < part["core_end"]
    ]


def _shuttle_track(inputs, parts):
    video = inputs.video
    count = video["frame_count"]
    xs, ys = [None] * count, [None] * count
    for part in parts:
        run = inputs.runs[part["shuttle"]]
        rows = run["frames"]
        for frame in range(part["core_start"], min(part["core_end"], count)):
            row = rows[frame - run["start_frame"]]
            if row["frame"] != frame:
                raise ValueError("Stored shuttle rows are not contiguous")
            point = row.get("shuttle") or {}
            if point.get("visible") and point.get("x") is not None:
                x, y = point["x"] / video["width"], point["y"] / video["height"]
                if 0 <= x <= 1 and 0 <= y <= 1:
                    xs[frame] = round(x, IMAGE_DECIMALS)
                    ys[frame] = round(y, IMAGE_DECIMALS)
    return ShuttleTrack(x=xs, y=ys)


def _score(value):
    if value is None or not np.isfinite(value):
        return None
    return round(min(1.0, max(0.0, float(value))), 4)


def _shots(inputs, parts, observations, resolve, shuttle):
    count = inputs.video["frame_count"]
    shots = []
    for part in parts:
        contacts = inputs.runs[part["contacts"]]
        recognized = {}
        if part["recognition"]:
            for c in _owned(inputs.runs[part["recognition"]], part):
                if c.get("contact_candidate_id"):
                    recognized[c["contact_candidate_id"]] = c
        players_run = contacts.get("player_run_id") or part["players"]
        for contact in sorted(_owned(contacts, part), key=lambda c: c["frame"]):
            frame = contact["frame"]
            learned = contact.get("learned") or {}
            rec = recognized.get(contact["id"], {})
            kind = rec.get("kind") or learned.get("kind")
            kind = kind if kind in ("serve", "shot") else None
            family = None
            if kind == "shot":
                family = FAMILY_NAMES.get(rec.get("family") or learned.get("family"))
            side = rec.get("side") or learned.get("side")
            side = side if side in ("forehand", "backhand") else None
            serve_type = (
                (rec.get("serve_type") or learned.get("serve_type"))
                if kind == "serve"
                else None
            )
            track = (rec.get("hitter_hint") or {}).get(
                "track_id", contact.get("track_id")
            )
            hitter, position = None, None
            if track is not None:
                for offset in CONTACT_SEARCH:
                    near = frame + offset
                    if not 0 <= near < count:
                        continue
                    match = [
                        o
                        for o in observations[near]
                        if o[0] == players_run and o[1] == track
                    ]
                    if len(match) != 1:
                        continue
                    if hitter is None:
                        hitter = resolve(players_run, track, near)
                    if position is None and match[0][2] is not None:
                        position = match[0][2]
                    if hitter is not None and position is not None:
                        break
            ball = next(
                (
                    ImagePoint(x=shuttle.x[near], y=shuttle.y[near])
                    for offset in SHUTTLE_SEARCH
                    if 0 <= (near := frame + offset) < count
                    and shuttle.x[near] is not None
                ),
                None,
            )
            players = [
                PlayerPosition(
                    person_id=resolve(run_id, track_id, frame),
                    position=_court_point(court),
                )
                for run_id, track_id, court in observations[frame]
                if court is not None
            ]
            shots.append(
                {
                    "frame": frame,
                    "kind": kind,
                    "hitter_id": hitter,
                    "family": family,
                    "side": side,
                    "serve_type": serve_type
                    if serve_type in ("short", "long")
                    else None,
                    "confidence": _score(contact.get("score")),
                    "family_score": _score(
                        rec.get("family_score", learned.get("family_score"))
                    )
                    if kind
                    else None,
                    "side_score": _score(
                        rec.get("side_score", learned.get("side_score"))
                    )
                    if side
                    else None,
                    "hitter_position": None
                    if position is None
                    else _court_point(position),
                    "players": players,
                    "shuttle": ball,
                }
            )
    shots.sort(key=lambda s: s["frame"])
    unique = []
    for shot in shots:
        if unique and unique[-1]["frame"] == shot["frame"]:
            continue
        unique.append(shot)
    return unique


def _proposals(inputs, parts):
    """The rallies stage's serve and rally-end proposals each window owns."""
    serves, ends = [], []
    for part in parts:
        if not part["rallies"]:
            continue
        for candidate in _owned(inputs.runs[part["rallies"]], part):
            if candidate.get("kind") == "serve":
                serves.append(candidate["frame"])
            elif candidate.get("kind") == "rally_end":
                ends.append(candidate["frame"])
    return sorted(set(serves)), sorted(set(ends))


def rally_breaks(shots, times, segments, serves=(), ends=()):
    """Where rallies start and end.

    Returns (starts, closes): starts[i] = (start_frame, start_source,
    opens_with_serve) for each shot index i that opens a rally; closes[i] =
    (end_frame, "proposed_rally_end") for each shot index that a proposed
    rally end closes.

    The rallies stage's proposals come first. A serve proposal opens the
    rally at the earliest contact within SERVE_MATCH_S of it (the serve
    contact; the proposal marks the launch a few frames later). Without such
    a contact it opens a rally at the proposal itself when a contact follows
    within RALLY_BREAK_S. A rally-end proposal after a contact (within
    RALLY_BREAK_S, same camera view, before the next rally's start) ends the
    rally at the proposal. Only where no proposal decides does the fallback
    apply: a predicted serve, more than RALLY_BREAK_S without a contact, or a
    camera cut.
    """
    frames = [s["frame"] for s in shots]
    starts, closes = {}, {}
    for serve in serves:
        if not frames or not 0 <= serve < len(times):
            continue
        near = [
            i
            for i, frame in enumerate(frames)
            if abs(times[frame] - times[serve]) <= SERVE_MATCH_S
            and segments[frame] == segments[serve]
        ]
        if near:
            index, frame, matched = near[0], frames[near[0]], True
        else:
            index = bisect.bisect_right(frames, serve)
            if (
                index == len(frames)
                or times[frames[index]] - times[serve] > RALLY_BREAK_S
                or segments[frames[index]] != segments[serve]
            ):
                continue  # no contact follows this serve: no rally to open
            frame, matched = serve, False
        if index in starts:
            continue
        starts[index] = (frame, "proposed_serve", matched)
    for end in ends:
        index = bisect.bisect_left(frames, end) - 1  # last contact before it
        if index < 0 or index in closes or not 0 <= end < len(times):
            continue
        if (
            times[end] - times[frames[index]] > RALLY_BREAK_S
            or segments[end] != segments[frames[index]]
        ):
            continue
        following = index + 1
        if following < len(frames):
            if end >= starts.get(following, (frames[following],))[0]:
                continue
            starts.setdefault(
                following, (frames[following], "after_proposed_end", False)
            )
        closes[index] = (end, "proposed_rally_end")
    for index in range(len(frames)):
        if index in starts:
            continue
        if index == 0:
            starts[0] = (frames[0], "first_contact", False)
            continue
        previous = frames[index - 1]
        if shots[index]["kind"] == "serve":
            starts[index] = (frames[index], "predicted_serve", True)
        elif times[frames[index]] - times[previous] > RALLY_BREAK_S:
            starts[index] = (frames[index], "contact_gap", False)
        elif segments[frames[index]] != segments[previous]:
            starts[index] = (frames[index], "camera_cut", False)
    return starts, closes


def _rallies(shots, times, segments, serves=(), ends=()):
    starts, closes = rally_breaks(shots, times, segments, serves, ends)
    groups = []
    for index, shot in enumerate(shots):
        if index in starts:
            groups.append({"start": starts[index], "shots": []})
        groups[-1]["shots"].append((index, shot))
    rallies = []
    for number, group in enumerate(groups, 1):
        items = [
            Shot(id=f"shot-{s['frame']}", time_s=round(times[s["frame"]], 4), **s)
            for _, s in group["shots"]
        ]
        start, start_source, opens_with_serve = group["start"]
        end, end_source = closes.get(
            group["shots"][-1][0], (items[-1].frame, "last_contact")
        )
        first = items[0]
        # A serve proposal at the opening contact confirms it is the serve.
        served = first.kind == "serve" or opens_with_serve
        rallies.append(
            Rally(
                id=f"rally-{number}",
                start_frame=start,
                end_frame=end,
                start_s=round(times[start], 4),
                end_s=round(times[end], 4),
                start_source=start_source,
                end_source=end_source,
                server_id=first.hitter_id if served else None,
                shots=items,
            )
        )
    return rallies


def flight_from_summary(summary):
    """ShotFlight from an outcomes-stage flight summary (None without a fit)."""
    if not summary or summary.get("initial_speed_kmh") is None:
        return None
    speed = float(summary["initial_speed_kmh"])
    rms, inliers = float(summary["rms"]), int(summary["inliers"])
    if rms > FLIGHT_RMS_MAX or inliers < FLIGHT_INLIERS_MIN:
        quality = "poor_fit"
    elif speed >= FLIGHT_SPEED_BOUND_KMH:
        quality = "speed_bound"
    else:
        quality = "good"
    return ShotFlight(
        initial_speed_kmh=round(speed, 1),
        speed_settled_kmh=summary.get("speed_settled_kmh"),
        apex_m=summary.get("apex_m"),
        quality=quality,
        rms=round(rms, 5),
        points=int(summary["points"]),
        inliers=inliers,
        observed_s=summary.get("observed_s"),
    )


def _stage_rallies(shots, times, run):
    """Rallies from the outcomes stage's records (boundaries, landing, outcome,
    and each shot's flight when the stage fitted them).

    Shots the stage put in no rally (none, as it uses the same contacts) are
    left out.
    """
    by_frame = {s["frame"]: s for s in shots}
    rallies = []
    for record in run.get("rallies", []):
        flights = record.get("shot_flights") or []
        if len(flights) != len(record["shot_frames"]):
            flights = [None] * len(record["shot_frames"])
        fitted = dict(zip(record["shot_frames"], flights))
        members = [by_frame[f] for f in record["shot_frames"] if f in by_frame]
        if not members:
            continue
        items = [
            Shot(
                id=f"shot-{s['frame']}",
                time_s=round(times[s["frame"]], 4),
                flight=flight_from_summary(fitted.get(s["frame"])),
                **s,
            )
            for s in members
        ]
        landing = record.get("landing")
        if landing is not None:
            x, y = landing["court"]
            point = (x, y) if on_court((x, y)) else None
            items[-1] = items[-1].model_copy(
                update={
                    "landing": Landing(
                        frame=landing["frame"],
                        time_s=round(times[landing["frame"]], 4),
                        image=ImagePoint(x=landing["image"][0], y=landing["image"][1]),
                        position=None if point is None else _court_point(point),
                        in_court=landing["in_court"],
                        kind=landing["kind"],
                        source=run.get("method", "outcomes stage"),
                    )
                }
            )
        outcome = record.get("outcome")
        if outcome is not None:
            model = (run.get("model") or {}).get("title")
            outcome = RallyOutcome(
                winner_end=outcome["winner_end"],
                last_hitter_end=record.get("last_hitter_end"),
                reason=outcome["reason"],
                detail=outcome.get("detail"),
                confidence=_score(outcome.get("confidence")),
                source=model if outcome.get("source") == "model" and model else "rule",
            )
        first = items[0]
        served = first.kind == "serve" or record.get("opens_with_serve")
        start, end = record["start_frame"], max(record["end_frame"], items[-1].frame)
        rallies.append(
            Rally(
                id=f"rally-{len(rallies) + 1}",
                start_frame=start,
                end_frame=end,
                start_s=round(times[start], 4),
                end_s=round(times[end], 4),
                start_source=record["start_source"],
                end_source=record["end_source"]
                if end == record["end_frame"]
                else "last_contact",
                server_id=first.hitter_id if served else None,
                shots=items,
                outcome=outcome,
            )
        )
    return rallies


def _end_team(rally, end, teams):
    """The team seen at a court end during the rally, by majority."""
    votes = {}
    for shot in rally.shots:
        for player in shot.players:
            if player.person_id is None:
                continue
            side = "far" if player.position.y < NET_Y_M else "near"
            if side == end:
                team = teams[player.person_id]
                votes[team] = votes.get(team, 0) + 1
    if not votes:
        return None
    best = max(votes.values())
    winners = [t for t, v in votes.items() if v == best]
    return winners[0] if len(winners) == 1 else None


def _scored(rallies, persons):
    """Give outcomes their team and every rally its running score."""
    teams = {p.id: p.team for p in persons}
    game, points = 1, {"T1": 0, "T2": 0}
    result = []
    for rally in rallies:
        outcome = rally.outcome
        if outcome is not None:
            outcome = outcome.model_copy(
                update={"winner_team": _end_team(rally, outcome.winner_end, teams)}
            )
        before = dict(points)
        if outcome is not None and outcome.winner_team is not None:
            points[outcome.winner_team] += 1
        score = RallyScore(
            game=game, before=TeamScore(**before), after=TeamScore(**points)
        )
        high, low = max(points.values()), min(points.values())
        if high >= GAME_CAP or (high >= GAME_POINTS and high - low >= 2):
            game, points = game + 1, {"T1": 0, "T2": 0}
        result.append(rally.model_copy(update={"outcome": outcome, "score": score}))
    return result


def _person_tracks(inputs, observations, resolve, persons):
    times, duration = inputs.times, inputs.video["duration_s"]
    samples = []
    k = 0
    while k / TRACK_RATE_HZ < duration:
        t = k / TRACK_RATE_HZ
        i = bisect.bisect_left(times, t)
        if i >= len(times) or (i > 0 and t - times[i - 1] <= times[i] - t):
            i -= 1
        samples.append(i)
        k += 1
    tracks = {p.id: ([], []) for p in persons}
    for frame in samples:
        seen, repeated = {}, set()
        for run_id, track_id, court in observations[frame]:
            person = resolve(run_id, track_id, frame)
            if person in tracks and court is not None:
                if person in seen:
                    repeated.add(person)
                seen[person] = court
        for person in repeated:
            seen[person] = None
        for person, (xs, ys) in tracks.items():
            court = seen.get(person)
            xs.append(None if court is None else round(court[0], COURT_DECIMALS))
            ys.append(None if court is None else round(court[1], COURT_DECIMALS))
    return samples, [
        PersonTrack(person_id=person, x=xs, y=ys) for person, (xs, ys) in tracks.items()
    ]


def _models(inputs, parts, outcomes=None):
    first = parts[0]
    players = inputs.runs[first["players"]]
    shuttle = inputs.runs[first["shuttle"]]
    contacts = inputs.runs[first["contacts"]]
    recognition = (
        inputs.runs.get(first["recognition"]) if first["recognition"] else None
    )
    models = [
        ModelRef(
            stage="players",
            name=players.get("model"),
            checkpoint_sha256=players.get("checkpoint_sha256"),
        ),
        ModelRef(
            stage="shuttle",
            name=shuttle.get("model"),
            checkpoint_sha256=shuttle.get("checkpoint_sha256"),
        ),
        ModelRef(
            stage="contacts",
            name=contacts.get("method"),
            checkpoint_sha256=(contacts.get("recipe") or {}).get("event_model_sha256"),
        ),
    ]
    if recognition is not None:
        models.append(
            ModelRef(
                stage="recognition",
                name=recognition.get("model") or recognition.get("status"),
                checkpoint_sha256=recognition.get("checkpoint_sha256"),
            )
        )
    if outcomes is not None:
        model = outcomes.get("model") or {}
        models.append(
            ModelRef(
                stage="outcomes",
                # Without its model the stage calls outcomes by the landing rule.
                name=model.get("title") or "landing rule",
                checkpoint_sha256=model.get("sha256"),
            )
        )
    return models


def build_match_analysis(
    inputs, identity=None, *, names=None, overrides=(), warnings=(), created_at=None
):
    """Assemble a MatchAnalysis from loaded pipeline outputs.

    ``identity`` is an IdentityInput (or a plain dict of that shape); by
    default the persons stage's document from ``inputs.identity``. Without
    either, the per-view fallback of per_view_identity is used and the
    document says so in ``identity`` and ``warnings``.

    ``names`` maps every person id to its confirmed name. ``overrides`` are
    PersonSwap corrections (or dicts of that shape), applied in order to every
    person id the document gives. ``warnings`` are added to the document's own.
    """
    video, plan = inputs.video, inputs.plan
    if len(inputs.times) != video["frame_count"]:
        raise ValueError("Timestamps do not match the video frame count")
    parts = _parts(plan)
    views = _court_views(parts, inputs.runs)
    observations, segments = _observations(inputs, parts, views)
    identities_id = (plan.get("identities") or {}).get("run_id")
    persons_id = None
    notes = list(warnings)
    source = "supplied"
    if identity is None and inputs.identity is not None:
        identity, source = inputs.identity, "persons_stage"
        persons_id = (plan.get("persons") or {}).get("run_id")
    if identity is not None:
        identity = IdentityInput.model_validate(identity)
        persons = [Person(**p.model_dump()) for p in identity.persons]
        records = validate_assignments(
            identity.assignments,
            player_ids={p.id for p in persons},
            frame_count=video["frame_count"],
        )
        info = {
            "source": source,
            "method": identity.method,
            "persistent": True,
            "note": PERSONS_NOTE
            if source == "persons_stage"
            else "Person ids come from the supplied track assignments for the whole video.",
        }
    else:
        persons = default_persons(video["mode"])
        records = per_view_identity(
            video["mode"], observations, segments, inputs.runs.get(identities_id)
        )
        far = "P1" if video["mode"] == "singles" else "P1 and P2"
        near = "P2" if video["mode"] == "singles" else "P3 and P4"
        unavailable = plan.get("persons_unavailable")
        reason = (
            f"{unavailable.rstrip('.')}, so the persons stage did not run. "
            if unavailable
            else ""
        )
        info = {
            "source": "per_view_fallback",
            "method": "court end per camera view v1",
            "persistent": False,
            "note": (
                reason + f"Not persistent identity. In each camera view {far} are the "
                f"far-end player(s) and {near} the near-end player(s); after an "
                "end change or a cut the same id can name a different person."
            ),
        }
        notes.append(
            reason + "Player ids are per camera view, not one person through the "
            "video, so per-player statistics over the whole match are unreliable."
        )
    if names is not None:
        if set(names) != {p.id for p in persons} or not all(
            isinstance(n, str) and n.strip() for n in names.values()
        ):
            raise ValueError("Confirmed names must name every person")
        persons = [p.model_copy(update={"name": names[p.id].strip()}) for p in persons]
    swaps = [PersonSwap.model_validate(o) for o in overrides]
    resolve = _Resolver(records, swaps)
    total = assigned = 0
    for frame, items in enumerate(observations):
        for run_id, track_id, court in items:
            if court is not None:
                total += 1
                assigned += resolve(run_id, track_id, frame) is not None
    shuttle = _shuttle_track(inputs, parts)
    shots = _shots(inputs, parts, observations, resolve, shuttle)
    samples, person_tracks = _person_tracks(inputs, observations, resolve, persons)
    outcomes_id = (plan.get("outcomes") or {}).get("run_id")
    outcomes = inputs.runs.get(outcomes_id) if outcomes_id else None
    if outcomes is not None:
        rallies = _stage_rallies(shots, inputs.times, outcomes)
    else:
        outcomes_id = None
        # Older processing without the outcomes stage: no landing or winner.
        rallies = _rallies(shots, inputs.times, segments, *_proposals(inputs, parts))
    rallies = _scored(rallies, persons)
    return MatchAnalysis(
        video=VideoInfo(
            id=video["id"],
            name=video.get("name"),
            mode=video["mode"],
            fps=video["fps"],
            frame_count=video["frame_count"],
            duration_s=video["duration_s"],
            width=video["width"],
            height=video["height"],
        ),
        players=persons,
        names_confirmed=all(p.name for p in persons),
        identity=IdentityInfo(
            **info,
            assignment_count=len(records),
            assigned_observation_share=round(assigned / total, 4) if total else None,
        ),
        court=Court(views=views),
        rallies=rallies,
        tracks=Tracks(
            rate_hz=TRACK_RATE_HZ,
            sample_frames=samples,
            persons=person_tracks,
            shuttle=shuttle,
        ),
        overrides=swaps,
        warnings=list(dict.fromkeys(notes)),
        provenance=Provenance(
            created_at=created_at
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            analysis_key=plan["analysis_key"],
            segments_run_id=(plan.get("segments") or {}).get("run_id"),
            identities_run_id=identities_id,
            persons_run_id=persons_id,
            outcomes_run_id=outcomes_id,
            shot_flights=outcomes is not None
            and any("shot_flights" in r for r in outcomes.get("rallies", [])),
            parts=[
                PartRuns(
                    core_start_frame=p["core_start"],
                    core_end_frame=p["core_end"],
                    players_run_id=p["players"],
                    shuttle_run_id=p["shuttle"],
                    contacts_run_id=p["contacts"],
                    rallies_run_id=p["rallies"],
                    recognition_run_id=p["recognition"],
                )
                for p in parts
            ],
            models=_models(inputs, parts, outcomes),
        ),
    )


# Storage --------------------------------------------------------------------


def match_analysis_path(data, video_id):
    """Per-video results file, next to metadata.json and timestamps.json."""
    if not video_id or any(c in video_id for c in "/\\."):
        raise ValueError("Invalid video id")
    return Path(data) / video_id / FILENAME


def write_match_analysis(data, document):
    """Atomically replace the video's stored MatchAnalysis. Returns the path."""
    path = match_analysis_path(data, document.video.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
            output.write(document.model_dump_json())
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return path


def read_match_analysis(data, video_id):
    """The stored document, or None when it has not been built (or was built
    in an older schema version and needs rebuilding)."""
    path = match_analysis_path(data, video_id)
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if json.loads(text).get("schema_version") != SCHEMA_VERSION:
        return None
    return MatchAnalysis.model_validate_json(text)


def load_identity(path):
    return IdentityInput.model_validate_json(Path(path).read_text(encoding="utf-8"))
