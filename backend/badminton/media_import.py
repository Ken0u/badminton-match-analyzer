"""Bounded local video imports and single public YouTube video downloads."""

import math
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import av

MAX_MEDIA_BYTES = 2 * 1024**3
SUPPORTED_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv", ".avi", ".webm"})
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}\Z")


class MediaImportError(ValueError):
    """A media source cannot be imported as an ordinary decodable video."""


class MediaTooLargeError(MediaImportError):
    """A media source exceeds the configured byte limit."""


def _limit(max_bytes):
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("Media byte limit must be a positive integer")


def _validate_video(path, suffix):
    """Check real container/decoded video before exposing a completed import.

    Local inputs cannot activate network protocols through demuxer probing.
    Only ordinary supported video containers proceed to the full timestamp
    inspection performed by the ingester.
    """
    try:
        with av.open(
            str(path), options={"protocol_whitelist": "file,pipe"}
        ) as container:
            formats = set(container.format.name.split(","))
            if formats & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}:
                extension = ".mov" if suffix == ".mov" else ".mp4"
            elif formats & {"matroska", "webm"}:
                extension = ".webm" if suffix == ".webm" else ".mkv"
            elif "avi" in formats:
                extension = ".avi"
            else:
                raise MediaImportError("Choose an MP4, MOV, MKV, AVI, or WebM video")
            if not container.streams.video:
                raise MediaImportError("The file contains no video stream")
            frame = next(container.decode(container.streams.video[0]), None)
            if frame is None or frame.width <= 0 or frame.height <= 0:
                raise MediaImportError("No video frames could be decoded")
            return extension
    except MediaImportError:
        raise
    except (av.FFmpegError, OSError, ValueError) as exc:
        raise MediaImportError("The file is not a readable video") from exc


def save_upload(
    stream, filename, media_root, max_bytes=MAX_MEDIA_BYTES, readchunk=1024**2
):
    """Save a bounded binary stream to a UUID filename and verify actual video.

    ``stream`` is synchronous and may be ``UploadFile.file``. The caller retains
    ownership of the stream and performs full timestamp inspection afterwards.
    Filename path components are never used for storage.
    """
    _limit(max_bytes)
    if type(readchunk) is not int or not 0 < readchunk <= 16 * 1024**2:
        raise ValueError("Upload read chunk must be between one byte and 16 MiB")
    suffix = Path(str(filename or "").replace("\\", "/")).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise MediaImportError("Choose an MP4, MOV, MKV, AVI, or WebM video")
    folder = Path(media_root).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    temporary = folder / f"{token}.part"
    final = None
    try:
        size = 0
        with temporary.open("xb") as output:
            while True:
                # Read one extra byte to distinguish an exact-size upload from
                # an oversized one without ever requesting an unbounded read.
                chunk = stream.read(min(readchunk, max_bytes - size + 1))
                if not isinstance(chunk, bytes | bytearray | memoryview):
                    raise MediaImportError("Upload must be a binary stream")
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise MediaTooLargeError("Video exceeds the configured size limit")
                output.write(chunk)
        if not size:
            raise MediaImportError("The uploaded file is empty")
        extension = _validate_video(temporary, suffix)
        final = folder / f"{token}{extension}"
        temporary.replace(final)
        return final
    except BaseException:
        temporary.unlink(missing_ok=True)
        if final is not None:
            final.unlink(missing_ok=True)
        raise


def canonical_youtube_url(url):
    """Accept only HTTPS single-video YouTube URLs, returning a watch URL.

    A strict publisher host allowlist and fixed output URL prevent user-provided
    URLs from selecting arbitrary downloader sites or network destinations.
    Playlist/radio parameters are rejected rather than silently discarded.
    """
    message = "Enter an HTTPS YouTube video URL without a playlist"
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url):
        raise MediaImportError(message)
    try:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.hostname
            not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port is not None
            or "\\" in url
        ):
            raise MediaImportError(message)
        query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=30)
    except ValueError as exc:
        raise MediaImportError(message) from exc
    if any(
        key.lower() in {"list", "playlist", "index", "start_radio"} for key in query
    ):
        raise MediaImportError(message)
    if parsed.hostname == "youtu.be":
        match = re.fullmatch(r"/([A-Za-z0-9_-]{11})/?", parsed.path)
        identifier = match[1] if match else None
        if "v" in query:
            raise MediaImportError(message)
    elif parsed.path == "/watch":
        values = query.get("v", [])
        identifier = values[0] if len(values) == 1 else None
    else:
        match = re.fullmatch(r"/(?:shorts|live)/([A-Za-z0-9_-]{11})/?", parsed.path)
        identifier = match[1] if match else None
        if "v" in query:
            raise MediaImportError(message)
    if not identifier or not _VIDEO_ID.fullmatch(identifier):
        raise MediaImportError(message)
    return f"https://www.youtube.com/watch?v={identifier}"


class _QuietLogger:
    # yt-dlp diagnostics may contain signed media URLs. Expose only our stable,
    # actionable error text through the API and let the caller report progress.
    def debug(self, message):
        pass

    def warning(self, message):
        pass

    def error(self, message):
        pass


