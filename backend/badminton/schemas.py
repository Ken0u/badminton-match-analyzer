"""The annotation contract. Coordinates are normalized; frames are source frames."""

import itertools
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Family = Literal["clear", "lift", "net", "drop", "smash", "drive", "other", "unknown"]
Side = Literal["forehand", "backhand", "unknown"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Player(StrictModel):
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(max_length=100)
    team: Literal["T1", "T2"]
    handedness: Literal["left", "right", "unknown"] = "unknown"


class Point(StrictModel):
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class Calibration(StrictModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    corners: list[Point] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_polygon(self):
        if self.end_frame <= self.start_frame:
            raise ValueError("Calibration end must follow its start")
        pts = self.corners
        crosses = []
        for i in range(4):
            a, b, c = pts[i], pts[(i + 1) % 4], pts[(i + 2) % 4]
            crosses.append((b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x))
        if not (all(v > 0.0001 for v in crosses) or all(v < -0.0001 for v in crosses)):
            raise ValueError(
                "Court corners must form a convex quadrilateral in perimeter order"
            )
        return self


class Event(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    rally_id: str = Field(min_length=1, max_length=64)
    kind: Literal["serve", "shot", "rally_end"]
    frame: int = Field(ge=0)
    time_s: float = Field(default=0, ge=0, allow_inf_nan=False)
    player_id: str | None = None
    family: Family | None = None
    side: Side | None = None
    status: Literal["predicted", "reviewed", "corrected"] = "reviewed"
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    notes: str = Field(default="", max_length=2000)
    source_run_id: str | None = Field(default=None, max_length=64)
    candidate_id: str | None = Field(default=None, max_length=64)
    contact_start_frame: int | None = Field(default=None, ge=0)
    contact_end_frame: int | None = Field(default=None, ge=0)
    classification_run_id: str | None = Field(default=None, min_length=1, max_length=64)
    classification_candidate_id: str | None = Field(
        default=None, min_length=1, max_length=64
    )
    family_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def valid_kind_fields(self):
        if (self.classification_run_id is None) != (
            self.classification_candidate_id is None
        ):
            raise ValueError(
                "Classification provenance requires both run and candidate IDs"
            )
        if self.family_score is not None and not self.classification_run_id:
            raise ValueError("A model family score requires classification provenance")
        if self.kind == "rally_end" and self.classification_run_id:
            raise ValueError("Rally endings cannot carry a stroke classification")
        if (self.contact_start_frame is None) != (self.contact_end_frame is None):
            raise ValueError("Contact uncertainty requires both start and end frames")
        if self.contact_start_frame is not None:
            if self.kind == "rally_end":
                raise ValueError("Rally endings cannot carry a contact interval")
            if not self.contact_start_frame <= self.frame <= self.contact_end_frame:
                raise ValueError(
                    "The event frame must lie inside its inclusive contact interval"
                )
        if (self.source_run_id is None) != (self.candidate_id is None):
            raise ValueError("Proposal provenance requires both run and candidate IDs")
        if self.kind == "shot" and (self.family is None or self.side is None):
            raise ValueError("Shots require family and side (unknown is allowed)")
        if self.kind != "shot" and self.family is not None:
            raise ValueError("Only shots have a shot family")
        if self.kind == "rally_end" and (
            self.player_id is not None or self.side is not None
        ):
            raise ValueError("Rally endings have no hitter or stroke side")
        return self


class FrameRange(StrictModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered_range(self):
        if self.end_frame <= self.start_frame:
            raise ValueError("Range end must follow its start")
        return self


class ReviewWindow(FrameRange):
    id: str = Field(min_length=1, max_length=64)
    contacts_complete: bool = False
    scene: Literal["live", "replay", "unknown"] = "unknown"
    notes: str = Field(default="", max_length=2000)


class ShuttlePoint(StrictModel):
    frame: int = Field(ge=0)
    visible: bool
    x: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    y: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def observed_position(self):
        if self.visible and (self.x is None or self.y is None):
            raise ValueError("A visible shuttle requires both coordinates")
        if not self.visible and (self.x is not None or self.y is not None):
            raise ValueError("An invisible shuttle has no position")
        return self


class TrackAssignment(FrameRange):
    run_id: str = Field(min_length=1, max_length=64)
    track_id: int = Field(ge=0)
    player_id: str = Field(min_length=1, max_length=32)


class Annotations(StrictModel):
    schema_version: Literal[1] = 1
    revision: int = Field(default=0, ge=0)
    mode: Literal["singles", "doubles"]
    players: list[Player]
    calibrations: list[Calibration] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    review_windows: list[ReviewWindow] = Field(default_factory=list)
    shuttle_points: list[ShuttlePoint] = Field(default_factory=list)
    track_assignments: list[TrackAssignment] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        expected = 2 if self.mode == "singles" else 4
        if (
            len(self.players) != expected
            or len({p.id for p in self.players}) != expected
        ):
            raise ValueError(f"{self.mode} requires {expected} distinct players")
        if any(
            sum(p.team == t for p in self.players) != expected // 2
            for t in ("T1", "T2")
        ):
            raise ValueError("Teams must have equal player counts")
        ids = {p.id for p in self.players}
        if len({e.id for e in self.events}) != len(self.events):
            raise ValueError("Event IDs must be unique")
        contacts = [e.frame for e in self.events if e.kind in ("serve", "shot")]
        if len(set(contacts)) != len(contacts):
            raise ValueError("A source frame can contain only one serve or shot event")
        proposals = [
            (e.source_run_id, e.candidate_id) for e in self.events if e.source_run_id
        ]
        if len(set(proposals)) != len(proposals):
            raise ValueError("A contact suggestion can only be added once")
        classifications = [
            (e.classification_run_id, e.classification_candidate_id)
            for e in self.events
            if e.classification_run_id
        ]
        if len(set(classifications)) != len(classifications):
            raise ValueError("A classification suggestion can only be applied once")
        if any(e.player_id is not None and e.player_id not in ids for e in self.events):
            raise ValueError("Unknown player ID")
        for rally in {e.rally_id for e in self.events}:
            events = [e for e in self.events if e.rally_id == rally]
            starts = [e.frame for e in events if e.kind == "serve"]
            ends = [e.frame for e in events if e.kind == "rally_end"]
            if len(starts) > 1 or len(ends) > 1:
                raise ValueError("Each rally allows one serve and one ending")
            if starts and ends and ends[0] <= starts[0]:
                raise ValueError("A rally ending must follow its serve")
            for e in events:
                if (starts and e.frame < starts[0]) or (ends and e.frame > ends[0]):
                    raise ValueError("Events must lie within their rally boundaries")
        ranges = sorted(self.calibrations, key=lambda c: c.start_frame)
        if any(a.end_frame > b.start_frame for a, b in itertools.pairwise(ranges)):
            raise ValueError("Court calibration ranges must not overlap")
        if len({w.id for w in self.review_windows}) != len(self.review_windows):
            raise ValueError("Review window IDs must be unique")
        windows = sorted(self.review_windows, key=lambda w: w.start_frame)
        if any(a.end_frame > b.start_frame for a, b in itertools.pairwise(windows)):
            raise ValueError("Review windows must not overlap")
        if len({p.frame for p in self.shuttle_points}) != len(self.shuttle_points):
            raise ValueError("Only one shuttle label is allowed per source frame")
        from .identity import validate_assignments

        validate_assignments(self.track_assignments, player_ids=ids)
        return self


def empty_annotations(mode: str) -> Annotations:
    ids = "AB" if mode == "singles" else "ABCD"
    return Annotations(
        mode=mode,
        players=[
            Player(id=p, name=f"Player {p}", team="T1" if i < len(ids) // 2 else "T2")
            for i, p in enumerate(ids)
        ],
    )
