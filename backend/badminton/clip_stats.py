"""Whole-clip statistics over one ``MatchAnalysis`` document.

Plain functions of the document only: no pipeline plans, stage runs or
annotations. ``clip_stats(document)`` returns a versioned ``ClipStats``
result for the match page's Analysis tab; docs/CLIP_STATS.md describes it.

Rules kept throughout:

- Unknown stays null (or out of the count), never a guess. Every number
  carries its sample size (``n``, ``count`` of ``n``, or a point list), so a
  reader can hide thin numbers.
- Uploads may be whole games or highlight reels, so nothing assumes that
  rallies are consecutive: no running-score statistics, only per-rally ones.
- Person ids are the document's, with its swap overrides already applied, so
  every per-player number follows the user's corrections.
- Model scores are not probabilities and are never averaged here.

Court maps use the document's metres but are turned so that the player (or,
for landings and returns, the hitter of the shot) is at the near end: a point
seen at the far end is rotated by half a turn about the court centre, which
keeps the player's own left and right.
"""

import bisect
import itertools
import math
from collections import Counter, defaultdict
from typing import Literal

import numpy as np
from pydantic import Field

from .match_analysis import (
    COURT_LENGTH_M,
    COURT_WIDTH_M,
    NET_Y_M,
    MatchAnalysis,
    PersonId,
    Team,
)
from .schemas import StrictModel

STATS_VERSION = 1

# Court maps: half-metre cells (12 across, 26 along the court) with two more
# cells beyond each line, so players behind the baseline stay on the map.
GRID_CELLS = (12, 26)
GRID_MARGIN_CELLS = 2
# Distance covered from the 10 Hz tracks:
# - a sample implying more than MAX_STEP_SPEED_M_S from both neighbours is a
#   tracking glitch (a box jump or an identity flip) and is dropped;
# - gaps up to MAX_GAP_S are bridged by a straight line, longer gaps end a
#   tracked span (their time counts as untracked);
# - positions are smoothed by a centred moving average of SMOOTH_SAMPLES
#   (feet jitter of a few centimetres per sample otherwise adds metres);
# - a rally's own distance is given only when at least MIN_COVERAGE of its
#   time is tracked; totals add every tracked span and say how much was.
MAX_STEP_SPEED_M_S = 7.0
MAX_GAP_S = 0.5
SMOOTH_SAMPLES = 3
MIN_COVERAGE = 0.8
# Doubles formation: partners closer than this are not classified.
FORMATION_MIN_M = 1.0
# Shot families after which the hitting side is attacking (it hit down) or
# defending (it sent the shuttle high to the back: the other side attacks).
ATTACKING = ("smash", "net_kill", "drop")
DEFENDING = ("lift", "clear")
# Histogram edges: shots per rally (one bin per count) and seconds.
RALLY_SHOT_EDGES = list(range(1, 32))
RALLY_SECOND_EDGES = list(range(0, 42, 2))
SPEED_EDGES = list(range(0, 460, 20))
# Single fitted speeds are too rough to name a fastest or slowest shot, so
# speed summaries leave min and max null.
NO_EXTREMES = {"min": None, "max": None}
TOP_SEQUENCES = 15
TOP_REPLIES = 10

Label = str
Side = Literal["forehand", "backhand"]


# Result model ---------------------------------------------------------------


def _finite(**kwargs):
    return Field(allow_inf_nan=False, **kwargs)


class Share(StrictModel):
    """``count`` of ``n``; ``share`` is null when ``n`` is 0."""

    count: int = Field(ge=0)
    n: int = Field(ge=0)
    share: float | None = _finite(default=None, ge=0, le=1)


class Summary(StrictModel):
    """Numbers summarised; every value is null when ``n`` is 0."""

    n: int = Field(ge=0)
    mean: float | None = _finite(default=None)
    median: float | None = _finite(default=None)
    p10: float | None = _finite(default=None)
    p90: float | None = _finite(default=None)
    min: float | None = _finite(default=None)
    max: float | None = _finite(default=None)


class Distribution(Summary):
    """A Summary with a histogram: bin i holds edges[i] <= v < edges[i + 1];
    ``below`` and ``above`` count values outside the edges."""

    edges: list[float]
    counts: list[int]
    below: int = 0
    above: int = 0


