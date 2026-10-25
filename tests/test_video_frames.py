"""Native image-analysis inputs must not silently lose imported source frames."""

from contextlib import contextmanager

import numpy as np
import pytest
from badminton import video as media
from badminton.ingest import inspect_video
from badminton.orientation import OrientationError
from badminton.storage import Store
from media_fixtures import write_rotated_video


@pytest.fixture
def source(tmp_path):
    path = write_rotated_video(tmp_path / "native-vfr.mp4", 0)
    store = Store(tmp_path / "processed")
    document = inspect_video(path, "singles", store, tmp_path)
    times = media.timestamps_for(store.data, document["id"])
    original = path.read_bytes()
    annotations = store.annotations(document["id"]).model_dump()
    clock_path = store.data / document["id"] / "timestamps.json"
    clock = clock_path.read_bytes()
    yield document, tmp_path, times
    assert path.read_bytes() == original
    assert store.annotations(document["id"]).model_dump() == annotations
    assert clock_path.read_bytes() == clock


def instrument_decoder(monkeypatch, transform=None):
    """Fault-inject only decoder outputs; pixels/PTS come from real PyAV media."""
    original = media.open_media
    observation = {"opened": False, "closed": False, "yielded_pts": []}

    @contextmanager
    def opened(*args, **kwargs):
        with original(*args, **kwargs) as container:
            observation["opened"] = True

            class Decoder:
                streams = container.streams
                seek = container.seek

                def decode(self, stream):
                    frames = container.decode(stream)
                    if transform is not None:
                        frames = transform(list(frames))
                    for frame in frames:
                        observation["yielded_pts"].append(frame.pts)
                        yield frame

            try:
                yield Decoder()
            finally:
                observation["closed"] = True

    monkeypatch.setattr(media, "open_media", opened)
    return observation


@pytest.mark.parametrize("indices", [[], [1, 2, 3], [0, 2, 3], [0, 1, 2]])
def test_missing_native_frame_is_not_a_successful_shorter_range(
    source, monkeypatch, indices
):
    document, root, times = source
    observation = instrument_decoder(
        monkeypatch, lambda frames: [frames[i] for i in indices]
    )
    with pytest.raises(media.SourceChangedError, match=r"frame|decode"):
        list(media.iter_frames(document, root, times, 0, 4))
    assert observation["closed"]


@pytest.mark.parametrize("indices", [[0, 1, 1, 2, 3], [0, 1, 0, 2, 3]])
def test_duplicate_or_backward_identity_is_rejected(source, monkeypatch, indices):
    document, root, times = source
    observation = instrument_decoder(
        monkeypatch, lambda frames: [frames[i] for i in indices]
    )
    frames = media.iter_frames(document, root, times, 0, 4)
    assert next(frames)[0] == 0
    assert next(frames)[0] == 1
    with pytest.raises(media.SourceChangedError, match=r"frame|decode"):
        next(frames)
    assert observation["closed"]


def test_preroll_cannot_hide_backward_frame_after_requested_output(source, monkeypatch):
    document, root, times = source
    observation = instrument_decoder(
        monkeypatch, lambda frames: [frames[i] for i in (0, 1, 2, 0, 3)]
    )
    frames = media.iter_frames(document, root, times, 2, 4)
    assert next(frames)[0] == 2
    with pytest.raises(media.SourceChangedError, match=r"frame|decode"):
        next(frames)
    assert observation["closed"]


def test_missing_pts_cannot_disappear_from_native_inputs(source, monkeypatch):
    document, root, times = source

    def missing_pts(frames):
        frames[1].pts = None
        return frames

    observation = instrument_decoder(monkeypatch, missing_pts)
    with pytest.raises(media.SourceChangedError, match=r"timestamp|frame"):
        list(media.iter_frames(document, root, times, 0, 4))
    assert observation["closed"]


def test_foreign_decoded_pts_remains_rejected(source, monkeypatch):
    document, root, times = source

    def shifted_pts(frames):
        frames[1].pts += 1
        return frames

    observation = instrument_decoder(monkeypatch, shifted_pts)
    with pytest.raises(media.SourceChangedError, match=r"timestamp|frame"):
        list(media.iter_frames(document, root, times, 0, 4))
    assert observation["closed"]


@pytest.mark.parametrize("start,end", [(0, 4), (1, 3), (2, 3), (3, 4)])
def test_native_vfr_subrange_and_keyframe_preroll(source, monkeypatch, start, end):
    document, root, times = source
    observation = instrument_decoder(monkeypatch)
    frames = list(media.iter_frames(document, root, times, start, end))
    assert [index for index, _, _ in frames] == list(range(start, end))
    assert [timestamp for _, timestamp, _ in frames] == pytest.approx(times[start:end])
    assert [
        float(frame.pts * frame.time_base) for _, _, frame in frames
    ] == pytest.approx(times[start:end])
    assert observation["closed"]
    # The reader may decode preroll, but must not ask for a frame past end-1.
    assert observation["yielded_pts"][-1] == frames[-1][2].pts


