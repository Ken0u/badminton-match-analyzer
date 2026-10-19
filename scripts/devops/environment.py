"""Read-only workstation checks and guarded disposable-worktree setup.

This module never imports application configuration or touches application state.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

UV_VERSION = "0.9.4"
PROFILES = {
    "review": ("dev", "youtube", "download"),
    "cpu": ("dev", "youtube", "download", "tracking", "recognition", "cpu"),
    "cuda": ("dev", "youtube", "download", "tracking", "recognition", "cuda"),
}


def probe(command: list[str], cwd: Path) -> dict:
    """Return status only for auth probes; never persist credential-bearing output."""
    try:
        executable = shutil.which(command[0])
        if executable is None:
            return {"available": False, "ok": False}
        command = [executable, *command[1:]]
        result = subprocess.run(
            command, cwd=cwd, capture_output=True, text=True, timeout=20, check=False
        )
        return {"available": True, "ok": result.returncode == 0}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "ok": False}


def doctor(profile: str, root: Path | None = None) -> dict:
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    root = (root or Path(__file__).resolve().parents[2]).resolve()
    tools = {
        name: probe([name, "--version"], root)
        for name in ("git", "uv", "node", "npm", "ffmpeg", "ffprobe", "gh", "codex")
    }
    auth = {
        "github": probe(["gh", "auth", "status"], root),
        "codex": probe(["codex", "login", "status"], root),
    }
    supported = profile != "cuda" or (
        sys.platform in {"linux", "win32"}
        and platform.machine().lower() in {"x86_64", "amd64"}
    )
    return {
        "root": str(root),
        "profile": profile,
        "platform": sys.platform,
        "machine": platform.machine(),
        "python": platform.python_version(),
        "python_default": (root / ".python-version").read_text().strip(),
        "profile_supported": supported,
        "tools": tools,
        "auth": auth,
        "lock_present": (root / "uv.lock").is_file(),
        "free_bytes": shutil.disk_usage(root).free,
        "ok": supported
        and (root / "uv.lock").is_file()
        and all(value["ok"] for key, value in tools.items() if key != "codex")
        and auth["github"]["ok"],
        "codex_cli_optional": True,
        "limits": [
            "No model/data downloads or inference performed",
            "No app, worker or process restart performed",
            "GPU driver and model availability require separate runtime checks",
        ],
    }


def bootstrap(profile: str, root: Path, python: str = "3.12") -> None:
    """Install only a bootstrap-owned environment in a linked Git worktree."""
    if profile not in PROFILES:
        raise ValueError(f"Unknown profile: {profile}")
    root = root.resolve()
    if not (root / ".git").is_file():
        raise ValueError("Install requires a dedicated linked Git worktree")
    if profile == "cuda" and (
        sys.platform not in {"linux", "win32"}
        or platform.machine().lower() not in {"x86_64", "amd64"}
    ):
        raise ValueError("CUDA profile requires x86-64 Linux or Windows")
    if python not in {"3.10", "3.12"}:
        raise ValueError("Supported Python versions: 3.10, 3.12")
    uv = shutil.which("uv")
    if uv is None:
        raise ValueError(f"Install uv=={UV_VERSION} before bootstrap")
    version = subprocess.check_output([uv, "--version"], text=True).split()[1]
    if version != UV_VERSION:
        raise ValueError(f"Expected uv {UV_VERSION}, found {version}")
    env_path = root / ".venv"
    marker = root / ".cache" / "bootstrap-environment.json"
    identity = {"root": str(root), "python": python, "profile": profile}
    if env_path.is_symlink():
        raise ValueError("Refusing a symlinked environment")
    if (root / ".cache").is_symlink():
        raise ValueError("Refusing a symlinked cache")
    if env_path.exists():
        if not marker.is_file() or json.loads(marker.read_text()) != identity:
            raise ValueError(
                "Refusing to sync an existing or differently configured environment"
            )
        executable = env_path / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        actual = subprocess.check_output(
            [
                str(executable),
                "-c",
                "import sys; print('%d.%d' % sys.version_info[:2])",
            ],
            text=True,
        ).strip()
        if actual != python:
            raise ValueError("Existing Python does not match; create another worktree")
        # Even a matching owned environment may have an active application. Never sync it.
        raise ValueError(
            "Environment already initialized; use --check or create another worktree"
        )
    cache = root / ".cache"
    cache.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.update(
        UV_PROJECT_ENVIRONMENT=str(env_path),
        UV_CACHE_DIR=str(cache / "uv"),
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(cache / "bootstrap-state"),
    )
    command = [uv, "sync", "--locked", "--python", python]
    for extra in PROFILES[profile]:
        command.extend(("--extra", extra))
    subprocess.run(command, cwd=root, env=env, check=True)
    npm = shutil.which("npm")
    if npm is None:
        raise ValueError("Install the pinned Node/npm runtime before bootstrap")
    subprocess.run([npm, "ci"], cwd=root, env=env, check=True)
    marker.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