class Grid(StrictModel):
    """Counts on court cells, rows along the court (y), columns across (x).

    ``counts[row][column]`` covers y_edges[row]..y_edges[row + 1] and
    x_edges[column]..x_edges[column + 1], in metres, with the player turned
    to the near end. ``n`` samples fell on the grid and ``outside`` beyond
    it; ``seconds`` is ``n`` at the track rate.
    """

    x_edges: list[float]
    y_edges: list[float]
    counts: list[list[int]]
    n: int = Field(ge=0)
    outside: int = Field(ge=0)
    seconds: float = _finite(ge=0)


class Spot(StrictModel):
    """One shot on a court map (metres, turned; see the module docstring)."""

    x: float = _finite()
    y: float = _finite()
    # Shot label: a ShotFamily, serve_short, serve_long, serve or unknown.
    label: Label
    side: Side | None = None
    person_id: PersonId | None = None
    rally_id: str
    shot_id: str


class LandingSpot(Spot):
    """Where a rally's last shot came down (the hitter at the near end)."""

    in_court: bool | None = None
    kind: Literal["rest", "descent"]
    # The last hitter's result: winner, error, or null when unknown.
    result: Literal["winner", "error"] | None = None


class ShotBreakdown(StrictModel):
    """Contacts by kind and label. ``families`` and ``sides`` are shares of
    ``shots`` (contacts recognised as shots); ``serve_types`` of ``serves``."""

    contacts: int = Field(ge=0)
    serves: int = Field(ge=0)
    shots: int = Field(ge=0)
    # Contacts the recognition gave no kind.
    unknown_kind: int = Field(ge=0)
    families: dict[Label, Share]
    sides: dict[str, Share]
    # Per family: the forehand share of the shots with a known side.
    forehand_by_family: dict[Label, Share]
    serve_types: dict[str, Share]


class RallyDistance(StrictModel):
    rally_id: str
    metres: float = _finite(ge=0)
    # Share of the rally's time with a tracked position.
    coverage: float = _finite(ge=0, le=1)
    covered: bool  # coverage >= MIN_COVERAGE


class DistanceStats(StrictModel):
    """Distance covered on the court floor during rallies (feet, metres).

    ``total_m`` adds every tracked span of every rally (a lower bound when
    coverage is below 1); ``per_minute_m`` is it per tracked minute.
    ``per_rally`` lists every rally; ``rally_m`` summarises the rallies that
    are at least MIN_COVERAGE tracked.
    """

    total_m: float = _finite(ge=0)
    tracked_s: float = _finite(ge=0)
    rally_s: float = _finite(ge=0)
    coverage: float | None = _finite(default=None, ge=0, le=1)
    per_minute_m: float | None = _finite(default=None, ge=0)
    rally_m: Summary
    per_rally: list[RallyDistance]


class ServeStats(StrictModel):
    serves: int = Field(ge=0)
    serve_types: dict[str, Share]
    # The server's feet at the serve.
    positions: list[Spot]
    # Rallies on this serve with a known winner: won by the serving side.
    won: Share
    # Serves that ended the rally, of serves with a known outcome: faults
    # (the server lost it) and unreturned (the server won it with the serve;
    # often a missed return contact rather than an ace).
    faults: Share
    unreturned: Share


class ReturnStats(StrictModel):
    """The shot after a serve, played by this side."""

    returns: int = Field(ge=0)
    families: dict[Label, Share]
    positions: list[Spot]
    # Rallies where this side returned the serve, with a known winner.
    won: Share


class ShotResult(StrictModel):
    """One shot label's results. ``played`` counts the shots of the label,
    leaving out rally-ending shots whose outcome is unknown."""

    played: int = Field(ge=0)
    winners: int = Field(ge=0)
    errors: int = Field(ge=0)
    errors_out: int = Field(ge=0)
    errors_net: int = Field(ge=0)
    # Shots that were not errors, of played; winners of played.
    consistency: Share
    winner_rate: Share


class FinishStats(StrictModel):
    """Rally-ending shots of this side with a known outcome."""

    ended: int = Field(ge=0)
    winners: Share
    errors: Share
    by_label: dict[Label, ShotResult]


class SpeedStats(StrictModel):
    """Fitted shot speeds of one label (see docs/CLIP_STATS.md for limits).

    ``initial_kmh`` and ``apex_m`` use only good fits; ``settled_kmh`` (0.1 s
    after the contact) also uses speed_bound fits, which fix it well. Speed
    min and max are null: single fits do not name a fastest shot.
    """

    shots: int = Field(ge=0)
    fitted: int = Field(ge=0)
    good: int = Field(ge=0)
    speed_bound: int = Field(ge=0)
    poor_fit: int = Field(ge=0)
    initial_kmh: Distribution
    settled_kmh: Summary
    apex_m: Summary


