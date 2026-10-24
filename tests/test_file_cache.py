"""Generated files exercise observable replacement, edits and concurrent reads."""

import hashlib
import os
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
    with patch.object(cache, "_hash", wraps=cache._hash) as hashed:
        first = cache.file_digest(source)
        assert cache.file_digest(source) == first
        assert hashed.call_count == 1
    with patch.object(cache, "_timestamps", wraps=cache._timestamps) as parsed:
        assert cache.timestamp_tuple(source) == cache.timestamp_tuple(source)
        assert parsed.call_count == 1


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
        assert hashed.call_count == 3


@pytest.mark.skipif(os.name != "nt", reason="Real Windows file-handle metadata")
def test_actual_windows_change_time_observes_in_place_timestamp_restoration(tmp_path):
    source = tmp_path / "media"
    source.write_bytes(b"old bytes")
    before = source.stat()
    with source.open("rb") as handle:
        first = cache._windows_metadata(handle)
    changed(source, b"new bytes")
    with source.open("rb") as handle:
        second = cache._windows_metadata(handle)
    assert first is not None and second is not None and first[2] != second[2]
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
    original = Path.stat

    def substituted(path, *args, **kwargs):
        info = original(path, *args, **kwargs)
        if path == source:
            return SimpleNamespace(
                st_dev=info.st_dev,
                st_ino=info.st_ino + 1,
                st_size=info.st_size,
                st_mtime_ns=info.st_mtime_ns,
                st_ctime_ns=info.st_ctime_ns,
            )
        return info

    monkeypatch.setattr(Path, "stat", substituted)
    with pytest.raises(cache.FileChangedError):
        cache.file_digest(source)


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