def test_explicit_early_close_is_not_an_incomplete_decode_failure(source, monkeypatch):
    document, root, times = source
    observation = instrument_decoder(monkeypatch)
    frames = media.iter_frames(document, root, times, 0, 4)
    assert next(frames)[0] == 0
    frames.close()
    assert observation["closed"]
    assert len(observation["yielded_pts"]) == 1


@pytest.mark.parametrize("start,end", [(-1, 2), (0, 5), (2, 2), (3, 1)])
def test_invalid_bounds_fail_before_decode(source, monkeypatch, start, end):
    document, root, times = source
    observation = instrument_decoder(monkeypatch)
    with pytest.raises(ValueError, match="range"):
        list(media.iter_frames(document, root, times, start, end))
    assert not observation["opened"]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_complete_native_reader_preserves_oriented_pixels_and_source_clock(
    tmp_path, rotation
):
    import av

    path = write_rotated_video(tmp_path / "oriented.mp4", rotation)
    with av.open(str(path)) as container:
        raw = list(container.decode(container.streams.video[0]))
    store = Store(tmp_path / "processed")
    document = inspect_video(path, "doubles", store, tmp_path)
    times = media.timestamps_for(store.data, document["id"])
    frames = list(media.iter_frames(document, tmp_path, times, 0, 4))
    for original, (index, timestamp, oriented) in zip(raw, frames, strict=True):
        expected = np.rot90(original.to_ndarray(format="rgb24"), rotation // 90)
        np.testing.assert_array_equal(oriented.to_ndarray(format="rgb24"), expected)
        assert oriented.pts == original.pts and oriented.time_base == original.time_base
        assert timestamp == times[index]


def test_full_video_reader_does_not_inherit_short_analysis_limit(tmp_path):
    path = write_rotated_video(
        tmp_path / "long-gaps.mp4", 0, timestamps=(0, 40000, 120000, 160000)
    )
    store = Store(tmp_path / "processed")
    document = inspect_video(path, "singles", store, tmp_path)
    times = media.timestamps_for(store.data, document["id"])
    assert document["duration_s"] > 120
    assert [i for i, _, _ in media.iter_frames(document, tmp_path, times, 0, 4)] == [
        0,
        1,
        2,
        3,
    ]


def test_source_and_orientation_guards_are_not_relaxed(source):
    document, root, times = source
    with pytest.raises(media.SourceChangedError, match="changed"):
        list(media.iter_frames(document | {"sha256": "0" * 64}, root, times, 0, 4))
    with pytest.raises(OrientationError, match="Reimport"):
        list(media.iter_frames(document | {"rotation": 90}, root, times, 0, 4))


@pytest.fixture
def mutable_source(tmp_path):
    """Keep registered truth immutable while allowing generated media changes."""

    def create(mode="singles", rotation=0):
        path = write_rotated_video(tmp_path / "mutable.mp4", rotation)
        # A valid free atom allows same-size data changes without corrupting PTS.
        with path.open("ab") as stream:
            stream.write((16).to_bytes(4, "big") + b"free" + b"original")
        store = Store(tmp_path / "processed")
        document = inspect_video(path, mode, store, tmp_path)
        times = media.timestamps_for(store.data, document["id"])
        folder = store.data / document["id"]
        prior = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        annotations = store.annotations(document["id"]).model_dump()
        return path, store, document, times, prior, annotations

    return create


def changing_native_decoder(monkeypatch, change, phase, failure=None):
    """Inject a source change around real native decoding and normal close."""
    original = media.open_media
    observed = {"closed": False, "changed": False, "yielded_pts": []}

    def mutate():
        if not observed["changed"]:
            change()
            observed["changed"] = True

    @contextmanager
    def opened(*args, **kwargs):
        try:
            with original(*args, **kwargs) as container:

                class Decoder:
                    streams = container.streams
                    seek = container.seek

                    def decode(self, stream):
                        for position, frame in enumerate(container.decode(stream)):
                            if position == 1:
                                if phase == "decode":
                                    mutate()
                                if failure == "decode":
                                    raise RuntimeError("original decoder failure")
                            observed["yielded_pts"].append(frame.pts)
                            yield frame

                yield Decoder()
        finally:
            observed["closed"] = True
            if phase == "teardown":
                mutate()
            if failure == "teardown":
                raise RuntimeError("original teardown failure")

    monkeypatch.setattr(media, "open_media", opened)
    return observed


def assert_registered_source_unchanged(store, document, prior, annotations):
    folder = store.data / document["id"]
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} == prior
    assert store.video(document["id"]) == document
    assert store.annotations(document["id"]).model_dump() == annotations


