"""Prepare native dependencies only on disposable Ubuntu GitHub Actions runners."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

ARCHIVE = "https://archive.ubuntu.com/ubuntu/"
KEYRING = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
MIRRORS = {
    "http://azure.archive.ubuntu.com/ubuntu",
    "https://azure.archive.ubuntu.com/ubuntu",
    "mirror+file:/etc/apt/apt-mirrors.txt",
}
OFFICIAL = {
    "http://archive.ubuntu.com/ubuntu",
    "https://archive.ubuntu.com/ubuntu",
    "http://security.ubuntu.com/ubuntu",
    "https://security.ubuntu.com/ubuntu",
}
LIBRARIES = {"libgl1": "libGL.so.1", "libglib2.0-0": "libglib-2.0.so.0"}
SUPPORTED_SUITES = {"22.04": "jammy", "24.04": "noble", "26.04": "resolute"}


def route_source(text: str, *, deb822: bool, suite: str) -> tuple[str, int]:
    """Replace recognized Ubuntu transport URIs, leaving signing/suites intact."""
    recognized = 0
    if suite not in SUPPORTED_SUITES.values():
        raise ValueError("Unsupported Ubuntu suite")
    allowed_suites = {
        suite,
        suite + "-updates",
        suite + "-security",
        suite + "-backports",
    }

    def stanza(block: str) -> str:
        nonlocal recognized
        fields = list(re.finditer(r"(?im)^URIs:[^\n]*(?:\n[ \t]+[^\n]+)*", block))
        if not fields:
            return block
        if len(fields) != 1:
            raise ValueError("Duplicate URIs fields are unsupported")
        field = fields[0]
        uris = field.group().partition(":")[2].split()
        if not any(uri.rstrip("/") in MIRRORS | OFFICIAL for uri in uris):
            return block
        if any(uri.rstrip("/") not in MIRRORS | OFFICIAL for uri in uris):
            raise ValueError("Mixed Ubuntu and unsupported archive URIs")
        suites = re.findall(r"(?im)^Suites:[ \t]*([^\r\n]+)", block)
        if (
            len(suites) != 1
            or not suites[0].split()
            or not set(suites[0].split()) <= allowed_suites
        ):
            raise ValueError("Ubuntu source suites do not match this runner")
        signed = re.findall(r"(?im)^Signed-By:[ \t]*([^\r\n]+)", block)
        if signed != [KEYRING]:
            raise ValueError("Ubuntu archive must retain its existing keyring")
        if re.search(
            r"(?im)^(?:Trusted|Allow-Insecure|Allow-Weak|Allow-Downgrade-To-Insecure):[ \t]*yes\b",
            block,
        ):
            raise ValueError("Insecure Ubuntu source options are forbidden")
        recognized += 1
        new = re.sub(
            r"\S+",
            lambda match: (
                ARCHIVE if match.group().rstrip("/") in MIRRORS else match.group()
            ),
            field.group(),
        )
        return block[: field.start()] + new + block[field.end() :]

    if deb822:
        parts = re.split(r"(\n[ \t]*\n)", text)
        return "".join(
            stanza(part) if i % 2 == 0 else part for i, part in enumerate(parts)
        ), recognized

    lines = []
    for line in text.splitlines(keepends=True):
        entry = re.match(
            r"^([ \t]*deb(?:-src)?[ \t]+(?:\[[^\]\r\n]*\][ \t]+)?)(\S+)",
            line,
        )
        if entry and entry[2].rstrip("/") in MIRRORS | OFFICIAL:
            remainder = line[entry.end() :].split()
            if not remainder or remainder[0] not in allowed_suites:
                raise ValueError("Ubuntu source suites do not match this runner")
            if f"signed-by={KEYRING}" not in entry[1].split():
                # The option may be immediately before the closing bracket.
                options = entry[1].replace("[", " ").replace("]", " ").split()
                if f"signed-by={KEYRING}" not in options:
                    raise ValueError("Ubuntu archive must retain its existing keyring")
            if re.search(
                r"\b(?:trusted|allow-insecure|allow-weak)=yes\b", entry[1], re.I
            ):
                raise ValueError("Insecure Ubuntu source options are forbidden")
            recognized += 1
            if entry[2].rstrip("/") in MIRRORS:
                line = line[: entry.start(2)] + ARCHIVE + line[entry.end(2) :]
        lines.append(line)
    return "".join(lines), recognized


def route_archives(apt_root: Path, suite: str) -> list[dict]:
    """Validate every candidate before writing; never rewrite third-party sources."""
    paths = [apt_root / "sources.list"]
    parts = apt_root / "sources.list.d"
    paths.extend(sorted(parts.glob("*.list")))
    paths.extend(sorted(parts.glob("*.sources")))
    changes = []
    recognized = 0
    for path in paths:
        if not path.exists():
            continue
        original = path.read_bytes()
        if len(original) > 256 * 1024:
            raise ValueError("Unexpectedly large APT source configuration")
        updated, count = route_source(
            original.decode("utf-8"), deb822=path.suffix == ".sources", suite=suite
        )
        recognized += count
        raw = updated.encode("utf-8")
        if raw != original:
            if path.is_symlink() or not path.is_file():
                raise ValueError("Refusing to rewrite an indirect APT source")
            changes.append((path, original, raw))
    if not recognized:
        raise ValueError("No supported signed Ubuntu archive source found")
    for path, _original, raw in changes:
        path.write_bytes(raw)
    return [
        {
            "path": str(path),
            "before_sha256": hashlib.sha256(old).hexdigest(),
            "after_sha256": hashlib.sha256(new).hexdigest(),
        }
        for path, old, new in changes
    ]


def missing_packages(profile: str) -> list[str]:
    missing = []
    if profile in {"python", "browser"}:
        available = True
        for tool in ("ffmpeg", "ffprobe"):
            executable = shutil.which(tool)
            if executable is None:
                available = False
                continue
            try:
                result = subprocess.run(
                    [executable, "-version"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                available &= result.stdout.startswith(tool + " version ")
            except (OSError, subprocess.SubprocessError):
                available = False
        if not available:
            missing.append("ffmpeg")
    if profile in {"python", "package"}:
        for package, soname in LIBRARIES.items():
            try:
                ctypes.CDLL(soname)
            except OSError:
                missing.append(package)
    return missing


def prepare(profile: str, suite: str, apt_root: Path = Path("/etc/apt")) -> dict:
    if profile not in {"python", "package", "browser"}:
        raise ValueError("Unsupported dependency profile")
    changes = route_archives(apt_root, suite)
    missing = missing_packages(profile)
    print(
        json.dumps(
            {
                "profile": profile,
                "archive_changes": changes,
                "missing_packages": missing,
            }
        ),
        flush=True,
    )
    if missing:
        subprocess.run(["apt-get", "update"], check=True)
        subprocess.run(
            ["apt-get", "install", "--no-install-recommends", "-y", *missing],
            check=True,
        )
    remaining = missing_packages(profile)
    if remaining:
        raise RuntimeError(
            "Native dependencies unavailable after bootstrap: " + ", ".join(remaining)
        )
    return {
        "profile": profile,
        "installed_packages": missing,
        "native_probes_passed": True,
        "archive_changes": changes,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile", choices=("python", "package", "browser"), required=True
    )
    args = parser.parse_args()
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_OS") != "Linux"
        or platform.system() != "Linux"
        or platform.machine() != "x86_64"
        or platform.freedesktop_os_release().get("ID") != "ubuntu"
    ):
        raise SystemExit("Bootstrap requires a disposable Ubuntu x86_64 Actions runner")
    release = platform.freedesktop_os_release()
    suite = SUPPORTED_SUITES.get(release.get("VERSION_ID"))
    if suite is None or release.get("VERSION_CODENAME") != suite:
        raise SystemExit("Unsupported Ubuntu release")
    print(json.dumps(prepare(args.profile, suite)), flush=True)


if __name__ == "__main__":
    main()
