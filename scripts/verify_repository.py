"""Check tracked text, JSON, local documentation links and obvious credentials."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

BINARY_SUFFIXES = {
    ".pt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".woff",
    ".woff2",
}
SECRET_PATTERNS = [
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{50,}\b"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE " + r"KEY-----"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{40,}\b"),
]
LINK = re.compile(r"!?\[[^\]\n]*\]\(([^\n)]+)\)")


def check_file(path: Path, root: Path) -> list[str]:
    relative = path.relative_to(root).as_posix()
    if path.suffix.lower() in BINARY_SUFFIXES:
        return []
    errors = []
    raw = path.read_bytes()
    if b"\x00" in raw:
        return [f"{relative}: unrecognized binary file (declare its type explicitly)"]
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{relative}: text must be UTF-8"]
    if b"\r" in raw:
        errors.append(f"{relative}: text must use LF endings")
    if content.startswith("\ufeff"):
        errors.append(f"{relative}: remove UTF-8 BOM")
    if path.suffix == ".json":
        try:
            json.loads(
                content,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
        except ValueError:
            errors.append(f"{relative}: invalid strict JSON")
    if any(pattern.search(content) for pattern in SECRET_PATTERNS):
        errors.append(f"{relative}: credential-like material detected; inspect locally")
    if path.suffix.lower() == ".md":
        # Fenced examples are prose examples rather than actual document navigation.
        markdown = re.sub(r"```.*?```", "", content, flags=re.DOTALL)
        for match in LINK.finditer(markdown):
            target = match[1].strip()
            target = (
                target[1 : target.index(">")]
                if target.startswith("<") and ">" in target
                else target.split(' "', 1)[0]
            )
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            decoded = unquote(parsed.path)
            # Historical local experiment receipts are intentionally unavailable in clones.
            if ".cache" in Path(decoded).parts:
                continue
            destination = (
                root / decoded.lstrip("/")
                if decoded.startswith("/")
                else path.parent / decoded
            ).resolve()
            if not destination.is_relative_to(root) or not destination.exists():
                errors.append(f"{relative}: missing local link {decoded}")
    return errors


def verify(root: Path) -> list[str]:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).split(b"\0")
    errors = []
    for name in tracked:
        if name:
            path = root / name.decode("utf-8")
            if path.is_file():
                errors.extend(check_file(path, root))
    result = subprocess.run(
        ["git", "diff", "--check"], cwd=root, capture_output=True, text=True
    )
    if result.returncode:
        errors.append("git diff --check failed:\n" + result.stdout + result.stderr)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    args = parser.parse_args()
    errors = verify(args.root.resolve())
    print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())