@pytest.mark.parametrize("phase", ["decode", "teardown"])
@pytest.mark.parametrize("mode,rotation", [("singles", 0), ("doubles", 90)])
def test_complete_native_read_rejects_changed_source_after_media_close(
    mutable_source, tmp_path, monkeypatch, phase, mode, rotation
):
    path, store, document, times, prior, annotations = mutable_source(mode, rotation)
    original = path.read_bytes()
    observed = changing_native_decoder(
        monkeypatch, lambda: path.write_bytes(original + b"changed"), phase
    )
    frames = media.iter_frames(document, tmp_path, times, 1, 4)
    returned = []
    with pytest.raises(media.SourceChangedError, match="changed since import"):
        for index, timestamp, frame in frames:
            returned.append((index, timestamp))
            assert (frame.width, frame.height) == (
                document["width"],
                document["height"],
            )
    assert returned == list(enumerate(times[1:4], start=1))
    assert observed["closed"] and observed["changed"]
    assert_registered_source_unchanged(store, document, prior, annotations)


@pytest.mark.parametrize("replacement", [False, True])
def test_native_read_rejects_same_size_restored_mtime_source_after_teardown(
    mutable_source, tmp_path, monkeypatch, replacement
):
    from test_file_cache import changed

    path, store, document, times, prior, annotations = mutable_source()
    content = path.read_bytes()
    observed = changing_native_decoder(
        monkeypatch,
        lambda: changed(path, content[:-1] + b"X", replacement),
        "teardown",
    )
    with pytest.raises(media.SourceChangedError, match="changed since import"):
        list(media.iter_frames(document, tmp_path, times, 0, 4))
    assert observed["closed"] and observed["changed"]
    assert_registered_source_unchanged(store, document, prior, annotations)


def test_native_read_rejects_source_removed_during_teardown(
    mutable_source, tmp_path, monkeypatch
):
    path, store, document, times, prior, annotations = mutable_source()
    observed = changing_native_decoder(monkeypatch, path.unlink, "teardown")
    with pytest.raises(FileNotFoundError, match="source is unavailable"):
        list(media.iter_frames(document, tmp_path, times, 0, 4))
    assert observed["closed"] and not path.exists()
    assert_registered_source_unchanged(store, document, prior, annotations)


def test_byte_identical_replacement_remains_the_registered_native_source(
    mutable_source, tmp_path, monkeypatch
):
    path, _store, document, times, _prior, _annotations = mutable_source()
    original = path.read_bytes()

    def replace():
        replacement = path.with_suffix(".new")
        replacement.write_bytes(original)
        replacement.replace(path)

    observed = changing_native_decoder(monkeypatch, replace, "teardown")
    assert [
        i for i, _, _ in media.iter_frames(document, tmp_path, times, 0, 4)
    ] == list(range(4))
    assert observed["closed"] and path.read_bytes() == original


@pytest.mark.parametrize("phase", ["decode", "teardown"])
def test_original_native_failure_is_not_replaced_by_later_source_validation(
    mutable_source, tmp_path, monkeypatch, phase
):
    path, _store, document, times, _prior, _annotations = mutable_source()
    original = path.read_bytes()
    observed = changing_native_decoder(
        monkeypatch,
        lambda: path.write_bytes(original + b"changed"),
        "teardown",
        failure=phase,
    )
    with pytest.raises(RuntimeError, match=f"original {phase}.*failure"):
        list(media.iter_frames(document, tmp_path, times, 0, 4))
    assert observed["closed"] and observed["changed"]


def test_changed_source_does_not_turn_explicit_partial_close_into_failure(
    mutable_source, tmp_path, monkeypatch
):
    path, _store, document, times, _prior, _annotations = mutable_source()
    original = path.read_bytes()
    observed = changing_native_decoder(
        monkeypatch, lambda: path.write_bytes(original + b"changed"), "teardown"
    )
    frames = media.iter_frames(document, tmp_path, times, 0, 4)
    assert next(frames)[0] == 0
    frames.close()
    assert observed["closed"] and observed["changed"]
    assert len(observed["yielded_pts"]) == 1
    with pytest.raises(media.SourceChangedError, match="changed since import"):
        media.resolve_source(document, tmp_path)


def test_injected_consumer_failure_survives_changed_source_close(
    mutable_source, tmp_path, monkeypatch
):
    path, _store, document, times, _prior, _annotations = mutable_source()
    original = path.read_bytes()
    observed = changing_native_decoder(
        monkeypatch, lambda: path.write_bytes(original + b"changed"), "teardown"
    )
    frames = media.iter_frames(document, tmp_path, times, 0, 4)
    next(frames)
    with pytest.raises(RuntimeError, match="original consumer failure"):
        frames.throw(RuntimeError("original consumer failure"))
    assert observed["closed"] and observed["changed"]
