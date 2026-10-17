"""Bounded source import tests; YouTube uses a stub and never external network."""

import io
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import av
import numpy as np
import pytest
from badminton.media_import import (
    MediaImportError,
    MediaTooLargeError,
    canonical_youtube_url,
    download_youtube,
    save_upload,
)


@pytest.fixture
def video_bytes(tmp_path):
    path = tmp_path / "tiny.mp4"
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = 32, 32
        stream.pix_fmt = "yuv420p"
        for index in range(3):
            frame = av.VideoFrame.from_ndarray(
                np.full((32, 32, 3), index * 30, np.uint8), format="rgb24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path.read_bytes()


def test_upload_uses_safe_uuid_and_actual_video_container(tmp_path, video_bytes):
    folder = tmp_path / ".media"
    path = save_upload(
        io.BytesIO(video_bytes),
        "../../user controlled\\match.avi",
        folder,
        max_bytes=len(video_bytes),
    )
    assert path.parent == folder.resolve()
    assert re.fullmatch(r"[a-f0-9]{32}\.mp4", path.name)
    assert path.read_bytes() == video_bytes
    assert list(folder.iterdir()) == [path]


def test_upload_reads_in_bounded_chunks_and_rejects_one_extra_byte(
    tmp_path, video_bytes
):
    class BoundedStream(io.BytesIO):
        def read(self, amount=-1):
            assert 0 < amount <= 13
            return super().read(amount)

    folder = tmp_path / ".media"
    with pytest.raises(MediaTooLargeError):
        save_upload(
            BoundedStream(video_bytes),
            "match.mp4",
            folder,
            max_bytes=len(video_bytes) - 1,
            readchunk=13,
        )
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize(
    "content,name",
    [
        (b"", "empty.mp4"),
        (b"not video", "fake.mp4"),
        (b"#EXTM3U\nhttps://127.0.0.1/no", "fake.mp4"),
        (b"hello", "file.txt"),
    ],
)
def test_upload_rejects_empty_nonvideo_and_unsupported_files(tmp_path, content, name):
    folder = tmp_path / ".media"
    with pytest.raises(MediaImportError):
        save_upload(io.BytesIO(content), name, folder)
    assert not folder.exists() or list(folder.iterdir()) == []


def test_upload_cleans_partial_file_after_stream_error(tmp_path):
    class BrokenStream:
        calls = 0

        def read(self, amount):
            self.calls += 1
            if self.calls > 1:
                raise OSError("disconnected")
            return b"partial"

    folder = tmp_path / ".media"
    with pytest.raises(OSError, match="disconnected"):
        save_upload(BrokenStream(), "match.mp4", folder)
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("value", [0, -1, True, 2.5])
def test_upload_rejects_invalid_limits_before_creating_files(tmp_path, value):
    folder = tmp_path / ".media"
    with pytest.raises(ValueError):
        save_upload(io.BytesIO(b"video"), "file.mp4", folder, max_bytes=value)
    assert not folder.exists()


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abcdefghI_1",
        "https://youtube.com/watch?v=abcdefghI_1&t=2",
        "https://m.youtube.com/watch?v=abcdefghI_1#t=2",
        "https://youtu.be/abcdefghI_1?si=tracking",
        "https://www.youtube.com/shorts/abcdefghI_1",
        "https://www.youtube.com/live/abcdefghI_1/",
    ],
)
def test_youtube_single_video_urls_are_canonicalized(url):
    assert canonical_youtube_url(url) == "https://www.youtube.com/watch?v=abcdefghI_1"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.youtube.com/watch?v=abcdefghI_1",
        "https://youtube.com:443/watch?v=abcdefghI_1",
        "https://user@youtube.com/watch?v=abcdefghI_1",
        "https://youtube.com.evil.com/watch?v=abcdefghI_1",
        "https://127.0.0.1/watch?v=abcdefghI_1",
        "https://localhost/watch?v=abcdefghI_1",
        "https://youtube.com@127.0.0.1/watch?v=abcdefghI_1",
        "https://youtu.be/abcdefghI_1/extra",
        "https://www.youtube.com/watch?v=abcdefghI_1&list=PLAYLIST",
        "https://youtu.be/abcdefghI_1?list=PLAYLIST",
        "https://www.youtube.com/playlist?list=PLAYLIST",
        "https://www.youtube.com/watch?v=short",
        "https://www.youtube.com/watch?v=abcdefghI_1&v=abcdefghI_2",
        "https://www.youtube.com/watch?v=abcdefghI_1&start_radio=1",
        "https://www.youtube.com/watch?v=abcdefghI_1\n",
        "file:///video.mp4",
        "ytsearch:badminton",
        "https://www.youtube.com\\@localhost/watch?v=abcdefghI_1",
        "https://www.youtube.com/redirect?q=https://127.0.0.1",
    ],
)
def test_youtube_rejects_arbitrary_urls_playlists_credentials_and_ports(url):
    with pytest.raises(MediaImportError):
        canonical_youtube_url(url)


