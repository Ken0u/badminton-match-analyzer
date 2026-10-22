"""Generated publication checks; no application data or media are involved."""

import ctypes
import errno
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
from badminton import video


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _windows_error(code):
    error = PermissionError(errno.EACCES, "generated replace failure")
    error.winerror = code
    return error


def test_json_publication_preserves_serialization_and_creates_parents(tmp_path):
    path = tmp_path / "nested" / "result.json"
    document = {"unicode": "羽毛球", "values": [True, None, 1.25], "mapping": {1: "x"}}
    video.write_json(path, document)
    assert path.read_bytes() == json.dumps(document).encode("utf-8")
    assert list(path.parent.iterdir()) == [path]


def test_simultaneous_writers_own_distinct_closed_same_directory_files(
    tmp_path, monkeypatch
):
    path = tmp_path / "result.json"
    original = {"writer": -1, "body": "original"}
    video.write_json(path, original)
    # Neither a legacy publisher's file nor another unique publisher belongs to us.
    other_files = [tmp_path / "result.tmp", tmp_path / ".result.json.other.tmp"]
    for other in other_files:
        other.write_bytes(b"unrelated publisher")
    documents = [{"writer": index, "body": str(index) * 4096} for index in range(8)]
    barrier = threading.Barrier(len(documents), timeout=10)
    replace = Path.replace
    temporaries = []
    observed = []
    stop = threading.Event()
    reader_started = threading.Event()
    reader_saw_new = threading.Event()
    staged = set()
    stage_lock = threading.Lock()

    def publish(source, target):
        if target == path:
            with stage_lock:
                first_attempt = source not in staged
                staged.add(source)
            if first_attempt:
                temporaries.append(source)
                assert source.parent == path.parent
                assert source != target
                assert _read(source) in documents
                barrier.wait()
        return replace(source, target)

    def read_until_stopped():
        while not stop.is_set():
            document = _read(path)
            observed.append(document)
            reader_started.set()
            if document != original:
                reader_saw_new.set()
            time.sleep(0.0005)

    monkeypatch.setattr(Path, "replace", publish)
    with ThreadPoolExecutor(max_workers=9) as pool:
        reader = pool.submit(read_until_stopped)
        try:
            assert reader_started.wait(5)
            writers = [pool.submit(video.write_json, path, doc) for doc in documents]
            for writer in writers:
                writer.result(timeout=15)
            assert reader_saw_new.wait(5)
        finally:
            stop.set()
        reader.result(timeout=5)
    assert len(temporaries) == len(set(temporaries)) == len(documents)
    assert observed
    assert all(document in [original, *documents] for document in observed)
    assert _read(path) in documents
    assert set(tmp_path.iterdir()) == {path, *other_files}
    assert all(other.read_bytes() == b"unrelated publisher" for other in other_files)


def test_distinct_destinations_with_same_stem_do_not_share_temporary(
    tmp_path, monkeypatch
):
    paths = [tmp_path / "shared.json", tmp_path / "shared.data"]
    barrier = threading.Barrier(2, timeout=10)
    replace = Path.replace
    sources = []

    def publish(source, target):
        sources.append(source)
        barrier.wait()
        return replace(source, target)

    monkeypatch.setattr(Path, "replace", publish)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(video.write_json, path, {"target": path.name}) for path in paths
        ]
        for future in futures:
            future.result(timeout=15)
    assert len(set(sources)) == 2
    assert [_read(path) for path in paths] == [{"target": path.name} for path in paths]
    assert set(tmp_path.iterdir()) == set(paths)


@pytest.mark.parametrize("existing", [False, True])
def test_serialization_failure_preserves_destination_and_other_temporary(
    tmp_path, existing
):
    path = tmp_path / "result.json"
    other = tmp_path / ".result.json.someone-else.tmp"
    other.write_bytes(b"other writer")
    if existing:
        path.write_bytes(b'{"old":true}')
    with pytest.raises(TypeError):
        video.write_json(path, {"valid_prefix": [1] * 2000, "unsupported": object()})
    assert path.exists() is existing
    if existing:
        assert path.read_bytes() == b'{"old":true}'
    assert other.read_bytes() == b"other writer"
    assert set(tmp_path.iterdir()) == ({path, other} if existing else {other})


