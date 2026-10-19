"""Server-owned, immutable native media exports and verified file handles."""

import hashlib
import json
import os
import re
import shutil
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .rally_export import ExportPlanStore, plan_rally_exports
from .rally_overlay import render_annotated_videos
from .rally_video import render_rally_videos

MODES = frozenset(("plain-rallies", "annotated-rallies", "annotated-full"))
_JOB_ID = re.compile(r"[0-9a-f]{32}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _safe_path(value):
    path = Path(value).absolute()
    if ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("Export paths cannot traverse directories or symlinks")
    return path


def _identity(info):
    return info.st_dev, info.st_ino


@contextmanager
def _directory(path):
    """Open every directory component without following links where supported."""
    _safe_path(path)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        with ExitStack() as stack:
            if os.open in os.supports_dir_fd:
                descriptor = os.open(path.anchor, flags)
                stack.callback(os.close, descriptor)
                for component in path.parts[1:]:
                    descriptor = os.open(component, flags, dir_fd=descriptor)
                    stack.callback(os.close, descriptor)
                if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    raise ValueError("Export storage must be a directory")
                yield descriptor
            else:
                # Windows does not support directory descriptors through os.open.
                # Check ancestry and identity around all pathname-based access.
                before = path.stat(follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    raise ValueError("Export storage must be a directory")
                yield None
                _safe_path(path)
                if _identity(before) != _identity(path.stat(follow_symlinks=False)):
                    raise ValueError("Export directory changed during verification")
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError("Export directory is unsafe or unavailable") from exc


def _open_file(directory, folder, name):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        if os.open in os.supports_dir_fd:
            descriptor = os.open(name, flags, dir_fd=directory)
        else:
            path = _safe_path(folder / name)
            before = path.stat(follow_symlinks=False)
            descriptor = os.open(path, flags)
            try:
                _safe_path(path)
                if _identity(before) != _identity(os.fstat(descriptor)):
                    raise ValueError("Export file changed while opening")
            except BaseException:
                os.close(descriptor)
                raise
        handle = os.fdopen(descriptor, "rb")
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            handle.close()
            raise ValueError("Export artifacts must be regular files")
        return handle
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ValueError("Export artifact is unsafe or unavailable") from exc


def _receipt(handle, name):
    before = os.fstat(handle.fileno())
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
        size += len(chunk)
    after = os.fstat(handle.fileno())
    if (
        _identity(before) != _identity(after)
        or before.st_size != size
        or after.st_size != size
        or before.st_mtime_ns != after.st_mtime_ns
        or before.st_ctime_ns != after.st_ctime_ns
    ):
        raise ValueError("Export artifact changed during verification")
    handle.seek(0)
    return {
        "filename": name,
        "sha256": digest.hexdigest(),
        "size_bytes": size,
        "media_type": "application/json" if name == "manifest.json" else "video/mp4",
    }


class MediaExportService:
    def __init__(self, root, data, exports):
        self.root = _safe_path(root)
        self.data = _safe_path(data)
        self.exports = _safe_path(exports)
        if self.exports.is_relative_to(self.data):
            raise ValueError("Media exports must be outside application data storage")
        if self.exports.exists():
            with _directory(self.exports):
                pass

    def _folder(self, job_id):
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise ValueError("Invalid media export job identifier")
        return self.exports / job_id

    @staticmethod
    def _request(revision, mode):
        if (
            type(revision) is not int
            or revision < 0
            or not isinstance(mode, str)
            or mode not in MODES
        ):
            raise ValueError("Choose an explicit saved revision and export mode")

    @staticmethod
    def _clips(manifest, mode):
        purpose = (
            "reviewed_rally_videos" if mode == "plain-rallies" else "annotated_videos"
        )
        if manifest.get("schema_version") != 1 or manifest.get("purpose") != purpose:
            raise ValueError("Export manifest does not match the requested mode")
        if mode == "plain-rallies":
            clips = [r["clip"] for r in manifest["rallies"] if r["clip"] is not None]
        else:
            scope = "full" if mode == "annotated-full" else "rallies"
            if manifest.get("scope") != scope:
                raise ValueError("Export scope does not match the requested mode")
            clips = manifest["exports"]
            if scope == "full" and len(clips) != 1:
                raise ValueError("Full-video export must contain one video")
            if scope == "rallies" and clips != [
                r["clip"] for r in manifest["rallies"] if r["clip"] is not None
            ]:
                raise ValueError("Rally export receipts do not match their manifest")
        prefix = "full" if mode == "annotated-full" else "rally"
        names = set()
        for clip in clips:
            name = clip["file"]
            if (
                not isinstance(name, str)
                or not re.fullmatch(rf"{prefix}-[0-9]{{6}}\.mp4", name)
                or name in names
                or not isinstance(clip["sha256"], str)
                or not _SHA256.fullmatch(clip["sha256"])
            ):
                raise ValueError("Invalid or duplicate export artifact receipt")
            names.add(name)
        return clips

    def render(self, job_id, video_id, revision, mode, progress):
        """Plan and encode only after the caller has admitted the shared job."""
        self._request(revision, mode)
        folder = self._folder(job_id)
        _safe_path(folder)
        try:
            self.exports.mkdir(parents=True, exist_ok=True)
            with _directory(self.exports):
                pass
        except OSError as exc:
            raise ValueError("Export root must be an available directory") from exc
        if folder.exists():
            raise ValueError("Media export job output already exists; start a new job")
        store = ExportPlanStore(self.data)
        plan = plan_rally_exports(store, video_id, revision, self.root)
        if mode == "plain-rallies":
            manifest = render_rally_videos(store, plan, self.root, folder, progress)
        else:
            manifest = render_annotated_videos(
                store,
                plan,
                self.root,
                folder,
                scope="full" if mode == "annotated-full" else "rallies",
                progress=progress,
            )
        # The native renderer cleans its own failures. Only remove the output
        # after its successful return establishes that this invocation owns it.
        identity = folder.stat(follow_symlinks=False)
        try:
            with _directory(folder) as directory:
                clips = self._clips(manifest, mode)
                native_bytes = (
                    json.dumps(manifest, ensure_ascii=False, allow_nan=False, indent=2)
                    + "\n"
                ).encode("utf-8")
                expected = {"manifest.json": hashlib.sha256(native_bytes).hexdigest()}
                expected.update({clip["file"]: clip["sha256"] for clip in clips})
                files = []
                for name, expected_hash in expected.items():
                    with _open_file(directory, folder, name) as handle:
                        receipt = _receipt(handle, name)
                        if receipt["sha256"] != expected_hash:
                            raise ValueError("Native export changed before completion")
                        files.append(receipt)
            summary = {
                "video_id": video_id,
                "mode": mode,
                "annotation_revision": revision,
                "manifest_sha256": files[0]["sha256"],
                "counts": manifest["counts"],
                "files": files,
            }
            self.describe(
                {
                    "id": job_id,
                    "video_id": video_id,
                    "kind": "media-export",
                    "status": "completed",
                    "details": {"revision": revision, "mode": mode},
                    "summary": summary,
                }
            )
            return summary
        except BaseException:
            if (
                not folder.is_symlink()
                and folder.exists()
                and _identity(folder.stat()) == _identity(identity)
                and not any(p.is_symlink() for p in folder.parents)
            ):
                shutil.rmtree(folder)
            raise

    def _validated(self, job, stack, requested=None):
        if job.get("kind") != "media-export" or job.get("status") != "completed":
            raise ValueError("Only completed media exports have downloadable artifacts")
        folder = self._folder(job["id"])
        details, summary = job["details"], job["summary"]
        revision, mode = details["revision"], details["mode"]
        self._request(revision, mode)
        if (
            summary["video_id"] != job["video_id"]
            or summary["mode"] != mode
            or summary["annotation_revision"] != revision
        ):
            raise ValueError("Export summary does not match the completed job")
        directory = stack.enter_context(_directory(folder))
        handle = stack.enter_context(_open_file(directory, folder, "manifest.json"))
        receipt = _receipt(handle, "manifest.json")
        if receipt["sha256"] != summary["manifest_sha256"]:
            raise ValueError("Export manifest hash differs from its completion receipt")
        manifest_bytes = handle.read()
        if hashlib.sha256(manifest_bytes).hexdigest() != receipt["sha256"]:
            raise ValueError("Export manifest changed during verification")
        manifest = json.loads(manifest_bytes)
        handle.seek(0)
        if (
            manifest["source"]["id"] != job["video_id"]
            or manifest["annotation_revision"] != revision
            or manifest["annotations"]["revision"] != revision
            or manifest["counts"] != summary["counts"]
        ):
            raise ValueError("Export manifest does not match the completed job")
        clips = self._clips(manifest, mode)
        expected_names = {"manifest.json", *[c["file"] for c in clips]}
        actual_names = (
            set(os.listdir(directory))
            if directory is not None and os.listdir in os.supports_fd
            else {p.name for p in folder.iterdir()}
        )
        if expected_names - actual_names:
            raise FileNotFoundError("Completed export artifacts are missing")
        if actual_names - expected_names:
            raise ValueError("Export directory has unexpected artifacts")
        files = [receipt]
        handles = {"manifest.json": handle} if requested == "manifest.json" else {}
        for clip in clips:
            name = clip["file"]
            with _open_file(directory, folder, name) as handle:
                receipt = _receipt(handle, name)
                if receipt["sha256"] != clip["sha256"]:
                    raise ValueError(
                        "Export video hash differs from its native receipt"
                    )
                files.append(receipt)
                if name == requested:
                    handles[name] = stack.enter_context(
                        os.fdopen(os.dup(handle.fileno()), "rb")
                    )
        if files != summary["files"]:
            raise ValueError("Export files differ from their completion receipts")
        return manifest, files, handles

    def describe(self, job):
        if job.get("kind") != "media-export":
            raise ValueError("Job is not a media export")
        if job.get("status") != "completed":
            return {"job": job, "available": False, "files": [], "manifest": None}
        try:
            with ExitStack() as stack:
                manifest, files, _ = self._validated(job, stack)
                return {
                    "job": job,
                    "available": True,
                    "files": files,
                    "manifest": manifest,
                }
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid media export completion receipt") from exc

    def open_download(self, job, filename):
        """Return the verified descriptor itself, never a path to reopen later."""
        try:
            with ExitStack() as stack:
                _, files, handles = self._validated(job, stack, filename)
                if not isinstance(filename, str) or filename not in handles:
                    raise LookupError("Filename is not a completed export artifact")
                receipt = next(f for f in files if f["filename"] == filename)
                # Duplicate the already validated descriptor before closing the
                # validation stack; no pathname is resolved again for streaming.
                handle = os.fdopen(os.dup(handles[filename].fileno()), "rb")
                handle.seek(0)
                return {
                    "file": handle,
                    "filename": filename,
                    "media_type": receipt["media_type"],
                    "size_bytes": receipt["size_bytes"],
                }
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid media export completion receipt") from exc