class SequenceCount(StrictModel):
    """Consecutive shot labels within a rally, with how often they occur
    (``count`` of every eligible sequence of that length)."""

    labels: list[Label]
    count: int = Field(ge=0)
    n: int = Field(ge=0)
    share: float | None = _finite(default=None, ge=0, le=1)


class FormationShare(StrictModel):
    """Samples with both partners tracked and at least FORMATION_MIN_M apart."""

    front_back: Share
    side_by_side: Share
    # Samples with both tracked but too close to classify.
    close: int = Field(ge=0)


class Formation(StrictModel):
    """Doubles formation from the 10 Hz tracks during rallies. Attacking and
    defending follow the last shot played (see ATTACKING and DEFENDING)."""

    all: FormationShare
    attacking: FormationShare
    defending: FormationShare
    seconds: float = _finite(ge=0)


class PlayStats(StrictModel):
    """Statistics of one player or one team."""

    shots: ShotBreakdown
    # The hitter's feet at contact.
    contacts: list[Spot]
    # Where the other side played this side's shot: their feet at the next
    # contact (this side's hitter at the near end). Not where it would land.
    returned_at: list[Spot]
    # Rally-ending shots' landings (this side's hitter at the near end).
    landings: list[LandingSpot]
    positions: Grid
    distance: DistanceStats
    serve: ServeStats
    receive: ReturnStats
    finish: FinishStats
    # Null when the document has no shot flights (not fitted).
    speeds: dict[Label, SpeedStats] | None = None
    # Most common (other side's shot, this side's reply) pairs.
    replies: list[SequenceCount]


class PlayerStats(PlayStats):
    person_id: PersonId
    team: Team
    name: str


class TeamStats(PlayStats):
    team: Team
    person_ids: list[PersonId]
    names: list[str]
    # Rallies with a known winning team: won by this team, and how.
    rallies_won: Share
    won_by_winner: int = Field(ge=0)
    won_by_opponent_error: int = Field(ge=0)
    # Doubles only.
    formation: Formation | None = None


class ClipTotals(StrictModel):
    rallies: int = Field(ge=0)
    contacts: int = Field(ge=0)
    rally_shots: Distribution
    # end_s - start_s; rallies ending at their last contact stop there.
    rally_seconds: Distribution
    rallies_ended_at_landing: Share
    outcomes_known: Share
    shots: ShotBreakdown
    landings: list[LandingSpot]
    pairs: list[SequenceCount]
    triples: list[SequenceCount]
    speeds: dict[Label, SpeedStats] | None = None
    # Contacts without a hitter (left out of every per-player number).
    unattributed_contacts: int = Field(ge=0)
    # Rallies whose last hitter's team disagrees with the outcome's winner
    # team (an identity or contact mistake); left out of the finish numbers.
    outcome_conflicts: int = Field(ge=0)


class ClipStats(StrictModel):
    stats_version: Literal[1] = 1
    video_id: str
    mode: Literal["singles", "doubles"]
    # The MatchAnalysis these were computed from.
    analysis_schema_version: int
    analysis_created_at: str
    analysis_key: str
    # False: per-view ids, so per-player numbers mix people.
    identity_persistent: bool
    # False: no shot flights in the document, so every speeds is null.
    shot_flights: bool
    clip: ClipTotals
    players: list[PlayerStats]
    teams: list[TeamStats]
    warnings: list[str] = Field(default_factory=list)


# Small helpers --------------------------------------------------------------


def share(count, n):
    return Share(count=count, n=n, share=round(count / n, 4) if n else None)


def summary(values, digits=2):
    values = np.asarray([v for v in values if v is not None], float)
    if not len(values):
        return Summary(n=0)

    def r(v):
        return round(float(v), digits)

    return Summary(
        n=len(values),
        mean=r(values.mean()),
        median=r(np.median(values)),
        p10=r(np.percentile(values, 10)),
        p90=r(np.percentile(values, 90)),
        min=r(values.min()),
        max=r(values.max()),
    )