@pytest.mark.parametrize("code", [None, 2, 3, 87])
def test_unrelated_replace_errors_are_not_retried_and_preserve_old_document(
    tmp_path, monkeypatch, code
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    error = _windows_error(code)
    calls = []

    def deny(source, target):
        calls.append(source)
        raise error

    monkeypatch.setattr(Path, "replace", deny)
    with pytest.raises(PermissionError) as caught:
        video.write_json(path, {"new": True})
    assert caught.value is error
    assert len(calls) == 1
    assert path.read_bytes() == b'{"old":true}'
    assert list(tmp_path.iterdir()) == [path]


def test_invalid_parent_is_reported_without_modifying_it(tmp_path):
    parent = tmp_path / "parent-is-file"
    parent.write_bytes(b"unchanged")
    with pytest.raises(OSError):
        video.write_json(parent / "result.json", {"new": True})
    assert parent.read_bytes() == b"unchanged"
    assert list(tmp_path.iterdir()) == [parent]


def test_write_failure_preserves_old_json_and_cleans_owned_file(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    error = OSError(errno.ENOSPC, "generated full disk")
    fdopen = os.fdopen

    class FailedOutput:
        def __init__(self, *args, **kwargs):
            self.output = fdopen(*args, **kwargs)

        def __enter__(self):
            self.output.__enter__()
            return self

        def write(self, content):
            self.output.write(content[:4])
            raise error

        def __exit__(self, *args):
            return self.output.__exit__(*args)

    monkeypatch.setattr(os, "fdopen", FailedOutput)
    with pytest.raises(OSError) as caught:
        video.write_json(path, {"new": True})
    assert caught.value is error
    assert path.read_bytes() == b'{"old":true}'
    assert list(tmp_path.iterdir()) == [path]


def test_stream_open_failure_closes_descriptor_and_cleans_owned_file(
    tmp_path, monkeypatch
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    error = OSError(errno.EMFILE, "generated stream open failure")
    descriptors = []

    def deny(descriptor, *args, **kwargs):
        descriptors.append(descriptor)
        raise error

    monkeypatch.setattr(os, "fdopen", deny)
    with pytest.raises(OSError) as caught:
        video.write_json(path, {"new": True})
    assert caught.value is error
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert path.read_bytes() == b'{"old":true}'
    assert list(tmp_path.iterdir()) == [path]


def test_cleanup_denial_does_not_mask_publication_error(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    error = OSError(errno.ENOSPC, "generated publication failure")
    owned = []

    def deny_replace(source, target):
        owned.append(source)
        raise error

    def deny_unlink(source, **kwargs):
        assert source == owned[0]
        raise PermissionError("generated cleanup denial")

    monkeypatch.setattr(Path, "replace", deny_replace)
    monkeypatch.setattr(Path, "unlink", deny_unlink)
    with pytest.raises(OSError) as caught:
        video.write_json(path, {"new": True})
    assert caught.value is error
    assert path.read_bytes() == b'{"old":true}'
    assert set(tmp_path.iterdir()) == {path, owned[0]}
    assert _read(owned[0]) == {"new": True}


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_windows_replace_errors_retry_complete_owned_document(
    tmp_path, monkeypatch, code
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    replace = Path.replace
    calls = []
    delays = []
    error = _windows_error(code)

    def publish(source, target):
        calls.append(source)
        assert _read(source) == {"new": True}
        if len(calls) < 3:
            assert path.read_bytes() == b'{"old":true}'
            raise error
        return replace(source, target)

    monkeypatch.setattr(video, "_WINDOWS", True)
    monkeypatch.setattr(video.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "replace", publish)
    video.write_json(path, {"new": True})
    assert len(calls) == 3
    assert len(set(calls)) == 1
    assert len(delays) == 2
    assert 0 < sum(delays) <= 0.3
    assert _read(path) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("code", [5, 32, 33])
def test_persistent_windows_replace_error_exposes_final_error_with_bounded_retries(
    tmp_path, monkeypatch, code
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    failures = []
    delays = []

    def deny(source, target):
        error = _windows_error(code)
        failures.append(error)
        raise error

    monkeypatch.setattr(video, "_WINDOWS", True)
    monkeypatch.setattr(video.time, "sleep", delays.append)
    monkeypatch.setattr(Path, "replace", deny)
    with pytest.raises(PermissionError) as caught:
        video.write_json(path, {"new": True})
    assert 2 <= len(failures) <= 6
    assert len(delays) == len(failures) - 1
    assert 0 < sum(delays) <= 0.3
    assert caught.value is failures[-1]
    assert path.read_bytes() == b'{"old":true}'
    assert list(tmp_path.iterdir()) == [path]


def test_non_windows_never_retries_windows_like_error(tmp_path, monkeypatch):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    calls = []
    error = _windows_error(5)

    def deny(source, target):
        calls.append(source)
        raise error

    monkeypatch.setattr(video, "_WINDOWS", False)
    monkeypatch.setattr(Path, "replace", deny)
    with pytest.raises(PermissionError) as caught:
        video.write_json(path, {"new": True})
    assert caught.value is error
    assert len(calls) == 1
    assert path.read_bytes() == b'{"old":true}'
    assert list(tmp_path.iterdir()) == [path]


def test_directory_destination_is_not_replaced_or_removed(tmp_path):
    path = tmp_path / "directory.json"
    path.mkdir()
    child = path / "keep.txt"
    child.write_bytes(b"preserved")
    with pytest.raises(OSError):
        video.write_json(path, {"new": True})
    assert child.read_bytes() == b"preserved"
    assert list(tmp_path.iterdir()) == [path]


@contextmanager
def _deny_windows_delete(path):
    """Own one generated handle; never discover or terminate external processes."""
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    # GENERIC_READ, SHARE_READ | SHARE_WRITE (deliberately no SHARE_DELETE), OPEN_EXISTING.
    handle = create(str(path), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    closed = False
    lock = threading.Lock()

    def release():
        nonlocal closed
        with lock:
            if not closed:
                if not close(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
                closed = True

    try:
        yield release
    finally:
        release()


@pytest.mark.skipif(os.name != "nt", reason="actual Windows sharing handles")
def test_windows_actual_temporary_sharing_denial_recovers_after_release(
    tmp_path, monkeypatch
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    replace = Path.replace
    denied = threading.Event()
    released = threading.Event()
    failures = []

    def publish(source, target):
        try:
            return replace(source, target)
        except OSError as error:
            failures.append(error)
            denied.set()
            assert released.wait(5)
            raise

    monkeypatch.setattr(Path, "replace", publish)
    with _deny_windows_delete(path) as release:

        def release_after_denial():
            assert denied.wait(5)
            assert path.read_bytes() == b'{"old":true}'
            release()
            released.set()

        with ThreadPoolExecutor(max_workers=1) as pool:
            releaser = pool.submit(release_after_denial)
            try:
                video.write_json(path, {"new": True})
            finally:
                # Unblock the controlled releaser even if publication fails before replace.
                denied.set()
                release()
                released.set()
            releaser.result(timeout=6)
    assert len(failures) == 1
    assert failures[0].winerror in {5, 32, 33}
    assert _read(path) == {"new": True}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != "nt", reason="actual Windows sharing handles")
def test_windows_actual_persistent_sharing_denial_is_bounded_and_preserves_old_json(
    tmp_path, monkeypatch
):
    path = tmp_path / "result.json"
    path.write_bytes(b'{"old":true}')
    replace = Path.replace
    failures = []

    def publish(source, target):
        try:
            return replace(source, target)
        except OSError as error:
            failures.append(error)
            raise

    monkeypatch.setattr(Path, "replace", publish)
    with _deny_windows_delete(path):
        started = time.monotonic()
        with pytest.raises(OSError) as caught:
            video.write_json(path, {"new": True})
        elapsed = time.monotonic() - started
        assert path.read_bytes() == b'{"old":true}'
    assert 2 <= len(failures) <= 6
    assert elapsed < 1
    assert all(error.winerror in {5, 32, 33} for error in failures)
    assert caught.value is failures[-1]
    assert list(tmp_path.iterdir()) == [path]
