"""Generated files exercise observable replacement, edits and concurrent reads."""

import hashlib
import os
import struct
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from badminton import file_cache as cache


def changed(path, content, replacement=False):
    before = path.stat()
    target = path.with_name(path.name + ".new") if replacement else path
    target.write_bytes(content)
    assert target.stat().st_size == before.st_size
    os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns))
    if replacement:
        target.replace(path)
    assert path.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("replacement", [False, True])
def test_same_size_and_mtime_do_not_reuse_old_file_bytes(tmp_path, replacement):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    before = cache.file_digest(source)
    changed(source, b"new bytes", replacement)
    after = cache.file_digest(source)
    assert after == hashlib.sha256(b"new bytes").hexdigest() and after != before


@pytest.mark.parametrize("replacement", [False, True])
def test_same_size_and_mtime_reload_timestamp_values(tmp_path, replacement):
    source = tmp_path / "timestamps.json"
    source.write_bytes(b"[0.0,0.1]")
    assert cache.timestamp_tuple(source) == (0, 0.1)
    changed(source, b"[0.0,0.2]", replacement)
    assert cache.timestamp_tuple(source) == (0, 0.2)


def test_unchanged_file_reuses_bytes_without_rehashing_or_reparsing(tmp_path):
    source = tmp_path / "timestamps.json"
    source.write_bytes(b"[0.0,0.1]")
    with source.open("rb") as handle:
        _, reusable = cache._observe(handle)
    with patch.object(cache, "_hash", wraps=cache._hash) as hashed:
        first = cache.file_digest(source)
        assert cache.file_digest(source) == first
        assert hashed.call_count == (1 if reusable else 4)
    with patch.object(cache, "_timestamps", wraps=cache._timestamps) as parsed:
        assert cache.timestamp_tuple(source) == cache.timestamp_tuple(source)
        assert parsed.call_count == (1 if reusable else 4)


def test_unavailable_change_metadata_disables_reuse_even_for_a_primed_file(
    tmp_path, monkeypatch
):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    cache.file_digest(source)
    monkeypatch.setattr(cache, "_WINDOWS", True)
    monkeypatch.setattr(cache, "_windows_metadata", lambda handle: None)
    with patch.object(cache, "_hash", wraps=cache._hash) as hashed:
        assert cache.file_digest(source) == hashlib.sha256(b"old bytes").hexdigest()
        changed(source, b"new bytes")
        assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()
        assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()
        assert hashed.call_count == 6


@pytest.mark.skipif(os.name != "nt", reason="Real Windows file-handle metadata")
def test_actual_windows_version_or_fallback_observes_timestamp_restoration(tmp_path):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    before = source.stat()
    with source.open("rb") as handle:
        first = cache._windows_metadata(handle)
    assert cache.file_digest(source) == hashlib.sha256(b"old bytes").hexdigest()
    changed(source, b"new bytes")
    with source.open("rb") as handle:
        second = cache._windows_metadata(handle)
    if first is not None and second is not None:
        assert first[-1] != second[-1]
    assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()
    assert before.st_ino == source.stat().st_ino
    assert before.st_mtime_ns == source.stat().st_mtime_ns


@pytest.mark.skipif(os.name != "nt", reason="Windows API fallback")
@pytest.mark.parametrize("failure", ["unsupported", "unavailable", "zero"])
def test_windows_query_failures_disable_metadata_reuse(tmp_path, monkeypatch, failure):
    source = tmp_path / "media"
    source.write_bytes(b"generated")
    if failure == "unavailable":

        def unavailable():
            raise OSError("metadata query unavailable")

        monkeypatch.setattr(cache, "_windows_api", unavailable)
    else:
        ctypes, info, _ = cache._windows_api()
        # A successful query with unavailable zero change time is also unusable.
        monkeypatch.setattr(
            cache,
            "_windows_api",
            lambda: (ctypes, info, lambda *args: failure == "zero"),
        )
    with source.open("rb") as handle:
        assert cache._windows_metadata(handle) is None


def test_read_mutation_fails_and_does_not_publish_a_cached_value(tmp_path):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")

    def mutate(handle):
        value = cache._hash(handle)
        changed(source, b"new bytes")
        return value

    with pytest.raises(cache.FileChangedError, match="changed while reading"):
        cache._read(source, "sha256", mutate)
    assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()


def test_cache_hit_also_checks_for_a_concurrent_change(tmp_path, monkeypatch):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    with source.open("rb") as handle:
        if not cache._observe(handle)[1]:
            pytest.skip("No reliable filesystem version; no cache hit is possible")
    cache.file_digest(source)
    observe = cache._observe
    count = 0

    def mutate(handle):
        nonlocal count
        result = observe(handle)
        count += 1
        if count == 1:
            changed(source, b"new bytes")
        return result

    monkeypatch.setattr(cache, "_observe", mutate)
    with pytest.raises(cache.FileChangedError, match="changed while reading"):
        cache.file_digest(source)
    assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()