def distribution(values, edges, digits=2):
    values = [v for v in values if v is not None]
    counts = [0] * (len(edges) - 1)
    below = above = 0
    for v in values:
        if v < edges[0]:
            below += 1
        elif v >= edges[-1]:
            above += 1
        else:
            counts[int(np.searchsorted(edges, v, side="right")) - 1] += 1
    return Distribution(
        **summary(values, digits).model_dump(),
        edges=[float(e) for e in edges],
        counts=counts,
        below=below,
        above=above,
    )


def end_of(y):
    return "far" if y < NET_Y_M else "near"


def turned(x, y, end):
    """The point with its player at the near end (half a turn when far)."""
    if end == "far":
        return COURT_WIDTH_M - x, COURT_LENGTH_M - y
    return x, y


def label(shot):
    if shot.kind == "serve":
        return f"serve_{shot.serve_type}" if shot.serve_type else "serve"
    if shot.kind == "shot":
        return shot.family or "unknown"
    return "unknown"


def _spot(shot, rally, point, end, cls=Spot, **extra):
    x, y = turned(point.x, point.y, end)
    return cls(
        x=round(x, 2),
        y=round(y, 2),
        label=label(shot),
        side=shot.side,
        person_id=shot.hitter_id,
        rally_id=rally.id,
        shot_id=shot.id,
        **extra,
    )


def _grid_edges():
    (nx, ny), m = GRID_CELLS, GRID_MARGIN_CELLS
    cx, cy = COURT_WIDTH_M / nx, COURT_LENGTH_M / ny
    xs = [round((i - m) * cx, 3) for i in range(nx + 2 * m + 1)]
    ys = [round((j - m) * cy, 3) for j in range(ny + 2 * m + 1)]
    return xs, ys


# Context: one pass over the document ----------------------------------------


class _Context:
    def __init__(self, document: MatchAnalysis):
        self.document = document
        self.teams = {p.id: p.team for p in document.players}
        self.tracks = {t.person_id: t for t in document.tracks.persons}
        self.rate = document.tracks.rate_hz
        frames = document.tracks.sample_frames
        # Track samples of each rally (sample frames within its frames).
        self.samples = {}
        for rally in document.rallies:
            lo = int(np.searchsorted(frames, rally.start_frame, side="left"))
            hi = int(np.searchsorted(frames, rally.end_frame, side="right"))
            self.samples[rally.id] = range(lo, hi)
        self.conflicts = set()
        for rally in document.rallies:
            if self._finish(rally) == "conflict":
                self.conflicts.add(rally.id)

    def team(self, person):
        return self.teams.get(person)

    def position(self, person, k):
        track = self.tracks.get(person)
        if track is None or track.x[k] is None or track.y[k] is None:
            return None
        return track.x[k], track.y[k]

    def server(self, rally):
        """(serve shot, server id or None), or None when not opened by a serve."""
        first = rally.shots[0]
        if first.kind == "serve" or rally.server_id is not None:
            return first, rally.server_id or first.hitter_id
        return None

    def _finish(self, rally):
        """The last hitter's result (winner/error), None when unknown, or
        "conflict" when the outcome's winner team contradicts the hitter."""
        outcome, last = rally.outcome, rally.shots[-1]
        if outcome is None:
            return None
        hitter_team = self.team(last.hitter_id)
        if hitter_team is not None and outcome.winner_team is not None:
            won = outcome.winner_team == hitter_team
            if won != (outcome.reason == "winner"):
                return "conflict"
        return outcome.reason

    def finish(self, rally):
        result = self._finish(rally)
        return None if result == "conflict" else result


# Statistics of a set of persons ----------------------------------------------


def shot_breakdown(shots):
    shots = list(shots)
    played = [s for s in shots if s.kind == "shot"]
    serves = [s for s in shots if s.kind == "serve"]
    families = Counter(label(s) for s in played)
    sides = Counter(s.side or "unknown" for s in played)
    known = defaultdict(Counter)
    for s in played:
        if s.side is not None:
            known[label(s)][s.side] += 1
    types = Counter(s.serve_type or "unknown" for s in serves)
    return ShotBreakdown(
        contacts=len(shots),
        serves=len(serves),
        shots=len(played),
        unknown_kind=sum(s.kind is None for s in shots),
        families={k: share(v, len(played)) for k, v in families.most_common()},
        sides={
            k: share(sides.get(k, 0), len(played))
            for k in ("forehand", "backhand", "unknown")
        },
        forehand_by_family={
            k: share(c["forehand"], sum(c.values())) for k, c in sorted(known.items())
        },
        serve_types={
            k: share(types.get(k, 0), len(serves)) for k in ("short", "long", "unknown")
        },
    )