@pytest.fixture
def fake_youtube(monkeypatch, video_bytes):
    state = SimpleNamespace(
        options=None, calls=[], behavior="success", body=video_bytes
    )

    class FakeYoutubeDL:
        def __init__(self, options):
            state.options = options

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download):
            state.calls.append((url, download))
            info = {
                "id": "abcdefghI_1",
                "title": "Badminton sample",
                "channel": "Example",
                "availability": "public",
            }
            if state.behavior == "wrong_id":
                info["id"] = "abcdefghI_2"
            if state.behavior == "live":
                info["is_live"] = True
            if state.behavior == "private":
                info["availability"] = "private"
            if state.behavior == "drm":
                info["has_drm"] = True
            if state.behavior == "playlist":
                info |= {"_type": "playlist", "entries": []}
            state.options["match_filter"](info, incomplete=False)
            path = Path(state.options["outtmpl"].replace("%(ext)s", "mp4"))
            if state.behavior == "partial_error":
                path.with_suffix(".part").write_bytes(b"partial")
                raise RuntimeError(
                    "secret signed https://example.com/media?token=secret"
                )
            if state.behavior != "missing_file":
                path.write_bytes(state.body)
            if state.behavior != "no_hook":
                if state.behavior == "incremental":
                    for index in range(1, 201):
                        state.options["progress_hooks"][0](
                            {
                                "status": "downloading",
                                "downloaded_bytes": index * 5000,
                                "total_bytes": 1000000,
                            }
                        )
                state.options["progress_hooks"][0](
                    {
                        "status": "finished",
                        "downloaded_bytes": len(state.body),
                        "total_bytes": len(state.body),
                    }
                )
            return info

    monkeypatch.setitem(sys.modules, "yt_dlp", SimpleNamespace(YoutubeDL=FakeYoutubeDL))
    return state


def test_youtube_download_is_bounded_single_file_and_preserves_public_provenance(
    tmp_path, fake_youtube, video_bytes
):
    progress = []
    folder = tmp_path / ".media"
    path, provenance = download_youtube(
        "https://youtu.be/abcdefghI_1?si=ignored",
        folder,
        max_bytes=len(video_bytes),
        progress=progress.append,
    )
    assert path.read_bytes() == video_bytes
    assert re.fullmatch(r"[a-f0-9]{32}\.mp4", path.name)
    assert list(folder.iterdir()) == [path]
    assert provenance == {
        "source_type": "youtube",
        "url": "https://www.youtube.com/watch?v=abcdefghI_1",
        "id": "abcdefghI_1",
        "title": "Badminton sample",
        "channel": "Example",
    }
    assert progress[0] == 0 and progress[-1] == 1 and progress == sorted(progress)
    assert fake_youtube.calls == [(provenance["url"], True)]
    options = fake_youtube.options
    assert options["max_filesize"] == len(video_bytes)
    assert options["noplaylist"] is True
    # yt-dlp raises MaxDownloadsReached *after* a successful first file if this
    # is set to 1. Canonical single-video URLs + the metadata guard enforce one
    # source without mistaking a completed download for a failure.
    assert "max_downloads" not in options
    assert options["allowed_extractors"] == ["youtube"]
    assert "cookiefile" not in options and "cookiesfrombrowser" not in options


def test_small_download_updates_accumulate_into_visible_progress(
    tmp_path, fake_youtube
):
    fake_youtube.behavior = "incremental"
    progress = []
    download_youtube(
        "https://youtu.be/abcdefghI_1", tmp_path / ".media", progress=progress.append
    )
    assert progress[0] == 0 and progress[-1] == 1
    assert len(progress) > 20
    assert any(0.25 < value < 0.75 for value in progress)
    assert progress == sorted(progress)


@pytest.mark.parametrize(
    "behavior",
    ["partial_error", "missing_file", "wrong_id", "live", "private", "drm", "playlist"],
)
def test_youtube_failure_cleans_owned_directory_and_redacts_downloader_details(
    tmp_path, fake_youtube, behavior
):
    fake_youtube.behavior = behavior
    folder = tmp_path / ".media"
    with pytest.raises(MediaImportError) as error:
        download_youtube("https://youtu.be/abcdefghI_1", folder)
    assert "token=secret" not in str(error.value)
    assert list(folder.iterdir()) == []


def test_youtube_size_limit_rejects_hook_and_final_file_even_if_no_hook(
    tmp_path, fake_youtube, video_bytes
):
    folder = tmp_path / ".media"
    for behavior in ("success", "no_hook"):
        fake_youtube.behavior = behavior
        with pytest.raises(MediaTooLargeError):
            download_youtube(
                "https://youtu.be/abcdefghI_1", folder, max_bytes=len(video_bytes) - 1
            )
        assert list(folder.iterdir()) == []


def test_youtube_validates_actual_downloaded_video_and_cleans_it(
    tmp_path, fake_youtube
):
    fake_youtube.body = b"not actual video"
    folder = tmp_path / ".media"
    with pytest.raises(MediaImportError, match="not a readable video"):
        download_youtube("https://youtu.be/abcdefghI_1", folder)
    assert list(folder.iterdir()) == []


def test_youtube_progress_failure_also_cleans_completed_file(tmp_path, fake_youtube):
    folder = tmp_path / ".media"

    def progress(value):
        if value == 1:
            raise RuntimeError("client disconnected")

    with pytest.raises(MediaImportError):
        download_youtube("https://youtu.be/abcdefghI_1", folder, progress=progress)
    assert list(folder.iterdir()) == []


def test_real_downloader_accepts_our_options_without_network(
    tmp_path, fake_youtube, monkeypatch
):
    download_youtube("https://youtu.be/abcdefghI_1", tmp_path / ".media")
    options = fake_youtube.options
    monkeypatch.undo()
    yt_dlp = pytest.importorskip("yt_dlp")
    # Constructor validates format selectors/runtime options but extracts no URL.
    with yt_dlp.YoutubeDL(options) as downloader:
        assert downloader.params["noplaylist"] is True
