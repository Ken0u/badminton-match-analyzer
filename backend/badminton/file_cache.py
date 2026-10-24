"""Bounded reads tied to file identity and observable change metadata.

Filesystem metadata is an invalidation signal, not proof against a writer that
can hide changes from the filesystem. Unsupported change metadata disables
reuse. Every call still checks the opened file and its current pathname.
"""

import hashlib
import json
import os
import stat
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from threading import Lock

_WINDOWS = os.name == "nt"
_LIMIT = 16
_MISSING = object()
_LOCK = Lock()
_CACHES = {"sha256": OrderedDict(), "timestamps": OrderedDict()}


class FileChangedError(ValueError):
    """The requested file changed during a read or cache lookup."""


@lru_cache(maxsize=1)
def _windows_api():
    import ctypes
    from ctypes import wintypes

    class BasicInfo(ctypes.Structure):
        _fields_ = [
            ("creation", ctypes.c_longlong),
            ("access", ctypes.c_longlong),
            ("write", ctypes.c_longlong),
            ("change", ctypes.c_longlong),
            ("attributes", wintypes.DWORD),
        ]

    query = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    return ctypes, BasicInfo, query


def _windows_metadata(handle):
    # Python 3.10 Windows st_ctime describes creation, not the last change.
    # FileBasicInfo (0) supplies the independent ChangeTime from the open handle.
    # https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_basic_info
    try:
        import msvcrt

        ctypes, basic_info, query = _windows_api()
        info = basic_info()
        if (
            not query(
                msvcrt.get_osfhandle(handle.fileno()),
                0,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            or info.change <= 0
        ):
            return None
        # Access time may change just from reading; never include it in the key.
        return info.creation, info.write, info.change, info.attributes
    except (AttributeError, ImportError, OSError):
        return None


def _stat_key(info):
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _observe(handle):
    info = os.fstat(handle.fileno())
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("Cached media inputs must be regular files")
    native = _windows_metadata(handle) if _WINDOWS else None
    reusable = bool(info.st_ino) and (
        native is not None if _WINDOWS else info.st_ctime_ns > 0
    )
    return (_stat_key(info), native), reusable


def _read(path, kind, load):
    path = Path(path).absolute()
    with path.open("rb") as handle:
        before, reusable = _observe(handle)
        key = path, before
        cache = _CACHES[kind]
        value = _MISSING
        if reusable:
            with _LOCK:
                if key in cache:
                    value = cache[key]
                    cache.move_to_end(key)
        if value is _MISSING:
            value = load(handle)
        after, still_reusable = _observe(handle)
        if before != after or _stat_key(path.stat()) != after[0]:
            raise FileChangedError(
                "Media input changed while reading; retry the request"
            )
        if reusable and still_reusable:
            with _LOCK:
                cache[key] = value
                cache.move_to_end(key)
                while len(cache) > _LIMIT:
                    cache.popitem(last=False)
        return value


def _hash(handle):
    digest = hashlib.sha256()
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def file_digest(path):
    """Hash stable bytes, reusing only an observed matching file version."""
    return _read(path, "sha256", _hash)


def _timestamps(handle):
    return tuple(json.loads(handle.read().decode("utf-8")))


def timestamp_tuple(path):
    """Read an immutable source-clock tuple with the same invalidation guards."""
    return _read(path, "timestamps", _timestamps)
