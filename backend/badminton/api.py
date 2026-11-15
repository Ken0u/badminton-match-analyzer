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
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from . import config
from . import matches as match_flow
from .access import AccessMiddleware
from .calibration_context import court_context_changed, court_run_context
from .ingest import inspect_video
from .jobs import JobCancelled
from .match_analysis import MatchAnalysis, read_match_analysis
from .orientation import OrientationError
from .schemas import Annotations, StrictModel
from .storage import ConflictError, Store
from .video import (
    SourceChangedError,
    iter_frames,
    resolve_source,
    timestamps_for,
    validate_range,
    write_json,
)

logger = logging.getLogger(__name__)


class _ViewerStaticFiles(StaticFiles):
    """Serve the built application at its two routes without masking API errors."""

    async def get_response(self, path, scope):
        if path.strip("/") in {"library", "editor"}:
            path = "index.html"
        response = await super().get_response(path, scope)
        if path in {
            ".",
            "",
            "index.html",
            "app.js",
            "style.css",
            "build-manifest.json",
        }:
            # Entry URLs remain stable across releases. Revalidate them so an
            # older HTML/module cache cannot mix two versions of the viewer.
            response.headers["Cache-Control"] = "no-cache"
        return response


class _ExportDownloadResponse(StreamingResponse):
    """Own the snapshot throughout ASGI, including cancellation before iteration."""

    def __init__(self, download):
        self.handle = download["file"]
        try:
            super().__init__(
                self.chunks(),
                media_type=download["media_type"],
                headers={
                    "Content-Disposition": (
                        f'attachment; filename="{download["filename"]}"'
                    ),
                    "Content-Length": str(download["size_bytes"]),
                },
            )
        except BaseException:
            self.handle.close()
            raise

    def chunks(self):
        while chunk := self.handle.read(64 * 1024):
            yield chunk

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # A generator finally/background task alone can be skipped when
            # response-start fails or cancellation precedes its first read.
            self.handle.close()


class ImportRequest(StrictModel):
    path: str
    mode: str = "singles"


class TrackingRequest(StrictModel):
    start_frame: int = Field(ge=0)
    end_frame: int = Field(gt=0)
    stride: int = Field(default=1, ge=1, le=10)
    stage: Literal["players", "shuttle"] = "players"
    player_model: Literal["small", "nano"] = "small"
    auto_calibrate: bool = True


class AnalysisRequest(StrictModel):
    player_model: Literal["small", "nano"] = "small"
    auto_calibrate: bool = True
    recognize: bool = True


class ContactsRequest(StrictModel):
    shuttle_run_id: str
    player_run_id: str | None = None
    include_audio: bool = False


class RalliesRequest(StrictModel):
    player_run_id: str
    shuttle_run_id: str


class EvaluationRequest(StrictModel):
    contacts_run_id: str | None = None
    shuttle_run_id: str | None = None
    recognition_run_id: str | None = None
    rallies_run_id: str | None = None
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


class MediaExportRequest(StrictModel):
    revision: int = Field(ge=0, strict=True)
    mode: Literal["plain-rallies", "annotated-rallies", "annotated-full"]


