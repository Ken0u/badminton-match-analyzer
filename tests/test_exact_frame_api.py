"""Exact review images must retain native frame and source identity."""

import io
from contextlib import contextmanager
from fractions import Fraction

import av
import numpy as np
import pytest
from badminton import ingest
from badminton import video as media
from badminton.api import create_app
from badminton.orientation import orient_frame
from badminton.storage import Store
from fastapi.testclient import TestClient
from media_fixtures import write_rotated_video
from PIL import Image


@pytest.fixture
def registered(tmp_path, monkeypatch):
    monkeypatch.delenv("BADMINTON_USERNAME", raising=False)
    monkeypatch.delenv("BADMINTON_PASSWORD", raising=False)
    snapshots = []

    def create(rotation=0, origin=0, mode="singles", stale=None):
        path = write_rotated_video(
            tmp_path / "generated.mp4",
            rotation,
            timestamps=tuple(origin + t for t in (0, 40, 120, 160)),
        )
        with path.open("ab") as stream:
            stream.write((16).to_bytes(4, "big") + b"free" + b"original")
        store = Store(tmp_path / "processed")
        document = ingest.inspect_video(path, mode, store, tmp_path)
        if stale:
            document.update(stale)
            store.register(document)
        store.annotations(document["id"])
        folder = store.data / document["id"]
        # A generated stand-in for prior output must survive failed review reads.
        (folder / "prior-predictions.json").write_text('{"generated":true}\n')
        prior = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        snapshots.append((store, document, folder, prior))
        return path, store, document, media.timestamps_for(store.data, document["id"])

    yield create
    for store, document, folder, prior in snapshots:
        assert store.video(document["id"]) == document
        assert {
            p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()
        } == prior


def instrument(monkeypatch, transform=None, change=None, phase="close", failure=None):
    """Alter actual generated decoder output, covering both old and new readers."""
    original = media.open_media
    observed = {"closed": False, "pts": []}

    @contextmanager
    def opened(*args, **kwargs):
        try:
            with original(*args, **kwargs) as container:

                class Decoder:
                    streams = container.streams
                    seek = container.seek

                    def decode(self, stream):
                        frames = container.decode(stream)
                        if transform:
                            frames = transform(list(frames))
                        for position, frame in enumerate(frames):
                            if position == 1:
                                if change and phase == "decode":
                                    change()
                                if failure == "decode":
                                    raise RuntimeError("original decoder failure")
                            observed["pts"].append(frame.pts)
                            yield frame

                yield Decoder()
        finally:
            observed["closed"] = True
            if change and phase == "close":
                change()
            if failure == "close":
                raise RuntimeError("original close failure")

    monkeypatch.setattr(ingest, "open_media", opened)
    monkeypatch.setattr(media, "open_media", opened)
    return observed


def request(root, store, document, index=1):
    with TestClient(create_app(root, store.data)) as client:
        return client.get(f"/api/videos/{document['id']}/frame?index={index}")


@pytest.mark.parametrize("fault", ["middle", "tail", "empty", "shift", "missing_pts"])
def test_inexact_decoder_output_never_returns_a_review_jpeg(
    registered, tmp_path, monkeypatch, fault
):
    path, store, document, _times = registered()
    original = path.read_bytes()

    def transform(frames):
        if fault == "empty":
            return []
        if fault in ("middle", "tail"):
            frames.pop(1 if fault == "middle" else 3)
        elif fault == "shift":
            frames[1].pts += 16
        else:
            frames[1].pts = None
        return frames

    observed = instrument(monkeypatch, transform)
    response = request(tmp_path, store, document, 3 if fault == "tail" else 1)
    assert response.status_code == 409
    assert "frame" in response.text.lower() or "timestamp" in response.text.lower()
    assert not response.headers["content-type"].startswith("image/")
    assert observed["closed"] and path.read_bytes() == original


