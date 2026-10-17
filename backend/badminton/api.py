import csv
import io
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from . import config
from .access import AccessMiddleware
from .ingest import inspect_video, read_frame
from .schemas import Annotations, StrictModel
from .storage import ConflictError, Store
from .video import (
    SourceChangedError,
    resolve_source,
    timestamps_for,
    validate_range,
    write_json,
)

logger = logging.getLogger(__name__)


class ImportRequest(StrictModel):
    path: str
    mode: str = "singles"


class TrackingRequest(StrictModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    stride: int = Field(default=1, ge=1, le=10)
    stage: Literal["players", "shuttle"] = "players"


class ContactsRequest(StrictModel):
    shuttle_run_id: str
    player_run_id: str | None = None


class EvaluationRequest(StrictModel):
    contacts_run_id: str | None = None
    shuttle_run_id: str | None = None
    tolerance_s: float = Field(default=0.12, gt=0, le=1, allow_inf_nan=False)
    tolerance_diagonal: float = Field(default=0.005, gt=0, le=0.1, allow_inf_nan=False)


class YoutubeRequest(StrictModel):
    url: str = Field(min_length=1, max_length=2048)
    mode: Literal["singles", "doubles"] = "singles"


class RecognitionRequest(StrictModel):
    player_run_id: str
    shuttle_run_id: str
    contacts_run_id: str | None = None
    include_reviewed: bool = True
    min_family_score: float = Field(default=0.5, ge=0, le=1, allow_inf_nan=False)


def create_app(
    root: Path = config.ROOT,
    data: Path = config.DATA,
    *,
    max_media_bytes: int = config.MAX_MEDIA_BYTES,
    username: str | None = None,
    password: str | None = None,
):
    if type(max_media_bytes) is not int or max_media_bytes <= 0:
        raise ValueError("Media byte limit must be a positive integer")
    username = (
        username if username is not None else os.environ.get("BADMINTON_USERNAME")
    )
    password = (
        password if password is not None else os.environ.get("BADMINTON_PASSWORD")
    )
    if bool(username) != bool(password):
        raise ValueError("Set both BADMINTON_USERNAME and BADMINTON_PASSWORD")
    root, data = Path(root).resolve(), Path(data).resolve()
    store = Store(data)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
    store.recover_jobs()

    @asynccontextmanager
    async def lifespan(app):
        yield
        executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="Badminton match analyzer", lifespan=lifespan)
    app.add_middleware(
        AccessMiddleware,
        username=username,
        password=password,
        max_bytes=max_media_bytes,
    )
    app.state.store = store

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return Response("Not found", status_code=404)

    def source(video):
        try:
            return resolve_source(video, root)
        except SourceChangedError as exc:
            raise HTTPException(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc

    def enqueue(kind, video_id, task):
        job = {
            "id": uuid4().hex,
            "kind": kind,
            "video_id": video_id,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
        }
        try:
            store.claim_job(job)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc

        def run():
            def progress(value):
                job.update(progress=round(min(value, 1), 3))
                store.put_job(job)

            try:
                job.update(status="running", message="Processing")
                store.put_job(job)
                summary = task(job["id"], progress)
                job.update(
                    status="completed", progress=1, message="Completed", summary=summary
                )
            except Exception as exc:
                logger.exception("Job failed: %s", job["id"])
                job.update(status="failed", message=str(exc))
            store.put_job(job)

        try:
            executor.submit(run)
        except RuntimeError as exc:
            job.update(
                status="failed", message="Worker is shutting down. Retry after restart."
            )
            store.put_job(job)
            raise HTTPException(503, job["message"]) from exc
        return dict(job)

    def register_media(path, mode, progress, provenance):
        prior = {v["id"]: v for v in store.videos()}
        try:
            document = inspect_video(path, mode, store, root, progress)
            existing = prior.get(document["id"])
            if existing and existing["path"] != document["path"]:
                try:
                    resolve_source(existing, root)
                except (ValueError, FileNotFoundError):
                    pass
                else:
                    document["path"] = existing["path"]
                    path.unlink(missing_ok=True)
            document["source"] = provenance
            document["source_type"] = provenance["source_type"]
            document["name"] = (
                provenance.get("name") or provenance.get("title") or document["name"]
            )
            write_json(data / document["id"] / "metadata.json", document)
            store.register(document)
            return document
        except BaseException:
            if not any(
                v["path"] == path.relative_to(root).as_posix() for v in store.videos()
            ):
                path.unlink(missing_ok=True)
            raise

    @app.post("/api/upload", status_code=202)
    def upload(
        file: UploadFile = File(...),
        mode: Literal["singles", "doubles"] = Form("singles"),
    ):
        from .media_import import MediaTooLargeError, save_upload

        try:
            path = save_upload(
                file.file,
                file.filename or "",
                root / ".media",
                max_bytes=max_media_bytes,
            )
        except MediaTooLargeError as exc:
            raise HTTPException(413, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            file.file.close()
        try:
            return enqueue(
                "import",
                None,
                lambda job_id, progress: register_media(
                    path,
                    mode,
                    progress,
                    {
                        "name": (file.filename or "Uploaded match")
                        .replace("\\", "/")
                        .rsplit("/", 1)[-1][:200],
                        "source_type": "upload",
                    },
                ),
            )
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    @app.post("/api/import/youtube", status_code=202)
    def youtube(body: YoutubeRequest):
        from .media_import import canonical_youtube_url, download_youtube

        try:
            canonical = canonical_youtube_url(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        def task(job_id, progress):
            path, provenance = download_youtube(
                canonical,
                root / ".media",
                max_bytes=max_media_bytes,
                progress=lambda value: progress(value * 0.45),
            )
            return register_media(
                path, body.mode, lambda value: progress(0.45 + value * 0.55), provenance
            )

        return enqueue("import", None, task)

    @app.get("/api/videos")
    def videos():
        return store.videos()

    @app.post("/api/import", status_code=202)
    def import_video(body: ImportRequest):
        if body.mode not in ("singles", "doubles"):
            raise HTTPException(422, "Mode must be singles or doubles")
        path = (root / body.path).resolve()
        if (
            not path.is_relative_to(root)
            or not path.is_file()
            or path.suffix.lower() not in (".mp4", ".mov", ".mkv", ".avi", ".webm")
        ):
            raise HTTPException(422, "Choose a video path inside the project folder")
        return enqueue(
            "import",
            None,
            lambda job_id, progress: inspect_video(
                path, body.mode, store, root, progress
            ),
        )

    @app.get("/api/videos/{video_id}")
    def video(video_id: str):
        return store.video(video_id)

    @app.get("/api/videos/{video_id}/timestamps")
    def timestamps(video_id: str):
        store.video(video_id)
        return FileResponse(
            data / video_id / "timestamps.json", media_type="application/json"
        )

    @app.get("/api/videos/{video_id}/media")
    def media(video_id: str):
        return FileResponse(source(store.video(video_id)))

    @app.get("/api/videos/{video_id}/image/{name}")
    def image(video_id: str, name: str):
        store.video(video_id)
        if name not in ("poster.jpg", "contact-sheet.jpg"):
            raise HTTPException(404)
        return FileResponse(data / video_id / name, media_type="image/jpeg")

    @app.get("/api/videos/{video_id}/frame")
    def frame(video_id: str, index: int = Query(ge=0)):
        v = store.video(video_id)
        if index >= v["frame_count"]:
            raise HTTPException(422, "Frame exceeds video length")
        times = timestamps_for(data, video_id)
        img = read_frame(source(v), times[index], v["source_start_s"])
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=90)
        return Response(
            buffer.getvalue(),
            media_type="image/jpeg",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/api/videos/{video_id}/annotations")
    def annotations(video_id: str):
        return store.annotations(video_id)

    @app.put("/api/videos/{video_id}/annotations")
    def save(video_id: str, body: Annotations):
        try:
            return store.save_annotations(video_id, body)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/videos/{video_id}/revisions/{revision}")
    def revision(video_id: str, revision: int):
        return store.annotations(video_id, revision)

    @app.get("/api/videos/{video_id}/export")
    def export(video_id: str, format: str = "json"):
        v = store.video(video_id)
        doc = store.annotations(video_id)
        if format == "json":
            payload = {"video": v, "annotations": doc.model_dump()}
            return Response(
                json.dumps(payload, indent=2),
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="{video_id}.json"'
                },
            )
        if format != "csv":
            raise HTTPException(422, "Format must be json or csv")
        buffer = io.StringIO(newline="")
        fields = [
            "id",
            "rally_id",
            "kind",
            "frame",
            "time_s",
            "player_id",
            "team_id",
            "family",
            "side",
            "status",
            "confidence",
            "notes",
            "source_run_id",
            "candidate_id",
            "contact_start_frame",
            "contact_end_frame",
            "classification_run_id",
            "classification_candidate_id",
            "family_score",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for event in doc.events:
            row = event.model_dump()
            player = next((p for p in doc.players if p.id == event.player_id), None)
            row["team_id"] = player.team if player else None
            # Prevent text annotations from becoming spreadsheet formulas.
            for key, value in row.items():
                if isinstance(value, str) and value.startswith(
                    ("=", "+", "-", "@", "\t", "\r")
                ):
                    row[key] = "'" + value
            writer.writerow(row)
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{video_id}.csv"'},
        )

    @app.get("/api/jobs")
    def jobs(video_id: str | None = None):
        store.recover_jobs()
        return store.jobs(video_id)

    @app.post("/api/videos/{video_id}/track", status_code=202)
    def track(video_id: str, body: TrackingRequest):
        v = store.video(video_id)
        times = timestamps_for(data, video_id)
        try:
            validate_range(v, times, body.start_frame, body.end_frame)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        source(v)
        if body.stage == "shuttle" and body.stride != 1:
            raise HTTPException(
                422, "Shuttle inference requires every source frame (stride 1)"
            )
        from .shuttle import track_shuttle
        from .tracking import track_players

        snapshot = store.annotations(video_id)

        def task(job_id, progress):
            output = data / video_id / "runs" / f"{job_id}.json"
            if body.stage == "players":
                return track_players(
                    v,
                    root,
                    data,
                    snapshot,
                    body.start_frame,
                    body.end_frame,
                    body.stride,
                    progress,
                    output,
                )
            return track_shuttle(
                v, root, data, body.start_frame, body.end_frame, progress, output
            )

        return enqueue(body.stage, video_id, task)

    def load_run(video_id, job_id, kind=None):
        job = next(
            (
                j
                for j in store.jobs(video_id)
                if j["id"] == job_id
                and j["status"] == "completed"
                and (kind is None or j["kind"] == kind)
            ),
            None,
        )
        if job is None:
            raise HTTPException(404, "Completed tracking run not found")
        path = data / video_id / "runs" / f"{job_id}.json"
        if not path.is_file():
            raise HTTPException(
                404, "Run artifact is unavailable. Rerun this analysis window."
            )
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("video_id") != video_id or result.get("stage") != job["kind"]:
            raise HTTPException(422, "Run artifact does not match its video or stage")
        return result

    @app.post("/api/videos/{video_id}/contacts", status_code=202)
    def contacts(video_id: str, body: ContactsRequest):
        from .contacts import METHOD, propose_contacts

        v = store.video(video_id)
        shuttle_run = load_run(video_id, body.shuttle_run_id, "shuttle")
        player_run = (
            load_run(video_id, body.player_run_id, "players")
            if body.player_run_id
            else None
        )

        def task(job_id, progress):
            candidates = propose_contacts(shuttle_run, player_run, v)
            result = {
                "schema_version": 1,
                "stage": "contacts",
                "video_id": video_id,
                "shuttle_run_id": body.shuttle_run_id,
                "player_run_id": body.player_run_id,
                "start_frame": shuttle_run["start_frame"],
                "end_frame": shuttle_run["end_frame"],
                "method": METHOD,
                "interval_bounds": "inclusive",
                "candidates": candidates,
            }
            write_json(data / video_id / "runs" / f"{job_id}.json", result)
            return {k: v for k, v in result.items() if k != "candidates"} | {
                "candidate_count": len(candidates)
            }

        return enqueue(
            "contacts",
            video_id,
            task,
        )

    @app.get("/api/videos/{video_id}/runs/{job_id}")
    def run(video_id: str, job_id: str):
        store.video(video_id)
        if not any(
            j["id"] == job_id
            and j["status"] == "completed"
            and j["kind"] in ("players", "shuttle", "contacts", "recognition")
            for j in store.jobs(video_id)
        ):
            raise HTTPException(404)
        if not (data / video_id / "runs" / f"{job_id}.json").is_file():
            raise HTTPException(
                404, "Run artifact is unavailable. Rerun this analysis window."
            )
        result = load_run(video_id, job_id)
        doc = store.annotations(video_id)
        from .identity import apply_assignments, resolve_contact_player

        if result.get("stage", "players") == "players":
            result = apply_assignments(result, doc.track_assignments, job_id)
        elif result.get("stage") == "contacts":
            for candidate in result["candidates"]:
                candidate["player_id"] = resolve_contact_player(
                    candidate["frame"],
                    candidate.get("track_id"),
                    doc.track_assignments,
                    result.get("player_run_id"),
                )
        elif result.get("stage") == "recognition":
            for candidate in result["candidates"]:
                if hint := candidate.get("hitter_hint"):
                    hint["player_id"] = resolve_contact_player(
                        candidate["frame"],
                        hint.get("track_id"),
                        doc.track_assignments,
                        result.get("player_run_id"),
                    )
        result["identity_annotation_revision"] = doc.revision
        return result

    @app.post("/api/videos/{video_id}/recognize", status_code=202)
    def recognize(video_id: str, body: RecognitionRequest):
        from .recognition import recognition_targets, recognize_strokes

        v = store.video(video_id)
        source(v)
        if v["mode"] != "singles":
            raise HTTPException(
                422,
                "The pretrained family model currently supports singles; doubles needs its own validated model",
            )
        players = load_run(video_id, body.player_run_id, "players")
        shuttle = load_run(video_id, body.shuttle_run_id, "shuttle") | {
            "run_id": body.shuttle_run_id
        }
        if players.get("stride", 1) != 1:
            raise HTTPException(
                422, "Classifying strokes requires player tracking at stride 1"
            )
        contacts = (
            load_run(video_id, body.contacts_run_id, "contacts")
            if body.contacts_run_id
            else None
        )
        if contacts and (
            contacts.get("shuttle_run_id") != body.shuttle_run_id
            or contacts.get("player_run_id") not in (None, body.player_run_id)
        ):
            raise HTTPException(
                422, "Contact proposals must use these same tracking runs"
            )
        snapshot = store.annotations(video_id)
        targets = recognition_targets(
            snapshot,
            contacts,
            body.include_reviewed,
            start_frame=max(players["start_frame"], shuttle["start_frame"]),
            end_frame=min(players["end_frame"], shuttle["end_frame"]),
        )
        if not targets:
            raise HTTPException(
                422,
                "Review shot contacts or generate contact suggestions before classifying",
            )
        if len(targets) > 500:
            raise HTTPException(422, "Classify at most 500 contacts per run")
        return enqueue(
            "recognition",
            video_id,
            lambda job_id, progress: recognize_strokes(
                v,
                timestamps_for(data, video_id),
                snapshot,
                players,
                shuttle,
                targets,
                body.player_run_id,
                progress,
                data / video_id / "runs" / f"{job_id}.json",
                body.min_family_score,
                contacts_run_id=body.contacts_run_id,
            ),
        )

    @app.post("/api/videos/{video_id}/evaluate")
    def evaluate(video_id: str, body: EvaluationRequest):
        from .evaluation import evaluate_contacts, evaluate_shuttle

        if not body.contacts_run_id and not body.shuttle_run_id:
            raise HTTPException(422, "Choose a contact or shuttle run to evaluate")
        v = store.video(video_id)
        source(v)
        doc = store.annotations(video_id).model_dump()
        result = {
            "video_id": video_id,
            "video_sha256": v["sha256"],
            "annotation_revision": doc["revision"],
        }
        try:
            if body.contacts_run_id:
                artifact = load_run(video_id, body.contacts_run_id, "contacts")
                result["contacts"] = evaluate_contacts(
                    v, doc, artifact, body.tolerance_s
                )
                result["contacts"]["run_id"] = body.contacts_run_id
            if body.shuttle_run_id:
                artifact = load_run(video_id, body.shuttle_run_id, "shuttle")
                result["shuttle"] = evaluate_shuttle(
                    v, doc, artifact, body.tolerance_diagonal
                )
                result["shuttle"]["run_id"] = body.shuttle_run_id
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return result

    app.mount(
        "/",
        StaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="viewer",
    )
    return app