def _youtube_info(info, identifier, max_bytes):
    if (
        not isinstance(info, dict)
        or info.get("_type", "video") != "video"
        or "entries" in info
    ):
        raise MediaImportError("Only one YouTube video can be imported at a time")
    if info.get("id") != identifier:
        raise MediaImportError(
            "The downloaded video does not match the requested YouTube video"
        )
    if info.get("is_live") or info.get("live_status") in {
        "is_live",
        "is_upcoming",
        "post_live",
    }:
        raise MediaImportError(
            "Choose a completed video rather than a live or scheduled stream"
        )
    if info.get("has_drm") or info.get("availability") in {
        "private",
        "premium_only",
        "subscriber_only",
        "needs_auth",
    }:
        raise MediaImportError(
            "Choose a publicly accessible video that does not require signing in"
        )
    for field in ("filesize", "filesize_approx"):
        if isinstance(info.get(field), int | float) and info[field] > max_bytes:
            raise MediaTooLargeError("Video exceeds the configured size limit")


def download_youtube(url, media_root, max_bytes=MAX_MEDIA_BYTES, progress=None):
    """Download one unauthenticated video and return its path and provenance.

    Single-file MP4 is preferred, followed by WebM and video-only variants. This
    works without an external ffmpeg binary; missing audio is acceptable for CV.
    No browser cookies, credentials, DRM workarounds, or alternate sites are used.
    ``progress`` receives a positional floating-point fraction in [0, 1].
    """
    canonical = canonical_youtube_url(url)
    _limit(max_bytes)
    try:
        from yt_dlp import YoutubeDL
    except ImportError as exc:
        raise MediaImportError("Install the YouTube import dependencies first") from exc
    folder = Path(media_root).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    work = folder / f".youtube-{token}"
    work.mkdir()
    identifier = canonical.rsplit("=", 1)[1]
    final = None
    last_progress = -1

    def report(value):
        nonlocal last_progress
        value = max(last_progress, min(1.0, max(0.0, float(value))))
        if progress and value - last_progress >= 0.01:
            progress(value)
        last_progress = value

    def check_info(info, *, incomplete=False):
        if not incomplete:
            _youtube_info(info, identifier, max_bytes)
        return None

    def hook(status):
        if status.get("status") not in {"downloading", "finished"}:
            return
        actual = sum(path.stat().st_size for path in work.iterdir() if path.is_file())
        downloaded = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        if actual > max_bytes or downloaded > max_bytes or total > max_bytes:
            raise MediaTooLargeError("Video exceeds the configured size limit")
        if total and math.isfinite(total):
            report(min(0.95, downloaded / total * 0.95))

    options = {
        "outtmpl": str(work / "video.%(ext)s"),
        "format": "best[ext=mp4]/best[ext=webm]/bestvideo[ext=mp4]/bestvideo[ext=webm]",
        "noplaylist": True,
        "max_filesize": max_bytes,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 2,
        "concurrent_fragment_downloads": 1,
        "skip_unavailable_fragments": False,
        "continuedl": False,
        "overwrites": False,
        "cachedir": False,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _QuietLogger(),
        "match_filter": check_info,
        "progress_hooks": [hook],
        "allowed_extractors": ["youtube"],
        "fixup": "never",
        "remote_components": [],
    }
    if node := shutil.which("node"):
        options["js_runtimes"] = {"node": {"path": node}}
    try:
        report(0)
        with YoutubeDL(options) as downloader:
            info = downloader.extract_info(canonical, download=True)
        _youtube_info(info, identifier, max_bytes)
        files = [
            path
            for path in work.iterdir()
            if path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if len(files) != 1 or not files[0].is_file():
            raise MediaImportError("YouTube did not return a downloadable video file")
        downloaded = files[0]
        if downloaded.stat().st_size > max_bytes:
            raise MediaTooLargeError("Video exceeds the configured size limit")
        if not downloaded.stat().st_size:
            raise MediaImportError("The downloaded video is empty")
        extension = _validate_video(downloaded, downloaded.suffix.lower())
        final = folder / f"{token}{extension}"
        downloaded.replace(final)
        provenance = {"source_type": "youtube", "url": canonical, "id": identifier}
        for field in ("title", "channel", "channel_id", "uploader", "upload_date"):
            if isinstance(info.get(field), str):
                provenance[field] = info[field][:500]
        report(1)
        return final, provenance
    except MediaImportError:
        if final is not None:
            final.unlink(missing_ok=True)
        raise
    except Exception:
        if final is not None:
            final.unlink(missing_ok=True)
        raise MediaImportError(
            "YouTube import failed. Check that the video is public and available, "
            "or upload a local copy. The downloader may need an update."
        ) from None
    except BaseException:
        if final is not None:
            final.unlink(missing_ok=True)
        raise
    finally:
        # This directory is a fixed UUID child created by this invocation, never
        # a filename or path supplied by a user or downloader response.
        if work.parent == folder and work.name == f".youtube-{token}":
            shutil.rmtree(work)