@pytest.mark.parametrize("phase", ["decode", "close"])
@pytest.mark.parametrize("mode,rotation", [("singles", 0), ("doubles", 90)])
def test_source_change_is_rejected_after_native_media_close(
    registered, tmp_path, monkeypatch, phase, mode, rotation
):
    path, store, document, _times = registered(rotation=rotation, mode=mode)
    original = path.read_bytes()
    observed = instrument(
        monkeypatch, change=lambda: path.write_bytes(original + b"changed"), phase=phase
    )
    response = request(tmp_path, store, document)
    assert response.status_code == 409 and "changed" in response.text.lower()
    assert observed["closed"] and path.read_bytes() != original


@pytest.mark.parametrize("replacement", [False, True])
def test_same_size_restored_mtime_change_cannot_reuse_source_validation(
    registered, tmp_path, monkeypatch, replacement
):
    from test_file_cache import changed

    path, store, document, _times = registered()
    original = path.read_bytes()
    observed = instrument(
        monkeypatch,
        change=lambda: changed(path, original[:-1] + b"X", replacement),
    )
    response = request(tmp_path, store, document)
    assert response.status_code == 409 and "changed" in response.text.lower()
    assert observed["closed"]


def test_source_removed_during_close_returns_unavailable(
    registered, tmp_path, monkeypatch
):
    path, store, document, _times = registered()
    observed = instrument(monkeypatch, change=path.unlink)
    response = request(tmp_path, store, document)
    assert response.status_code == 404 and "unavailable" in response.text.lower()
    assert observed["closed"] and not path.exists()


@pytest.mark.parametrize("stale", [{"rotation": 90}, {"width": 129}])
def test_imported_display_contract_must_match_decoded_frame(
    registered, tmp_path, monkeypatch, stale
):
    _path, store, document, _times = registered(stale=stale)
    observed = instrument(monkeypatch)
    response = request(tmp_path, store, document)
    assert response.status_code == 409
    assert "reimport" in response.text.lower()
    assert observed["closed"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", [0, 5000])
def test_exact_vfr_pixels_origin_rotation_and_response_contract(
    registered, tmp_path, monkeypatch, rotation, origin
):
    path, store, document, times = registered(rotation=rotation, origin=origin)
    original = path.read_bytes()
    with av.open(str(path)) as container:
        expected = [np.asarray(orient_frame(f).to_image()) for f in container.decode(0)]
    observed = instrument(monkeypatch)
    for index in range(4):
        observed["closed"] = False
        observed["pts"].clear()
        response = request(tmp_path, store, document, index)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.headers["cache-control"] == "private, max-age=3600"
        pixels = np.asarray(Image.open(io.BytesIO(response.content)))
        assert pixels.shape == expected[index].shape
        assert np.mean(np.abs(pixels.astype(float) - expected[index])) < 5
        assert observed["closed"]
        assert float(
            observed["pts"][-1] * Fraction(document["time_base"])
        ) == pytest.approx(times[index] + document["source_start_s"])
    assert document["source_start_s"] == pytest.approx(origin / 1000)
    assert path.read_bytes() == original


@pytest.mark.parametrize("failure", ["decode", "close"])
def test_original_decoder_or_close_failure_is_not_replaced(
    registered, tmp_path, monkeypatch, failure
):
    path, store, document, _times = registered()
    original = path.read_bytes()
    observed = instrument(
        monkeypatch,
        change=lambda: path.write_bytes(original + b"changed"),
        failure=failure,
    )
    with pytest.raises(RuntimeError, match=r"original .* failure"):
        request(tmp_path, store, document)
    assert observed["closed"]


@pytest.mark.parametrize("index", [-1, 4])
def test_invalid_index_is_rejected_without_decoding(
    registered, tmp_path, monkeypatch, index
):
    _path, store, document, _times = registered()
    observed = instrument(monkeypatch)
    assert request(tmp_path, store, document, index).status_code == 422
    assert observed["pts"] == []
