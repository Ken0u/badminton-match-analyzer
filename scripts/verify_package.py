"""Build and verify distributions against tracked package bytes and a fresh install."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


def package_sources(root: Path) -> dict[str, bytes]:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "backend/badminton"], cwd=root
        )
        .decode()
        .split("\0")
    )
    return {
        Path(name).relative_to("backend").as_posix(): (root / name).read_bytes()
        for name in names
        if name
    }


def verify_archives(root: Path, wheel: Path, sdist: Path) -> dict:
    expected = package_sources(root)
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe wheel member")
            if not name.startswith("badminton/") and not (
                path.parts
                and path.parts[0].startswith("badminton_match_analyzer-")
                and path.parts[0].endswith(".dist-info")
            ):
                raise ValueError(f"Unexpected wheel content: {name}")
        actual = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.startswith("badminton/") and not name.endswith("/")
        }
    if actual != expected:
        missing = sorted(expected.keys() - actual.keys())
        extra = sorted(actual.keys() - expected.keys())
        changed = sorted(
            name
            for name in expected.keys() & actual.keys()
            if expected[name] != actual[name]
        )
        raise ValueError(
            f"Wheel package mismatch: missing={missing}, extra={extra}, changed={changed}"
        )
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe source distribution member")
        source = {}
        required = {"uv.lock", "pyproject.toml", ".python-version", ".node-version"}
        verified = set()
        for member in members:
            relative = PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix()
            if relative in required and member.isfile():
                stream = archive.extractfile(member)
                assert stream is not None
                if stream.read() != (root / relative).read_bytes():
                    raise ValueError(
                        f"Source distribution metadata differs: {relative}"
                    )
                verified.add(relative)
            parts = PurePosixPath(relative).parts
            if any(
                part in {".cache", ".env", ".media", ".aws", ".codex"} for part in parts
            ):
                raise ValueError("Private state in source distribution")
            if PurePosixPath(relative).suffix.lower() in {
                ".mp4",
                ".mkv",
                ".mov",
                ".avi",
                ".webm",
            }:
                raise ValueError("Raw media in source distribution")
            if member.isfile() and relative.startswith("backend/badminton/"):
                stream = archive.extractfile(member)
                assert stream is not None
                source[relative.removeprefix("backend/")] = stream.read()
        if verified != required:
            raise ValueError("Source distribution missing reproducibility files")
    if source != expected:
        raise ValueError(
            "Source distribution package bytes differ from tracked sources"
        )
    return {
        "package_files": len(expected),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "sdist_sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
    }


def verify_installed(root: Path, wheel: Path, uv: str) -> None:
    cache = root / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="package-check-", dir=cache) as directory:
        scratch = Path(directory)
        environment = scratch / "venv"
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.update(
            UV_PROJECT_ENVIRONMENT=str(environment),
            UV_CACHE_DIR=str(cache / "uv"),
            BADMINTON_ROOT=str(scratch),
            BADMINTON_DATA_DIR=str(scratch / "state"),
            BADMINTON_WEIGHTS_DIR=str(scratch / "weights"),
        )
        subprocess.run(
            [
                uv,
                "sync",
                "--locked",
                "--no-dev",
                "--no-install-project",
                "--python",
                sys.executable,
                "--extra",
                "youtube",
                "--extra",
                "download",
            ],
            cwd=root,
            env=env,
            check=True,
        )
        subprocess.run(
            [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
            cwd=scratch,
            env=env,
            check=True,
        )
        subprocess.run(
            [uv, "pip", "check", "--python", str(python)],
            cwd=scratch,
            env=env,
            check=True,
        )
        installed = subprocess.check_output(
            [
                str(python),
                "-c",
                "import badminton; print(next(iter(badminton.__path__)))",
            ],
            cwd=scratch,
            env=env,
            text=True,
        ).strip()
        installed_path = Path(installed)
        if not installed_path.is_relative_to(environment):
            raise ValueError("Package import escaped the clean environment")
        for name, content in package_sources(root).items():
            if (installed_path.parent / name).read_bytes() != content:
                raise ValueError(f"Installed bytes differ: {name}")
        subprocess.run(
            [str(python), "-m", "badminton.cli", "--help"],
            cwd=scratch,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path(".cache/dist"))
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--uv", default="uv")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    dist = args.dist_dir.resolve()
    if args.build:
        dist.mkdir(parents=True, exist_ok=True)
        subprocess.run([args.uv, "build", "--out-dir", str(dist)], cwd=root, check=True)
    wheels = list(dist.glob("*.whl"))
    sources = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        parser.error(
            "Use a directory containing exactly one wheel and one source distribution"
        )
    receipt = verify_archives(root, wheels[0], sources[0])
    verify_installed(root, wheels[0], args.uv)
    print(json.dumps({"ok": True, **receipt}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