def distance_of(context, person, rally):
    """(metres, tracked seconds, rally seconds) for one person in one rally."""
    rate = context.rate
    ks = context.samples[rally.id]
    points = [(k, *p) for k in ks if (p := context.position(person, k)) is not None]
    rally_s = len(ks) / rate

    def fast(a, b):
        return math.dist(a[1:], b[1:]) * rate / (b[0] - a[0]) > MAX_STEP_SPEED_M_S

    # A sample too far from both neighbours is a glitch.
    kept = [
        p
        for i, p in enumerate(points)
        if not (
            0 < i < len(points) - 1
            and fast(points[i - 1], p)
            and fast(p, points[i + 1])
        )
    ]
    max_gap = round(MAX_GAP_S * rate)
    spans, current = [], []
    for p in kept:
        if current and (p[0] - current[-1][0] > max_gap or fast(current[-1], p)):
            spans.append(current)
            current = []
        current.append(p)
    if current:
        spans.append(current)
    metres = tracked = 0.0
    half = SMOOTH_SAMPLES // 2
    for span in spans:
        if len(span) < 2:
            continue
        xy = np.array([p[1:] for p in span], float)
        # Centred moving average, the window cut short at the span's ends.
        total = np.vstack([np.zeros(2), np.cumsum(xy, axis=0)])
        index = np.arange(len(xy))
        lo = np.maximum(0, index - half)
        hi = np.minimum(len(xy), index + half + 1)
        smooth = (total[hi] - total[lo]) / (hi - lo)[:, None]
        metres += float(np.linalg.norm(np.diff(smooth, axis=0), axis=1).sum())
        tracked += (span[-1][0] - span[0][0] + 1) / rate
    return metres, min(tracked, rally_s), rally_s


def distance_stats(context, persons):
    per_rally, total, tracked_total, rally_total = [], 0.0, 0.0, 0.0
    for rally in context.document.rallies:
        parts = [distance_of(context, p, rally) for p in persons]
        metres = sum(m for m, _, _ in parts)
        tracked = sum(t for _, t, _ in parts)
        rally_s = sum(r for _, _, r in parts)
        coverage = min(t / r for _, t, r in parts) if rally_s else 0.0
        total += metres
        tracked_total += tracked
        rally_total += rally_s
        per_rally.append(
            RallyDistance(
                rally_id=rally.id,
                metres=round(metres, 1),
                coverage=round(coverage, 3),
                covered=coverage >= MIN_COVERAGE,
            )
        )
    return DistanceStats(
        total_m=round(total, 1),
        tracked_s=round(tracked_total, 1),
        rally_s=round(rally_total, 1),
        coverage=round(tracked_total / rally_total, 3) if rally_total else None,
        per_minute_m=round(total / tracked_total * 60, 1) if tracked_total else None,
        rally_m=summary([r.metres for r in per_rally if r.covered], 1),
        per_rally=per_rally,
    )


def position_grid(context, persons):
    xs, ys = _grid_edges()
    counts = [[0] * (len(xs) - 1) for _ in range(len(ys) - 1)]
    n = outside = 0
    for rally in context.document.rallies:
        for k in context.samples[rally.id]:
            for person in persons:
                point = context.position(person, k)
                if point is None:
                    continue
                x, y = turned(*point, end_of(point[1]))
                column = bisect.bisect_right(xs, x) - 1
                row = bisect.bisect_right(ys, y) - 1
                if 0 <= column < len(xs) - 1 and 0 <= row < len(ys) - 1:
                    counts[row][column] += 1
                    n += 1
                else:
                    outside += 1
    return Grid(
        x_edges=xs,
        y_edges=ys,
        counts=counts,
        n=n,
        outside=outside,
        seconds=round(n / context.rate, 1),
    )


def _hitter_end(rally, index):
    """Court end of the hitter of rally.shots[index], or None."""
    shot = rally.shots[index]
    if shot.hitter_position is not None:
        return end_of(shot.hitter_position.y)
    if index == len(rally.shots) - 1 and rally.outcome is not None:
        return rally.outcome.last_hitter_end
    return None


