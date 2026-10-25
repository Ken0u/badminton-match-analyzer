"""Build and verify distributions against tracked package bytes and a fresh install."""

from __future__ import annotations

import argparse
import base64
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import secrets
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath


def safe_relative(name: str) -> bool:
    return (
        isinstance(name, str)
        and bool(name)
        and "\\" not in name
        and ":" not in name
        and not PurePosixPath(name).is_absolute()
        and all(part not in {"", ".", ".."} for part in name.split("/"))
    )


def frontend_assets(root: Path) -> dict[str, bytes]:
    """Validate the staged build without Node or a frontend runtime dependency."""
    static = root / "backend/badminton/static"
    manifest_bytes = (static / "build-manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if set(manifest) != {"schema_version", "input_fingerprint", "inputs", "assets"}:
        raise ValueError("Unexpected frontend manifest fields")
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise ValueError("Unsupported frontend manifest schema")
    for section in ("inputs", "assets"):
        values = manifest[section]
        if not isinstance(values, dict) or not values:
            raise ValueError(f"Missing frontend {section}")
        for name, digest in values.items():
            if (
                not safe_relative(name)
                or not isinstance(digest, str)
                or not re.fullmatch("[0-9a-f]{64}", digest)
            ):
                raise ValueError(f"Invalid frontend {section} entry")
    inputs = manifest["inputs"]
    input_names = {".node-version", "package-lock.json"} | {
        f"backend/frontend/{name}"
        for name in (
            "index.html",
            "package.json",
            "tsconfig.json",
            "tsconfig.test.json",
            "vite.config.js",
        )
    }
    for directory in ("scripts", "src"):
        for source in (root / "backend/frontend" / directory).rglob("*"):
            if source.is_symlink():
                raise ValueError("Symlink in frontend build inputs")
            if source.is_file():
                input_names.add(source.relative_to(root).as_posix())
    if inputs.keys() != input_names:
        raise ValueError("Frontend build input file set differs")
    for name, digest in inputs.items():
        if name not in {".node-version", "package-lock.json"} and not name.startswith(
            "backend/frontend/"
        ):
            raise ValueError("Unexpected frontend build input")
        source = root / name
        if (
            source.is_symlink()
            or hashlib.sha256(source.read_bytes()).hexdigest() != digest
        ):
            raise ValueError(f"Frontend build input differs: {name}")
    fingerprint = hashlib.sha256(
        "".join(f"{name}\0{inputs[name]}\n" for name in sorted(inputs)).encode()
    ).hexdigest()
    if manifest["input_fingerprint"] != f"sha256:{fingerprint}":
        raise ValueError("Frontend input fingerprint differs")
    assets = manifest["assets"]
    if not {"index.html", "app.js", "style.css"} <= assets.keys():
        raise ValueError("Missing production frontend entry points")
    for name in assets:
        if (
            name == "build-manifest.json"
            or any(
                part in {"src", "scripts", "tests", "node_modules"}
                for part in name.split("/")
            )
            or PurePosixPath(name).suffix.lower()
            in {".map", ".ts", ".tsx", ".jsx", ".md", ".json"}
            or any(part.startswith(".") for part in name.split("/"))
        ):
            raise ValueError(f"Source or tooling in runtime frontend: {name}")
    actual = {}
    for path in static.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink in runtime frontend")
        if path.is_file():
            actual[path.relative_to(static).as_posix()] = path.read_bytes()
    if actual.keys() != assets.keys() | {"build-manifest.json"}:
        raise ValueError("Runtime frontend file set differs from manifest")
    for name, digest in assets.items():
        if hashlib.sha256(actual[name]).hexdigest() != digest:
            raise ValueError(f"Frontend asset hash differs: {name}")
    return actual


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def loopback_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    try:
        local = (
            parsed.hostname == "localhost"
            or ipaddress.ip_address(parsed.hostname or "").is_loopback
        )
        valid_port = parsed.port is None or 0 < parsed.port < 65536
    except ValueError:
        local = valid_port = False
    if (
        parsed.scheme != "http"
        or not local
        or not valid_port
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("HTTP verification requires a credential-free loopback origin")
    return value.rstrip("/")


def verify_http(root: Path, url: str, username: str, password: str) -> dict:
    origin = loopback_url(url)
    if not username or ":" in username or not password:
        raise ValueError("HTTP verification requires a username and password")
    assets = frontend_assets(root)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    credential = base64.b64encode(f"{username}:{password}".encode()).decode()

    def get(path, status, authenticated=True):
        headers = {"Authorization": f"Basic {credential}"} if authenticated else {}
        request = urllib.request.Request(origin + path, headers=headers)
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            body = response.read()
            if response.status != status:
                raise ValueError(
                    f"HTTP status differs for {path}: {response.status} != {status}"
                )
            return body, response.headers

    body, _ = get("/api/health", 200, authenticated=False)
    if json.loads(body) != {"status": "ok"}:
        raise ValueError("Unexpected health response")
    protected = ["/", "/library", "/editor", "/api/videos"] + [
        "/" + urllib.parse.quote(name, safe="/") for name in assets
    ]
    for path in protected:
        _, headers = get(path, 401, authenticated=False)
        if not headers.get("WWW-Authenticate", "").lower().startswith("basic "):
            raise ValueError(f"Missing HTTP authentication challenge: {path}")
    body, _ = get("/api/videos", 200)
    if json.loads(body) != []:
        raise ValueError(
            "HTTP delivery verification requires an empty disposable catalog"
        )
    for path in ("/", "/library", "/editor"):
        body, headers = get(path, 200)
        if body != assets["index.html"] or headers.get_content_type() != "text/html":
            raise ValueError(f"Production SPA bytes or MIME differ: {path}")
        if "no-cache" not in headers.get("Cache-Control", ""):
            raise ValueError(f"SPA response is missing revalidation: {path}")
    for name, expected in assets.items():
        body, headers = get("/" + urllib.parse.quote(name, safe="/"), 200)
        if body != expected:
            raise ValueError(f"Served frontend bytes differ: {name}")
        mime = headers.get_content_type()
        expected_mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
        if mime != expected_mime and not (
            name.endswith(".js")
            and mime in {"text/javascript", "application/javascript"}
        ):
            raise ValueError(f"Served frontend MIME differs: {name}")
        if name in {
            "index.html",
            "app.js",
            "style.css",
            "build-manifest.json",
        } and "no-cache" not in headers.get("Cache-Control", ""):
            raise ValueError(f"Frontend entry point is missing revalidation: {name}")
    for path in (
        "/api/package-verification-missing",
        "/api/videos/package-verification-missing",
        "/package-verification-missing",
        "/assets/package-verification-missing.js",
        "/src/main.tsx",
        "/backend/frontend/package.json",
        "/node_modules/react/package.json",
        "/.env",
        "/.cache/private",
        "/app.js.map",
        "/editor/package-verification-missing",
    ):
        get(path, 404)
        get(path, 401, authenticated=False)
    return {
        "http_assets": len(assets),
        "http_spa_routes": 3,
        "http_authentication": True,
    }


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


def public_manifest_sources(root: Path) -> dict[str, bytes]:
    """Read only tracked public JSON files; never discover local data by glob."""
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", "data/manifests"], cwd=root
        )
        .decode("utf-8")
        .split("\0")
    )
    result = {}
    for name in names:
        if not name or PurePosixPath(name).suffix != ".json":
            continue
        parts = PurePosixPath(name).parts
        if (
            not safe_relative(name)
            or len(parts) != 3
            or parts[:2] != ("data", "manifests")
            or name in result
        ):
            raise ValueError("Invalid tracked public manifest path")
        source = root / name
        for item in (root / "data", source.parent, source):
            try:
                info = item.lstat()
            except FileNotFoundError as error:
                raise ValueError("Tracked public manifest is missing") from error
            if stat.S_ISLNK(info.st_mode) or (
                getattr(info, "st_file_attributes", 0)
                & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            ):
                raise ValueError("Symlink or reparse point in tracked public manifests")
            if not (
                stat.S_ISREG(info.st_mode)
                if item == source
                else stat.S_ISDIR(info.st_mode)
            ):
                raise ValueError("Tracked public manifest path is not ordinary")
        result[name] = source.read_bytes()
    if not result:
        raise ValueError("No tracked public manifests to verify")
    return result


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
                not safe_relative(member.name.rstrip("/"))
                or path.is_absolute()
                or ".." in path.parts
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsafe source distribution member")
        public = public_manifest_sources(root)
        public_seen = set()
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
            if parts and parts[0] == "data":
                if member.isdir() and relative in {"data", "data/manifests"}:
                    continue
                if not member.isfile() or relative not in public:
                    raise ValueError("Unexpected data in source distribution")
                if relative in public_seen:
                    raise ValueError("Duplicate public manifest in source distribution")
                stream = archive.extractfile(member)
                assert stream is not None
                if (
                    member.size != len(public[relative])
                    or stream.read(len(public[relative]) + 1) != public[relative]
                ):
                    raise ValueError("Source distribution public manifest bytes differ")
                public_seen.add(relative)
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
        if public_seen != public.keys():
            raise ValueError("Source distribution missing tracked public manifests")
    if source != expected:
        raise ValueError(
            "Source distribution package bytes differ from tracked sources"
        )
    assets = frontend_assets(root)
    return {
        "package_files": len(expected),
        "frontend_files": len(assets),
        "public_manifest_files": len(public),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "sdist_sha256": hashlib.sha256(sdist.read_bytes()).hexdigest(),
    }