def create_app(
    root: Path = config.ROOT,
    data: Path = config.DATA,
    *,
    max_media_bytes: int = config.MAX_MEDIA_BYTES,
    username: str | None = None,
    password: str | None = None,
    export_root: Path | None = None,
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
    from .export_service import MediaExportService

    media_exports = MediaExportService(
        root,
        data,
        export_root
        if export_root is not None
        else Path(os.environ.get("BADMINTON_EXPORT_DIR", data.parent / "exports")),
    )
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

    def enqueue(kind, video_id, task, details=None, *, with_job=False, claimed=None):
        """Admit and queue one job. ``task(job_id, progress)``, or with
        ``with_job`` ``task(job, progress)`` so it can set the job's message
        and details. ``claimed(job)`` runs after admission, before queuing."""
        job = {
            "id": uuid4().hex,
            "kind": kind,
            "video_id": video_id,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "details": details,
        }
        try:
            store.claim_job(job)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc
        if claimed is not None:
            try:
                claimed(job)
            except BaseException as exc:
                job.update(status="failed", message=str(exc) or type(exc).__name__)
                store.put_job(job)
                raise

        def run():
            def progress(value):
                job.update(progress=round(min(value, 1), 3))
                store.put_job(job)

            try:
                job.update(status="running", message="Processing")
                store.put_job(job)
                summary = task(job if with_job else job["id"], progress)
                job.update(
                    status="completed", progress=1, message="Completed", summary=summary
                )
            except JobCancelled as exc:
                job.update(status="interrupted", message=str(exc))
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

    @app.get(
        "/api/videos/{video_id}/match-analysis",
        response_model=MatchAnalysis,
        responses={404: {"description": "Video unknown or results not built yet"}},
    )
    def match_analysis(video_id: str):
        """The stored per-match results document; read-only, never rebuilt here."""
        store.video(video_id)
        document = read_match_analysis(data, video_id)
        if document is None:
            raise HTTPException(404, "Match analysis has not been built yet")
        return document

    # Matches: upload plus names, one job, name confirmation (docs/MATCHES_API.md)

    def match_job(video_id, ingest=None, record=None):
        """Admit one analysis job running matches.run_match for this video."""

        def claimed(job):
            with match_flow.lock():
                current = record or match_flow.read_record(data, video_id)
                current["job_id"] = job["id"]
                current["jobs"] = [*current.get("jobs", []), job["id"]]
                match_flow.write_record(data, current)

        return enqueue(
            "analysis",
            video_id,
            lambda job, progress: match_flow.run_match(
                store, root, video_id, job, progress, ingest=ingest
            ),
            {"match": True},
            with_job=True,
            claimed=claimed,
        )

    def match_record(match_id):
        record = match_flow.read_record(data, match_id)
        if record is None:
            raise HTTPException(404, "Unknown match")
        return record

    def require_results(match_id):
        state = match_flow.status(store, match_id).state
        if state not in ("needs_names", "ready"):
            raise HTTPException(409, f"The match is {state}, not finished")

    @app.post(
        "/api/matches",
        status_code=202,
        response_model=match_flow.MatchCreated,
        responses={
            409: {"description": "Another job is running, or format mismatch"},
            413: {"description": "Video too large"},
            422: {"description": "Invalid video or names"},
        },
    )
    def create_match(
        file: UploadFile = File(...),
        mode: Literal["singles", "doubles"] = Form(...),
        team1: list[str] = Form(...),
        team2: list[str] = Form(...),
    ):
        """Upload a match with its players' names and start the one job.

        Names: singles one per team, doubles two per team (partners). The
        same video uploaded again reuses the stored video and its finished
        processing stages.
        """
        from .file_cache import file_digest
        from .media_import import MediaTooLargeError, save_upload

        try:
            entered = match_flow.entered_names(mode, team1, team2)
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
        keep = False
        try:
            video_id = file_digest(path)[:16]
            try:
                existing = store.video(video_id)
            except KeyError:
                existing = None
            if existing and existing["mode"] != mode:
                raise HTTPException(
                    409, f"This video is already stored as a {existing['mode']} match"
                )
            reuse = False
            if existing:
                try:
                    resolve_source(existing, root)
                    reuse = True
                except (ValueError, FileNotFoundError):
                    pass
            name = (
                existing.get("name")
                if reuse
                else (file.filename or "Uploaded match")
                .replace("\\", "/")
                .rsplit("/", 1)[-1][:200]
            )
            previous = match_flow.read_record(data, video_id) or {}
            record = match_flow.new_record(video_id, mode, entered, name)
            record["jobs"] = previous.get("jobs", [])

            def ingest(progress):
                register_media(
                    path, mode, progress, {"name": name, "source_type": "upload"}
                )

            job = match_job(video_id, None if reuse else ingest, record)
            keep = not reuse
        finally:
            if not keep:
                path.unlink(missing_ok=True)
        return {
            "match_id": video_id,
            "video_id": video_id,
            "job_id": job["id"],
            "reused_video": reuse,
        }

    @app.get("/api/matches", response_model=list[match_flow.MatchSummary])
    def list_matches():
        return match_flow.matches(store)

    @app.get(
        "/api/matches/{match_id}",
        response_model=match_flow.MatchStatus,
        responses={404: {"description": "Unknown match"}},
    )
    def match_status(match_id: str):
        """State, one overall progress value 0..1 and a stage label."""
        match_record(match_id)
        return match_flow.status(store, match_id)

    @app.post(
        "/api/matches/{match_id}/pause",
        status_code=202,
        response_model=match_flow.MatchStatus,
        responses={409: {"description": "The match is not processing"}},
    )
    def pause_match(match_id: str):
        """Ask the running job to stop; finished stages are kept for resuming."""
        record = match_record(match_id)
        try:
            store.request_cancel(record.get("job_id") or "")
        except (ConflictError, KeyError) as exc:
            raise HTTPException(409, "The match is not processing") from exc
        return match_flow.status(store, match_id)

    @app.post(
        "/api/matches/{match_id}/resume",
        status_code=202,
        response_model=match_flow.MatchCreated,
        responses={409: {"description": "Already processing or video missing"}},
    )
    def resume_match(match_id: str):
        """Run the match job again, reusing every finished stage."""
        match_record(match_id)
        if match_flow.status(store, match_id).state in ("queued", "running"):
            raise HTTPException(409, "The match is already processing")
        try:
            source(store.video(match_id))
        except KeyError as exc:
            raise HTTPException(
                409, "The video was never stored; upload it again"
            ) from exc
        job = match_job(match_id)
        return {
            "match_id": match_id,
            "video_id": match_id,
            "job_id": job["id"],
            "reused_video": True,
        }

    def thumbnail_url(match_id):
        return lambda person: f"/api/matches/{match_id}/players/{person}/thumbnail"

    @app.get(
        "/api/matches/{match_id}/players",
        response_model=match_flow.MatchPlayers,
        responses={409: {"description": "No results yet"}},
    )
    def match_players(match_id: str):
        """Each person found, with team, the guessed or confirmed name and a
        picture."""
        match_record(match_id)
        try:
            return match_flow.players(store, match_id, thumbnail_url(match_id))
        except match_flow.NotReady as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.put(
        "/api/matches/{match_id}/players",
        response_model=match_flow.MatchPlayers,
        responses={
            409: {"description": "No results yet"},
            422: {"description": "Names break the entered teams"},
        },
    )
    def confirm_match_players(match_id: str, body: match_flow.NameConfirmation):
        """Confirm which entered name belongs to which person (swaps allowed;
        doubles partners stay on one team). Rebuilds the document."""
        match_record(match_id)
        require_results(match_id)
        try:
            match_flow.confirm_names(store, match_id, body.names)
        except match_flow.NotReady as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return match_flow.players(store, match_id, thumbnail_url(match_id))

    @app.get(
        "/api/matches/{match_id}/players/{person_id}/thumbnail",
        response_class=FileResponse,
        responses={404: {"description": "No picture of this person"}},
    )
    def match_player_thumbnail(match_id: str, person_id: str):
        match_record(match_id)
        document = read_match_analysis(data, match_id)
        person = next(
            (p for p in (document.players if document else []) if p.id == person_id),
            None,
        )
        path = match_flow.thumbnail_file(
            data, match_id, person.thumbnail if person else None
        )
        if path is None:
            raise HTTPException(404, "No picture of this person")
        return FileResponse(path)

    def swap_response(match_id, rally_id, persons):
        match_record(match_id)
        require_results(match_id)
        try:
            applied, rally, document = match_flow.swap(
                store, match_id, rally_id, persons
            )
        except match_flow.NotReady as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        rebuilt = next(
            (
                r
                for r in document.rallies
                if (r.start_frame, r.end_frame) == (rally.start_frame, rally.end_frame)
            ),
            rally,
        )
        return {"applied": applied, "rally": rebuilt, "overrides": document.overrides}

    @app.post(
        "/api/matches/{match_id}/rallies/{rally_id}/swap",
        response_model=match_flow.SwapResult,
        responses={404: {"description": "Unknown match or rally"}},
    )
    def swap_rally_players(match_id: str, rally_id: str, body: match_flow.SwapRequest):
        """Swap two persons for one rally (usually partners). The same swap
        again undoes it. Stored as an override; the document is rebuilt."""
        return swap_response(match_id, rally_id, body.persons)

    @app.delete(
        "/api/matches/{match_id}/rallies/{rally_id}/swap",
        response_model=match_flow.SwapResult,
        responses={404: {"description": "Unknown match or rally"}},
    )
    def undo_rally_swaps(match_id: str, rally_id: str):
        """Remove every swap made on this rally."""
        return swap_response(match_id, rally_id, None)

    @app.get(
        "/api/matches/{match_id}/analysis",
        response_model=MatchAnalysis,
        responses={404: {"description": "Unknown match or results not built yet"}},
    )
    def match_document(match_id: str):
        """The MatchAnalysis document (same as /api/videos/{id}/match-analysis)."""
        match_record(match_id)
        document = read_match_analysis(data, match_id)
        if document is None:
            raise HTTPException(404, "Match analysis has not been built yet")
        return document

    @app.get("/api/videos/{video_id}/timestamps")
    def timestamps(video_id: str):
        store.video(video_id)
        return FileResponse(
            data / video_id / "timestamps.json", media_type="application/json"
        )

    @app.get("/api/videos/{video_id}/media")
    def media(video_id: str):
        return FileResponse(source(store.video(video_id)))

    @app.get("/api/videos/{video_id}/playback")
    def playback_status(video_id: str):
        from .playback import cached_playback

        v = store.video(video_id)
        source(v)
        cached = cached_playback(v, root, data)
        return {
            "status": "ready" if cached else "missing",
            "url": f"/api/videos/{video_id}/playback/media" if cached else None,
        }

    @app.post("/api/videos/{video_id}/playback", status_code=202)
    def playback_prepare(video_id: str):
        from .playback import prepare_playback

        v = store.video(video_id)
        source(v)
        return enqueue(
            "playback",
            video_id,
            lambda job_id, progress: prepare_playback(v, root, data, progress),
        )

    @app.get("/api/videos/{video_id}/playback/media")
    def playback_media(video_id: str):
        from .playback import cached_playback

        v = store.video(video_id)
        source(v)
        cached = cached_playback(v, root, data)
        if cached is None:
            raise HTTPException(404, "Prepare browser playback for this video first")
        return FileResponse(cached[0], media_type="video/mp4")

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
        try:
            # Exhaust the single-frame range: its image is provisional until
            # normal media close and the reader's final source validation.
            frames = list(iter_frames(v, root, times, index, index + 1))
        except (SourceChangedError, OrientationError) as exc:
            raise HTTPException(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        img = frames[0][2].to_image()
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
            "terminal_start_frame",
            "terminal_end_frame",
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

    @app.post("/api/videos/{video_id}/media-exports", status_code=202)
    def start_media_export(video_id: str, body: MediaExportRequest):
        # Only catalog reads run in the request: decode/audit starts after shared
        # admission, in the existing single worker, with the explicit revision.
        store.annotations(video_id, revision=body.revision)
        return enqueue(
            "media-export",
            video_id,
            lambda job_id, progress: media_exports.render(
                job_id, video_id, body.revision, body.mode, progress
            ),
            body.model_dump(),
        )

    def media_export_job(video_id, job_id):
        store.recover_jobs()
        job = store.job(job_id)
        if job.get("video_id") != video_id or job.get("kind") != "media-export":
            raise HTTPException(404, "Media export job not found")
        return job

    @app.get("/api/videos/{video_id}/media-exports/{job_id}")
    def media_export_status(video_id: str, job_id: str):
        job = media_export_job(video_id, job_id)
        if job["status"] != "completed":
            return {"job": job, "available": False}
        try:
            return {"job": job, "available": True, **media_exports.describe(job)}
        except (ValueError, OSError, KeyError) as exc:
            raise HTTPException(
                409, "Export artifacts are unavailable or changed. Start a new export."
            ) from exc

    @app.get("/api/videos/{video_id}/media-exports/{job_id}/files/{filename}")
    def media_export_download(video_id: str, job_id: str, filename: str):
        job = media_export_job(video_id, job_id)
        if job["status"] != "completed":
            raise HTTPException(409, "Only completed media exports can be downloaded")
        try:
            download = media_exports.open_download(job, filename)
        except LookupError as exc:
            raise HTTPException(404, "Export file not found") from exc
        except (ValueError, OSError) as exc:
            raise HTTPException(
                409, "Export artifacts are unavailable or changed. Start a new export."
            ) from exc
        return _ExportDownloadResponse(download)

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
                    player_model=body.player_model,
                    auto_calibrate=body.auto_calibrate,
                )
            return track_shuttle(
                v,
                root,
                data,
                body.start_frame,
                body.end_frame,
                progress,
                output,
                snapshot,
            )

        return enqueue(body.stage, video_id, task)

    @app.post("/api/videos/{video_id}/analysis", status_code=202)
    def analyze_match(video_id: str, body: AnalysisRequest):
        from .pipeline import digest, plan_windows, process_match, processing_recipe

        video = store.video(video_id)
        source(video)
        times = timestamps_for(data, video_id)
        snapshot = store.annotations(video_id)
        settings = body.model_dump()
        try:
            plan_windows(video, times)
            key = digest(processing_recipe(video, times, snapshot, settings))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return enqueue(
            "analysis",
            video_id,
            lambda job_id, progress: process_match(
                video,
                root,
                store,
                snapshot,
                job_id,
                progress,
                settings,
                expected_key=key,
            ),
            {"analysis_key": key, "settings": settings},
        )

    @app.get("/api/videos/{video_id}/analysis/{job_id}")
    def analysis_progress(video_id: str, job_id: str):
        from .pipeline import read_plan
        from .rallies import context_signature

        job = store.job(job_id)
        if job.get("video_id") != video_id or job.get("kind") != "analysis":
            raise HTTPException(404)
        key = (job.get("details") or {}).get("analysis_key")
        if key is None:
            return {
                "job": job,
                "parts": [],
                "state": job["status"],
                "requires_processing_rerun": False,
            }
        try:
            plan = read_plan(store, video_id, key)
        except FileNotFoundError:
            return {
                "job": job,
                "parts": [],
                "state": job["status"],
                "requires_processing_rerun": False,
            }
        video = store.video(video_id)
        plan["requires_processing_rerun"] = plan["recipe"][
            "context_signature"
        ] != context_signature(store.annotations(video_id), 0, video["frame_count"])
        return {**plan, "job": job}

    @app.post("/api/videos/{video_id}/analysis/{job_id}/pause", status_code=202)
    def pause_analysis(video_id: str, job_id: str):
        if store.job(job_id).get("video_id") != video_id:
            raise HTTPException(404)
        try:
            return store.request_cancel(job_id)
        except ConflictError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/videos/{video_id}/segments", status_code=202)
    def segments(video_id: str):
        from .segments import scan_video

        video = store.video(video_id)
        source(video)

        def task(job_id, progress):
            return scan_video(
                video, root, data, progress, data / video_id / "runs" / f"{job_id}.json"
            )

        return enqueue("segments", video_id, task)

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
        from .contacts import (
            METHOD,
            proposal_recipe,
            propose_contacts,
            validate_contact_inputs,
        )
        from .scene_review import camera_review_signature, reviewed_run

        v = store.video(video_id)
        source(v)
        shuttle_run = load_run(video_id, body.shuttle_run_id, "shuttle")
        player_run = (
            load_run(video_id, body.player_run_id, "players")
            if body.player_run_id
            else None
        )
        if body.include_audio and player_run is None:
            raise HTTPException(422, "Audio support needs a player/pose run")
        try:
            times = timestamps_for(data, video_id)
            input_provenance = validate_contact_inputs(
                v, shuttle_run, player_run, times
            )
        except (OSError, TypeError, ValueError) as exc:
            raise HTTPException(
                422, f"Contact inputs do not match the native source: {exc}"
            ) from exc
        snapshot = store.annotations(video_id)
        shuttle_run = reviewed_run(shuttle_run, snapshot)
        player_run = reviewed_run(player_run, snapshot) if player_run else None
        if any(
            run and run["requires_tracking_rerun"] for run in (shuttle_run, player_run)
        ):
            raise HTTPException(
                422,
                "Camera corrections or court calibration changed these inputs; rerun tracking before suggesting contacts",
            )

        def task(job_id, progress):
            candidates = propose_contacts(shuttle_run, player_run, v, times)
            audio = None
            if body.include_audio:
                from .audio import extract_audio_cues
                from .audio_contacts import add_audio_support

                start, end = shuttle_run["start_frame"], shuttle_run["end_frame"]
                validate_range(v, times, start, end)
                end_s = times[end] if end < len(times) else v["duration_s"]
                audio = extract_audio_cues(v, root, times[start], end_s)
                candidates = add_audio_support(
                    candidates, shuttle_run, player_run, v, audio
                )
            result = {
                "schema_version": 1,
                "stage": "contacts",
                "video_id": video_id,
                "video_sha256": v["sha256"],
                **input_provenance,
                "shuttle_run_id": body.shuttle_run_id,
                "player_run_id": body.player_run_id,
                "start_frame": shuttle_run["start_frame"],
                "end_frame": shuttle_run["end_frame"],
                "method": METHOD,
                "recipe": proposal_recipe(),
                "interval_bounds": "inclusive",
                "candidates": candidates,
                "scene_annotation_revision": snapshot.revision,
                "scene_ranges": [r.model_dump() for r in snapshot.scene_ranges],
                "camera_review_signature": camera_review_signature(
                    snapshot, shuttle_run["start_frame"], shuttle_run["end_frame"]
                ),
            }
            if player_run and "calibration_signature" in player_run:
                result.update(
                    court_context=court_run_context(player_run),
                    calibration_signature=player_run["calibration_signature"],
                )
            if audio is not None:
                from .audio_contacts import METHOD as AUDIO_METHOD

                result.update(audio=audio, audio_support_method=AUDIO_METHOD)
            write_json(data / video_id / "runs" / f"{job_id}.json", result)
            return (
                {k: v for k, v in result.items() if k not in ("candidates", "audio")}
                | {"candidate_count": len(candidates)}
                | ({"audio_status": audio["status"]} if audio is not None else {})
            )

        return enqueue(
            "contacts",
            video_id,
            task,
        )

    @app.post("/api/videos/{video_id}/rallies", status_code=202)
    def rallies(video_id: str, body: RalliesRequest):
        from .rallies import generate_rallies, validate_rally_inputs

        video = store.video(video_id)
        source(video)
        players = load_run(video_id, body.player_run_id, "players")
        shuttle = load_run(video_id, body.shuttle_run_id, "shuttle")
        snapshot = store.annotations(video_id)
        times = timestamps_for(data, video_id)
        # Validate inputs before admission; inference remains in the shared worker.
        try:
            validate_rally_inputs(video, players, shuttle, snapshot, times)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        return enqueue(
            "rallies",
            video_id,
            lambda job_id, progress: generate_rallies(
                video,
                players,
                shuttle,
                snapshot,
                body.player_run_id,
                body.shuttle_run_id,
                data / video_id / "runs" / f"{job_id}.json",
                times,
            ),
        )

    @app.get("/api/videos/{video_id}/runs/{job_id}")
    def run(video_id: str, job_id: str):
        video = store.video(video_id)
        if not any(
            j["id"] == job_id
            and j["status"] == "completed"
            and j["kind"]
            in (
                "players",
                "shuttle",
                "contacts",
                "recognition",
                "segments",
                "rallies",
                "identities",
            )
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
            from .scene_review import reviewed_run

            result = reviewed_run(result, doc)
            result = apply_assignments(result, doc.track_assignments, job_id)
        elif result.get("stage") == "shuttle":
            from .scene_review import reviewed_run

            result = reviewed_run(result, doc)
        elif result.get("stage") == "rallies":
            from .rallies import reviewed_rallies

            result = reviewed_rallies(result, doc)
        elif result.get("stage") == "contacts":
            from .scene_review import reviewed_contacts

            result = reviewed_contacts(result, doc)
            for candidate in result["candidates"]:
                candidate["player_id"] = resolve_contact_player(
                    candidate["frame"],
                    candidate.get("track_id"),
                    doc.track_assignments,
                    result.get("player_run_id"),
                )
        elif result.get("stage") == "recognition":
            from .scene_review import camera_context_changed

            result["requires_context_rerun"] = court_context_changed(
                doc, result
            ) or camera_context_changed(doc, result.get("court_context"))
            for candidate in result["candidates"]:
                if hint := candidate.get("hitter_hint"):
                    hint["player_id"] = resolve_contact_player(
                        candidate["frame"],
                        hint.get("track_id"),
                        doc.track_assignments,
                        result.get("player_run_id"),
                    )
        elif result.get("stage") == "identities":
            from .rallies import context_signature

            result["requires_context_rerun"] = result.get(
                "source_context_signature"
            ) != context_signature(doc, 0, video["frame_count"])
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
        from .scene_review import reviewed_run

        players, shuttle = (
            reviewed_run(players, snapshot),
            reviewed_run(shuttle, snapshot),
        )
        if players["requires_tracking_rerun"] or shuttle["requires_tracking_rerun"]:
            raise HTTPException(
                422,
                "Camera corrections or court calibration changed these inputs; rerun tracking before classifying",
            )
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
        from .rally_evaluation import evaluate_rallies
        from .recognition_evaluation import evaluate_recognition

        if not any(
            (
                body.contacts_run_id,
                body.shuttle_run_id,
                body.recognition_run_id,
                body.rallies_run_id,
            )
        ):
            raise HTTPException(
                422, "Choose a contact, shuttle, recognition, or rally run to evaluate"
            )
        v = store.video(video_id)
        source(v)
        doc = store.annotations(video_id).model_dump()
        result = {
            "video_id": video_id,
            "video_sha256": v["sha256"],
            "annotation_revision": doc["revision"],
        }
        try:
            native_times = None
            if body.contacts_run_id or body.recognition_run_id or body.shuttle_run_id:
                try:
                    native_times = timestamps_for(data, video_id)
                except (OSError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "Native source timestamp map is unavailable or malformed"
                    ) from exc
            if body.rallies_run_id:
                artifact = load_run(video_id, body.rallies_run_id, "rallies") | {
                    "run_id": body.rallies_run_id
                }
                result["rallies"] = evaluate_rallies(
                    v, doc, artifact, timestamps_for(data, video_id), body.tolerance_s
                )
            if body.recognition_run_id:
                artifact = load_run(
                    video_id, body.recognition_run_id, "recognition"
                ) | {"run_id": body.recognition_run_id}
                result["recognition"] = evaluate_recognition(
                    v,
                    doc,
                    artifact,
                    body.tolerance_s,
                    native_timestamps=native_times,
                )
            if body.contacts_run_id:
                artifact = load_run(video_id, body.contacts_run_id, "contacts")
                result["contacts"] = evaluate_contacts(
                    v,
                    doc,
                    artifact,
                    body.tolerance_s,
                    native_timestamps=native_times,
                )
                result["contacts"]["run_id"] = body.contacts_run_id
            if body.shuttle_run_id:
                artifact = load_run(video_id, body.shuttle_run_id, "shuttle")
                result["shuttle"] = evaluate_shuttle(
                    v,
                    doc,
                    artifact,
                    body.tolerance_diagonal,
                    native_timestamps=native_times,
                )
                result["shuttle"]["run_id"] = body.shuttle_run_id
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return result

    app.mount(
        "/",
        _ViewerStaticFiles(directory=Path(__file__).parent / "static", html=True),
        name="viewer",
    )
    return app