def _landing(context, rally):
    """LandingSpot of the rally's last shot, or None (no reliable position)."""
    last = rally.shots[-1]
    landing = last.landing
    if landing is None or landing.position is None or landing.kind == "track_end":
        return None
    end = _hitter_end(rally, len(rally.shots) - 1)
    if end is None:
        # The landing is on the other side from the hitter unless it was
        # an error into the net; without the hitter's end it cannot be turned.
        return None
    return _spot(
        last,
        rally,
        landing.position,
        end,
        LandingSpot,
        in_court=landing.in_court,
        kind=landing.kind,
        result=context.finish(rally),
    )


def speed_table(shots):
    groups = defaultdict(list)
    for s in shots:
        groups[label(s)].append(s)
    table = {}
    for key, items in sorted(groups.items()):
        flights = [s.flight for s in items if s.flight is not None]
        good = [f for f in flights if f.quality == "good"]
        settled = [f for f in flights if f.quality in ("good", "speed_bound")]
        table[key] = SpeedStats(
            shots=len(items),
            fitted=len(flights),
            good=len(good),
            speed_bound=sum(f.quality == "speed_bound" for f in flights),
            poor_fit=sum(f.quality == "poor_fit" for f in flights),
            # The launch-support diagnostics on a flight never hide a speed:
            # good fits give the launch speed, speed-bound ones the settled one.
            initial_kmh=distribution(
                [f.initial_speed_kmh for f in good], SPEED_EDGES, 1
            ).model_copy(update=NO_EXTREMES),
            settled_kmh=summary([f.speed_settled_kmh for f in settled], 1).model_copy(
                update=NO_EXTREMES
            ),
            apex_m=summary([f.apex_m for f in good]),
        )
    return table


def _sequences(rallies, length, teams, last_in=None):
    """Counter of label tuples of ``length`` consecutive shots, and the
    number of eligible sequences. A sequence is eligible when every label is
    known and no two consecutive shots are by the same team (that is a
    contact or identity mistake). With ``last_in`` only sequences whose last
    shot's hitter is in that set count."""
    counter, n = Counter(), 0
    for rally in rallies:
        for window in zip(*(rally.shots[i:] for i in range(length))):
            labels = tuple(label(s) for s in window)
            if "unknown" in labels:
                continue
            hitters = [teams.get(s.hitter_id) for s in window]
            if any(a is not None and a == b for a, b in itertools.pairwise(hitters)):
                continue
            if last_in is not None and window[-1].hitter_id not in last_in:
                continue
            counter[labels] += 1
            n += 1
    return counter, n


def _top(counter, n, limit):
    return [
        SequenceCount(
            labels=list(labels),
            count=count,
            n=n,
            share=round(count / n, 4) if n else None,
        )
        for labels, count in counter.most_common(limit)
    ]