def process_identity(process) -> dict:
    return {
        "pid": process.pid,
        "created": process.create_time(),
        "cwd": process.cwd(),
        "command": process.cmdline(),
    }


def verify_installed_http(root: Path, python: Path, scratch: Path, env: dict) -> dict:
    """Serve only a newly installed wheel, preserving an owned-process receipt."""
    # URL-only container checks run with the host's standard library. Process
    # ownership needs psutil only when this verifier launches its own fixture.
    import psutil

    token = secrets.token_hex(8)
    evidence = root / ".cache/package-http" / token
    evidence.mkdir(parents=True)
    port_file = scratch / "http-port.json"
    username, password = "package-reviewer", secrets.token_urlsafe(24)
    env = {**env, "BADMINTON_USERNAME": username, "BADMINTON_PASSWORD": password}
    launcher = (
        "import json, socket, sys; from pathlib import Path; import uvicorn; "
        "from badminton.api import create_app; "
        "app = create_app(); server = socket.socket(); "
        "server.bind(('127.0.0.1', 0)); server.listen(128); "
        "Path(sys.argv[1]).write_text(json.dumps({'port': server.getsockname()[1]})); "
        "uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False))"
        ".run(sockets=[server])"
    )
    command = [str(python), "-c", launcher, str(port_file)]
    receipt = {"cwd": str(scratch), "command": command, "status": "starting"}
    receipt_path = evidence / "process.json"
    identity = None
    with (evidence / "server.log").open("wb") as log:
        process = subprocess.Popen(
            command, cwd=scratch, env=env, stdout=log, stderr=log
        )
        try:
            identity = process_identity(psutil.Process(process.pid))
            if (
                identity["command"][1:] != command[1:]
                or Path(identity["cwd"]).resolve() != scratch.resolve()
            ):
                raise ValueError("Installed HTTP fixture process identity differs")
            receipt.update(identity, status="running")
            receipt["initial_identity"] = identity
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
            deadline = time.monotonic() + 45
            while not port_file.exists():
                if process.poll() is not None:
                    raise ValueError("Installed HTTP fixture exited during startup")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Installed HTTP fixture startup timed out")
                time.sleep(0.1)
            port = json.loads(port_file.read_text())["port"]
            # The socket is bound before the file is written. Wait for ASGI startup.
            probe = urllib.request.build_opener(
                urllib.request.ProxyHandler({}), NoRedirect()
            )
            while True:
                try:
                    with probe.open(
                        f"http://127.0.0.1:{port}/api/health", timeout=1
                    ) as response:
                        if response.status == 200:
                            break
                except (OSError, urllib.error.URLError):
                    pass
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise TimeoutError("Installed HTTP fixture did not become healthy")
                time.sleep(0.1)
            # macOS framework Python may rewrite argv[0] while initializing.
            # Capture the settled command after application startup, retaining
            # the spawned PID/lifetime/cwd and exact launcher arguments fence.
            settled = process_identity(psutil.Process(process.pid))
            if (
                any(settled[key] != identity[key] for key in ("pid", "created", "cwd"))
                or settled["command"][1:] != command[1:]
            ):
                raise ValueError("Installed HTTP fixture startup identity changed")
            identity = settled
            receipt.update(identity)
            result = verify_http(root, f"http://127.0.0.1:{port}", username, password)
            receipt.update(result, status="verified", port=port)
            return result
        finally:
            if receipt["status"] != "verified":
                receipt["status"] = "failed"
            if process.poll() is None:
                current = process_identity(psutil.Process(process.pid))
                if identity is None or current != identity:
                    receipt["cleanup"] = "refused: process identity differs"
                    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
                    raise ValueError("Refusing to stop an unverified HTTP fixture")
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    if process_identity(psutil.Process(process.pid)) != identity:
                        raise ValueError(
                            "Refusing to kill a changed HTTP fixture"
                        ) from None
                    process.kill()
                    process.wait(timeout=10)
            receipt.update(exit_code=process.returncode, cleanup="owned process exited")
            receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")


def verify_installed(root: Path, wheel: Path, uv: str) -> dict:
    cache = root / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="badminton-package-check-") as directory:
        scratch = Path(directory).resolve()
        environment = scratch / "venv"
        python = environment / (
            "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        for name in list(env):
            if name.startswith("BADMINTON_"):
                del env[name]
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
        installed_path = Path(installed).resolve()
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
        return verify_installed_http(root, python, scratch, env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, default=Path(".cache/dist"))
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--uv", default="uv")
    parser.add_argument(
        "--url", help="Verify an already running disposable loopback server"
    )
    parser.add_argument("--username", default="reviewer")
    parser.add_argument("--password-env", default="BADMINTON_VERIFY_PASSWORD")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.url:
        if args.build:
            parser.error("--url cannot be combined with --build")
        password = os.environ.get(args.password_env, "")
        if not password:
            parser.error(
                "The configured verification password environment variable is empty"
            )
        receipt = verify_http(root, args.url, args.username, password)
        print(json.dumps({"ok": True, **receipt}, indent=2))
        return 0
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
    receipt.update(verify_installed(root, wheels[0], args.uv))
    print(json.dumps({"ok": True, **receipt}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