def test_pathname_must_still_refer_to_the_opened_file(tmp_path, monkeypatch):
    source = tmp_path / "media"
    source.write_bytes(b"generated")
    other = tmp_path / "replacement"
    other.write_bytes(b"generated")
    original = Path.open
    count = 0

    def substituted(path, *args, **kwargs):
        nonlocal count
        if path == source:
            count += 1
            if count == 2:
                return original(other, *args, **kwargs)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", substituted)
    with pytest.raises(cache.FileChangedError):
        cache.file_digest(source)


def test_path_stat_creation_time_does_not_conflict_with_handle_change_time(
    tmp_path, monkeypatch
):
    source = tmp_path / "media"
    source.write_bytes(b"generated")
    original = Path.stat

    def creation_time(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        return SimpleNamespace(
            st_dev=info.st_dev,
            st_ino=info.st_ino,
            st_size=info.st_size,
            st_mtime_ns=info.st_mtime_ns,
            st_ctime_ns=info.st_ctime_ns - 1_000_000,
        )

    monkeypatch.setattr(Path, "stat", creation_time)
    assert cache.file_digest(source) == hashlib.sha256(b"generated").hexdigest()


def test_unavailable_versions_detect_changes_even_with_identical_metadata(
    tmp_path, monkeypatch
):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    with source.open("rb") as handle:
        fixed, _ = cache._observe(handle)
    monkeypatch.setattr(cache, "_observe", lambda handle: (fixed, False))

    def mutate(handle):
        value = cache._hash(handle)
        changed(source, b"new bytes")
        return value

    with pytest.raises(cache.FileChangedError):
        cache._read(source, "sha256", mutate)
    assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()


@pytest.mark.parametrize("major,offset,length", [(2, 24, 60), (3, 40, 76)])
@pytest.mark.parametrize("usn", [0, -1, 123456])
def test_file_journal_record_versions(major, offset, length, usn):
    data = bytearray(length)
    struct.pack_into("<IHH", data, 0, length, major, 0)
    struct.pack_into("<q", data, offset, usn)
    assert cache._usn_from_record(data) == (usn if usn > 0 else None)


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"short",
        struct.pack("<IHH", 60, 2, 0),
        bytes(80),
        struct.pack("<IHH", 80, 4, 0) + bytes(72),
        struct.pack("<IHH", 60, 2, 1) + bytes(52),
    ],
)
def test_invalid_file_journal_records_disable_reuse(data):
    assert cache._usn_from_record(data) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows API fallback")
def test_missing_file_journal_disables_windows_cache_reuse(tmp_path, monkeypatch):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    monkeypatch.setattr(cache, "_windows_usn", lambda handle: None)
    with source.open("rb") as handle:
        assert cache._windows_metadata(handle) is None
    cache.file_digest(source)
    changed(source, b"new bytes")
    assert cache.file_digest(source) == hashlib.sha256(b"new bytes").hexdigest()


@pytest.mark.skipif(os.name != "nt", reason="Windows API fallback")
@pytest.mark.parametrize("failure", ["unavailable", "unsupported", "oversized"])
def test_file_journal_query_failure_disables_reuse(tmp_path, monkeypatch, failure):
    source = tmp_path / "media"
    source.write_bytes(b"generated")
    if failure == "unavailable":

        def unavailable():
            raise OSError("journal unavailable")

        monkeypatch.setattr(cache, "_windows_usn_api", unavailable)
    else:
        ctypes, dword, _ = cache._windows_usn_api()

        def query(*args):
            if failure == "oversized":
                ctypes.cast(args[6], ctypes.POINTER(dword)).contents.value = 4097
                return True
            return False

        monkeypatch.setattr(cache, "_windows_usn_api", lambda: (ctypes, dword, query))
    with source.open("rb") as handle:
        assert cache._windows_usn(handle) is None


def test_concurrent_readers_remain_correct_and_cache_storage_stays_bounded(tmp_path):
    paths = []
    for index in range(24):
        path = tmp_path / str(index)
        path.write_bytes(str(index).encode())
        paths.append(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(cache.file_digest, paths * 3))
    assert results == [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths * 3]
    assert all(len(entries) <= 16 for entries in cache._CACHES.values())


def test_invalid_json_is_not_cached_and_missing_files_still_fail(tmp_path):
    source = tmp_path / "timestamps.json"
    source.write_bytes(b"invalid")
    with pytest.raises(ValueError):
        cache.timestamp_tuple(source)
    source.write_bytes(b"[0,0.1]")
    assert cache.timestamp_tuple(source) == (0, 0.1)
    source.unlink()
    with pytest.raises(FileNotFoundError):
        cache.timestamp_tuple(source)