def play_stats(context, persons):
    """PlayStats of the given person ids (one player, or a team)."""
    document = context.document
    members = set(persons)
    side_teams = {context.team(p) for p in persons}
    rallies = document.rallies
    own = [
        (rally, i, shot)
        for rally in rallies
        for i, shot in enumerate(rally.shots)
        if shot.hitter_id in members
    ]
    contacts, returned_at, landings = [], [], []
    for rally, i, shot in own:
        if shot.hitter_position is not None:
            contacts.append(
                _spot(
                    shot,
                    rally,
                    shot.hitter_position,
                    end_of(shot.hitter_position.y),
                )
            )
        if i + 1 < len(rally.shots):
            reply = rally.shots[i + 1]
            team = context.team(reply.hitter_id)
            end = _hitter_end(rally, i)
            if (
                reply.hitter_position is not None
                and team is not None
                and team not in side_teams
                and end is not None
            ):
                returned_at.append(_spot(shot, rally, reply.hitter_position, end))
        else:
            spot = _landing(context, rally)
            if spot is not None:
                landings.append(spot)

    # Serve and receive.
    serves, returns = [], []
    for rally in rallies:
        opened = context.server(rally)
        if opened is None:
            continue
        serve, server = opened
        if server in members:
            serves.append((rally, serve))
        elif (
            len(rally.shots) > 1
            and rally.shots[1].hitter_id in members
            and context.team(server) not in side_teams
        ):
            returns.append((rally, rally.shots[1]))

    def won(rally_list, team_of):
        known = [r for r in rally_list if r.outcome and r.outcome.winner_team]
        return share(
            sum(r.outcome.winner_team == team_of(r) for r in known), len(known)
        )

    serve_types = Counter(s.serve_type or "unknown" for _, s in serves)
    alone = [
        (r, context.finish(r))
        for r, _ in serves
        if len(r.shots) == 1 and context.finish(r) is not None
    ]
    known_serve = [
        r for r, _ in serves if len(r.shots) > 1 or context.finish(r) is not None
    ]
    serve = ServeStats(
        serves=len(serves),
        serve_types={
            k: share(serve_types.get(k, 0), len(serves))
            for k in ("short", "long", "unknown")
        },
        positions=[
            _spot(s, r, s.hitter_position, end_of(s.hitter_position.y))
            for r, s in serves
            if s.hitter_position is not None
        ],
        won=won([r for r, _ in serves], lambda r: context.team(context.server(r)[1])),
        faults=share(sum(res == "error" for _, res in alone), len(known_serve)),
        unreturned=share(sum(res == "winner" for _, res in alone), len(known_serve)),
    )
    return_families = Counter(label(s) for _, s in returns)
    receive = ReturnStats(
        returns=len(returns),
        families={k: share(v, len(returns)) for k, v in return_families.most_common()},
        positions=[
            _spot(s, r, s.hitter_position, end_of(s.hitter_position.y))
            for r, s in returns
            if s.hitter_position is not None
        ],
        won=won([r for r, _ in returns], lambda r: context.team(r.shots[1].hitter_id)),
    )

    # Finishing shots and consistency.
    results = defaultdict(Counter)
    ended = winners = errors = 0
    for rally, i, shot in own:
        key = label(shot)
        if i + 1 < len(rally.shots):
            results[key]["played"] += 1
            continue
        result = context.finish(rally)
        if result is None:
            continue
        results[key]["played"] += 1
        ended += 1
        if result == "winner":
            results[key]["winners"] += 1
            winners += 1
        else:
            results[key]["errors"] += 1
            errors += 1
            detail = rally.outcome.detail
            if detail in ("out", "net"):
                results[key][f"errors_{detail}"] += 1
    finish = FinishStats(
        ended=ended,
        winners=share(winners, ended),
        errors=share(errors, ended),
        by_label={
            key: ShotResult(
                played=c["played"],
                winners=c["winners"],
                errors=c["errors"],
                errors_out=c["errors_out"],
                errors_net=c["errors_net"],
                consistency=share(c["played"] - c["errors"], c["played"]),
                winner_rate=share(c["winners"], c["played"]),
            )
            for key, c in sorted(results.items())
        },
    )
    pairs, n = _sequences(rallies, 2, context.teams, members)
    return {
        "shots": shot_breakdown(s for _, _, s in own),
        "contacts": contacts,
        "returned_at": returned_at,
        "landings": landings,
        "positions": position_grid(context, persons),
        "distance": distance_stats(context, persons),
        "serve": serve,
        "receive": receive,
        "finish": finish,
        "speeds": speed_table(s for _, _, s in own)
        if document.provenance.shot_flights
        else None,
        "replies": _top(pairs, n, TOP_REPLIES),
    }


# Doubles formation -------------------------------------------------------------


def _phases(context, rally, team):
    """Per track sample of the rally: attacking, defending or None for
    ``team``, from the last shot played before the sample."""
    frames = context.document.tracks.sample_frames
    phase = {}
    shots = rally.shots
    for i, shot in enumerate(shots):
        hitter_team = context.team(shot.hitter_id)
        until = shots[i + 1].frame if i + 1 < len(shots) else rally.end_frame + 1
        key = label(shot)
        if hitter_team is None:
            state = None
        elif key in ATTACKING or key in DEFENDING or key == "serve_long":
            attacking_hitter = key in ATTACKING
            state = (
                ("attacking" if attacking_hitter else "defending")
                if hitter_team == team
                else ("defending" if attacking_hitter else "attacking")
            )
        else:
            state = None
        for k in context.samples[rally.id]:
            if shot.frame <= frames[k] < until:
                phase[k] = state
    return phase


