"""Generated app-source and clock invalidation without opening source media."""

import hashlib
from unittest.mock import patch

import pytest
from badminton.file_cache import FileChangedError
from badminton.video import SourceChangedError, resolve_source, timestamps_for
from test_file_cache import changed


@pytest.mark.parametrize("replacement", [False, True])
def test_changed_same_size_timestamp_preserving_source_is_rejected(
    tmp_path, replacement
):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    video = {"path": source.name, "sha256": hashlib.sha256(b"original").hexdigest()}
    assert resolve_source(video, tmp_path) == source
    changed(source, b"modified", replacement)
    with pytest.raises(SourceChangedError, match="changed since import"):
        resolve_source(video, tmp_path)


@pytest.mark.parametrize("replacement", [False, True])
def test_timestamp_edits_refresh_native_frame_timing(tmp_path, replacement):
    source = tmp_path / "video-id" / "timestamps.json"
    source.parent.mkdir()
    source.write_bytes(b"[0.0,0.1]")
    assert timestamps_for(tmp_path, "video-id") == (0, 0.1)
    changed(source, b"[0.0,0.2]", replacement)
    assert timestamps_for(tmp_path, "video-id") == (0, 0.2)


def test_concurrent_source_mutation_keeps_the_source_changed_error_contract(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"original")
    video = {"path": source.name, "sha256": hashlib.sha256(b"original").hexdigest()}
    with (
        patch("badminton.video.file_digest", side_effect=FileChangedError("changed")),
        pytest.raises(SourceChangedError, match="changed"),
    ):
        resolve_source(video, tmp_path)
