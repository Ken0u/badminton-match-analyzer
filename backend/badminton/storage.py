"""SQLite catalog and append-only annotation revisions."""

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

import psutil

from .schemas import Annotations, empty_annotations


class ConflictError(Exception):
    pass


def owner_alive(job):
    try:
        return (
            abs(psutil.Process(job["owner_pid"]).create_time() - job["owner_started"])
            < 0.01
        )
    except (KeyError, psutil.NoSuchProcess):
        return False
    except psutil.AccessDenied:
        return True


class Store:
    def __init__(self, data: Path):
        self.data = Path(data)
        self.data.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data / "catalog.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS annotations (
                    video_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(video_id, revision));
                CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, document TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        try:
            with db:
                yield db
        finally:
            db.close()

    def videos(self):
        with self.connect() as db:
            return [
                json.loads(r[0])
                for r in db.execute("SELECT document FROM videos ORDER BY id")
            ]

    def video(self, video_id):
        with self.connect() as db:
            row = db.execute(
                "SELECT document FROM videos WHERE id=?", (video_id,)
            ).fetchone()
        if row is None:
            raise KeyError(video_id)
        return json.loads(row[0])

    def register(self, document):
        with self.connect() as db:
            existing = db.execute(
                "SELECT document FROM videos WHERE id=?", (document["id"],)
            ).fetchone()
            if existing and json.loads(existing[0])["mode"] != document["mode"]:
                raise ValueError(
                    "This video is already registered with a different match format"
                )
            db.execute(
                "INSERT OR REPLACE INTO videos VALUES (?,?)",
                (document["id"], json.dumps(document)),
            )
            initial = empty_annotations(document["mode"])
            db.execute(
                "INSERT OR IGNORE INTO annotations(video_id,revision,document) VALUES (?,0,?)",
                (document["id"], initial.model_dump_json()),
            )

    def annotations(self, video_id, revision=None):
        self.video(video_id)
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT document FROM annotations WHERE video_id=? ORDER BY revision DESC LIMIT 1",
                    (video_id,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT document FROM annotations WHERE video_id=? AND revision=?",
                    (video_id, revision),
                ).fetchone()
        if row is None:
            raise KeyError("Annotation revision not found")
        return Annotations.model_validate_json(row[0])

    def save_annotations(self, video_id, annotations):
        video = self.video(video_id)
        times = json.loads((self.data / video_id / "timestamps.json").read_text())
        if annotations.mode != video["mode"]:
            raise ValueError("Annotation mode must match the video")
        for event in annotations.events:
            if event.frame >= len(times):
                raise ValueError("Event frame exceeds the video")
            if event.contact_end_frame is not None and event.contact_end_frame >= len(
                times
            ):
                raise ValueError("Contact interval exceeds the video")
            if event.terminal_end_frame is not None and event.terminal_end_frame >= len(
                times
            ):
                raise ValueError("Rally-end interval exceeds the video")
            event.time_s = times[event.frame]
        if any(c.end_frame > len(times) for c in annotations.calibrations):
            raise ValueError("Calibration exceeds the video")
        if any(w.end_frame > len(times) for w in annotations.review_windows):
            raise ValueError("Review window exceeds the video")
        if any(p.frame >= len(times) for p in annotations.shuttle_points):
            raise ValueError("Shuttle label exceeds the video")
        if any(r.end_frame > len(times) for r in annotations.scene_ranges):
            raise ValueError("Scene range exceeds the video")
        gap_threshold = max(0.1, 2.5 / video.get("fps", 25))
        for correction in annotations.camera_corrections:
            if correction.frame >= len(times):
                raise ValueError("Camera correction exceeds the video")
            if (
                not correction.is_cut
                and times[correction.frame] - times[correction.frame - 1]
                > gap_threshold + 1e-8
            ):
                raise ValueError("Cannot join a source timestamp discontinuity")
        from .identity import validate_assignments

        validate_assignments(
            annotations.track_assignments,
            player_ids={p.id for p in annotations.players},
            frame_count=len(times),
        )
        for run_id in {a.run_id for a in annotations.track_assignments}:
            if not any(
                j["id"] == run_id
                and j["kind"] == "players"
                and j["status"] == "completed"
                for j in self.jobs(video_id)
            ):
                raise ValueError("Player assignment requires a completed player run")
            path = self.data / video_id / "runs" / f"{run_id}.json"
            if not path.is_file():
                raise ValueError("Player assignment run is unavailable; rerun tracking")
            run = json.loads(path.read_text(encoding="utf-8"))
            if run.get("video_id") != video_id or run.get("stage") != "players":
                raise ValueError(
                    "Player assignment artifact must match its video and stage"
                )
            for assignment in annotations.track_assignments:
                if assignment.run_id != run_id:
                    continue
                if (
                    assignment.start_frame < run["start_frame"]
                    or assignment.end_frame > run["end_frame"]
                ):
                    raise ValueError("Player assignment exceeds its tracking run")
                if not any(
                    assignment.start_frame <= row["frame"] < assignment.end_frame
                    and any(
                        p["track_id"] == assignment.track_id for p in row["players"]
                    )
                    for row in run["frames"]
                ):
                    raise ValueError("Assigned tracker is absent from that frame range")
        for run_id in {
            e.classification_run_id
            for e in annotations.events
            if e.classification_run_id
        }:
            if not any(
                j["id"] == run_id
                and j["kind"] == "recognition"
                and j["status"] == "completed"
                for j in self.jobs(video_id)
            ):
                raise ValueError(
                    "Classification provenance requires a completed recognition run for this video"
                )
            path = self.data / video_id / "runs" / f"{run_id}.json"
            if not path.is_file():
                raise ValueError("Classification artifact is unavailable")
            run = json.loads(path.read_text(encoding="utf-8"))
            if run.get("video_id") != video_id or run.get("stage") != "recognition":
                raise ValueError(
                    "Classification artifact must match its video and stage"
                )
            candidates = {c["id"]: c for c in run["candidates"]}
            for event in annotations.events:
                if event.classification_run_id != run_id:
                    continue
                candidate = candidates.get(event.classification_candidate_id)
                if candidate is None:
                    raise ValueError(
                        "Classification candidate is absent from its source run"
                    )
                if event.family_score is not None and (
                    event.frame != candidate.get("frame")
                    or event.kind != candidate.get("kind")
                    or event.family != candidate.get("family")
                    or event.family_score != candidate.get("family_score")
                ):
                    raise ValueError(
                        "Clear the model family score after changing the contact or label"
                    )
        result = annotations.model_copy(deep=True)
        result.events.sort(key=lambda e: (e.frame, e.id))
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            latest = db.execute(
                "SELECT MAX(revision) FROM annotations WHERE video_id=?", (video_id,)
            ).fetchone()[0]
            if latest != annotations.revision:
                raise ConflictError(
                    "Annotations changed in another window. Reload before saving."
                )
            result.revision = latest + 1
            db.execute(
                "INSERT INTO annotations(video_id,revision,document) VALUES (?,?,?)",
                (video_id, result.revision, result.model_dump_json()),
            )
        return result

    def put_job(self, job):
        job["updated_at"] = time.time()
        with self.connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document",
                (job["id"], json.dumps(job)),
            )

    def claim_job(self, job):
        """Atomically admit one worker across CLI processes and web instances."""
        job.update(
            owner_pid=os.getpid(),
            owner_started=psutil.Process().create_time(),
            created_at=time.time(),
            updated_at=time.time(),
        )
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,document FROM jobs").fetchall()
            for job_id, document in rows:
                active = json.loads(document)
                if active["status"] not in ("queued", "running"):
                    continue
                if owner_alive(active):
                    raise ConflictError("Another processing job is running")
                active.update(
                    status="interrupted",
                    message="Worker stopped. Start a new run to retry.",
                )
                db.execute(
                    "UPDATE jobs SET document=? WHERE id=?",
                    (json.dumps(active), job_id),
                )
            db.execute("INSERT INTO jobs VALUES (?,?)", (job["id"], json.dumps(job)))
        return job

    def jobs(self, video_id=None):
        with self.connect() as db:
            jobs = [
                json.loads(r[0])
                for r in db.execute("SELECT document FROM jobs ORDER BY rowid DESC")
            ]
        return [j for j in jobs if video_id is None or j["video_id"] == video_id]

    def recover_jobs(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for job_id, document in db.execute(
                "SELECT id,document FROM jobs"
            ).fetchall():
                job = json.loads(document)
                if job["status"] in ("queued", "running") and not owner_alive(job):
                    job.update(
                        status="interrupted",
                        message="Worker stopped. Start a new run to retry.",
                        updated_at=time.time(),
                    )
                    db.execute(
                        "UPDATE jobs SET document=? WHERE id=?",
                        (json.dumps(job), job_id),
                    )