def formation(context, team):
    persons = [p.id for p in context.document.players if p.team == team]
    if len(persons) != 2:
        return None
    counts = {name: Counter() for name in ("all", "attacking", "defending")}
    seconds = 0
    for rally in context.document.rallies:
        phase = _phases(context, rally, team)
        for k in context.samples[rally.id]:
            a, b = (context.position(p, k) for p in persons)
            if a is None or b is None:
                continue
            seconds += 1
            dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
            if math.hypot(dx, dy) < FORMATION_MIN_M:
                kind = "close"
            else:
                kind = "front_back" if dy >= dx else "side_by_side"
            counts["all"][kind] += 1
            if phase.get(k) in ("attacking", "defending"):
                counts[phase[k]][kind] += 1

    def shares(c):
        n = c["front_back"] + c["side_by_side"]
        return FormationShare(
            front_back=share(c["front_back"], n),
            side_by_side=share(c["side_by_side"], n),
            close=c["close"],
        )

    return Formation(
        all=shares(counts["all"]),
        attacking=shares(counts["attacking"]),
        defending=shares(counts["defending"]),
        seconds=round(seconds / context.rate, 1),
    )


# Whole clip ----------------------------------------------------------------------


def clip_totals(context):
    document = context.document
    rallies = document.rallies
    shots = [s for r in rallies for s in r.shots]
    pairs, n2 = _sequences(rallies, 2, context.teams)
    triples, n3 = _sequences(rallies, 3, context.teams)
    return ClipTotals(
        rallies=len(rallies),
        contacts=len(shots),
        rally_shots=distribution([len(r.shots) for r in rallies], RALLY_SHOT_EDGES),
        rally_seconds=distribution(
            [r.end_s - r.start_s for r in rallies], RALLY_SECOND_EDGES
        ),
        rallies_ended_at_landing=share(
            sum(r.end_source == "landing" for r in rallies), len(rallies)
        ),
        outcomes_known=share(sum(r.outcome is not None for r in rallies), len(rallies)),
        shots=shot_breakdown(shots),
        landings=[spot for r in rallies if (spot := _landing(context, r)) is not None],
        pairs=_top(pairs, n2, TOP_SEQUENCES),
        triples=_top(triples, n3, TOP_SEQUENCES),
        speeds=speed_table(shots) if document.provenance.shot_flights else None,
        unattributed_contacts=sum(s.hitter_id is None for s in shots),
        outcome_conflicts=len(context.conflicts),
    )


def clip_stats(document: MatchAnalysis) -> ClipStats:
    """Every clip statistic of one MatchAnalysis document."""
    context = _Context(document)
    warnings = list(document.warnings)
    if not document.identity.persistent:
        warnings.append(
            "Player ids are per camera view, so per-player and per-team numbers "
            "mix people after an end change or a cut."
        )
    if not document.provenance.shot_flights:
        warnings.append("Shot flights were not fitted for this video: no speeds.")
    if not document.court.views:
        warnings.append(
            "No camera view has a court fit: positions, distance, landings and "
            "formation are empty."
        )
    players = [
        PlayerStats(
            person_id=p.id,
            team=p.team,
            name=p.name,
            **play_stats(context, [p.id]),
        )
        for p in document.players
    ]
    teams = []
    for team in ("T1", "T2"):
        members = [p for p in document.players if p.team == team]
        ids = [p.id for p in members]
        known = [r for r in document.rallies if r.outcome and r.outcome.winner_team]
        won = [r for r in known if r.outcome.winner_team == team]
        by_winner = sum(
            context.finish(r) == "winner"
            and context.team(r.shots[-1].hitter_id) in (team, None)
            for r in won
        )
        teams.append(
            TeamStats(
                team=team,
                person_ids=ids,
                names=[p.name for p in members],
                rallies_won=share(len(won), len(known)),
                won_by_winner=by_winner,
                won_by_opponent_error=sum(
                    context.finish(r) == "error"
                    and context.team(r.shots[-1].hitter_id) != team
                    for r in won
                ),
                formation=formation(context, team)
                if document.video.mode == "doubles"
                else None,
                **play_stats(context, ids),
            )
        )
    return ClipStats(
        video_id=document.video.id,
        mode=document.video.mode,
        analysis_schema_version=document.schema_version,
        analysis_created_at=document.provenance.created_at,
        analysis_key=document.provenance.analysis_key,
        identity_persistent=document.identity.persistent,
        shot_flights=document.provenance.shot_flights,
        clip=clip_totals(context),
        players=players,
        teams=teams,
        warnings=list(dict.fromkeys(warnings)),
    )


__all__ = [
    "STATS_VERSION",
    "ClipStats",
    "clip_stats",
    "distance_of",
    "label",
    "shot_breakdown",
    "turned",
]
