"""Generated bootstrap checks; these do not execute apt on developer machines."""

import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location(
    "ci_linux_dependencies",
    Path(__file__).resolve().parents[1] / "scripts/ci_linux_dependencies.py",
)
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)

SOURCE = """Types: deb
URIs: mirror+file:/etc/apt/apt-mirrors.txt
Suites: noble noble-updates noble-security noble-backports
Components: main restricted universe multiverse
Architectures: amd64
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
"""


def test_route_preserves_security_suite_architecture_and_unrelated_stanza():
    third_party = "Types: deb\nURIs: https://packages.microsoft.com/ubuntu/24.04/prod\nSuites: noble\nComponents: main\nSigned-By: /usr/share/keyrings/microsoft-prod.gpg\n"
    text = SOURCE + "\n" + third_party
    routed, count = bootstrap.route_source(text, deb822=True, suite="noble")
    assert count == 1
    assert routed == text.replace(
        "mirror+file:/etc/apt/apt-mirrors.txt", bootstrap.ARCHIVE
    )
    assert bootstrap.route_source(routed, deb822=True, suite="noble") == (routed, 1)


@pytest.mark.parametrize("uri", sorted(bootstrap.MIRRORS))
def test_legacy_route_keeps_options_and_comments(uri):
    text = f"# preserve\ndeb [arch=amd64 signed-by={bootstrap.KEYRING}] {uri}/ noble-updates main # comment\n"
    routed, count = bootstrap.route_source(text, deb822=False, suite="noble")
    assert count == 1
    assert routed == text.replace(uri + "/", bootstrap.ARCHIVE)


@pytest.mark.parametrize(
    "changed",
    [
        SOURCE.replace(bootstrap.KEYRING, "/tmp/another-key.gpg"),
        SOURCE.replace("Signed-By:", "Missing-Keyring:"),
        SOURCE + "Trusted: yes\n",
        SOURCE + "Allow-Insecure: yes\n",
        SOURCE.replace("noble-updates", "jammy-updates"),
        SOURCE.replace(
            "mirror+file:/etc/apt/apt-mirrors.txt",
            "mirror+file:/etc/apt/apt-mirrors.txt https://example.invalid/ubuntu",
        ),
        SOURCE + "URIs: https://archive.ubuntu.com/ubuntu/\n",
    ],
)
def test_unsafe_or_conflicting_source_fails(changed):
    with pytest.raises(ValueError):
        bootstrap.route_source(changed, deb822=True, suite="noble")


def test_unknown_suite_fails():
    with pytest.raises(ValueError, match="Unsupported Ubuntu suite"):
        bootstrap.route_source(SOURCE, deb822=True, suite="unknown")


def test_all_source_validation_precedes_writes(tmp_path):
    parts = tmp_path / "sources.list.d"
    parts.mkdir()
    good = parts / "a.sources"
    bad = parts / "b.sources"
    good.write_text(SOURCE, encoding="utf-8")
    bad.write_text(SOURCE.replace("noble", "jammy"), encoding="utf-8")
    original = good.read_bytes()
    with pytest.raises(ValueError):
        bootstrap.route_archives(tmp_path, "noble")
    assert good.read_bytes() == original


def test_no_supported_archive_fails_without_touching_third_party(tmp_path):
    path = tmp_path / "sources.list"
    raw = b"deb https://example.invalid/ubuntu noble main\n"
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="No supported signed"):
        bootstrap.route_archives(tmp_path, "noble")
    assert path.read_bytes() == raw


def test_route_actual_files_preserves_other_source_bytes(tmp_path):
    path = tmp_path / "sources.list"
    source = f"deb [signed-by={bootstrap.KEYRING}] http://azure.archive.ubuntu.com/ubuntu noble main\n"
    path.write_text(source, encoding="utf-8")
    parts = tmp_path / "sources.list.d"
    parts.mkdir()
    other = parts / "other.sources"
    other.write_bytes(
        b"Types: deb\nURIs: https://example.invalid/apt\nSuites: stable\n"
    )
    before = other.read_bytes()
    changes = bootstrap.route_archives(tmp_path, "noble")
    assert len(changes) == 1
    assert path.read_text() == source.replace(
        "http://azure.archive.ubuntu.com/ubuntu", bootstrap.ARCHIVE
    )
    assert other.read_bytes() == before
    assert bootstrap.route_archives(tmp_path, "noble") == []


@pytest.fixture
def working_runtime(monkeypatch):
    monkeypatch.setattr(bootstrap.shutil, "which", lambda tool: "/usr/bin/" + tool)
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda command, **kw: SimpleNamespace(
            stdout=Path(command[0]).name + " version fixture\n"
        ),
    )
    monkeypatch.setattr(bootstrap.ctypes, "CDLL", lambda name: object())


@pytest.mark.parametrize("profile", ["python", "browser", "package"])
def test_working_preinstalled_runtime(profile, working_runtime):
    assert bootstrap.missing_packages(profile) == []


def test_missing_ffprobe_requires_ffmpeg_package(working_runtime, monkeypatch):
    monkeypatch.setattr(
        bootstrap.shutil,
        "which",
        lambda tool: None if tool == "ffprobe" else "/usr/bin/ffmpeg",
    )
    assert bootstrap.missing_packages("python") == ["ffmpeg"]


def test_unexpected_tool_output_is_unavailable(working_runtime, monkeypatch):
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="not ffmpeg"),
    )
    assert bootstrap.missing_packages("browser") == ["ffmpeg"]


@pytest.mark.parametrize(
    "failure",
    [
        OSError("unavailable"),
        subprocess.TimeoutExpired("ffmpeg", 15),
        subprocess.CalledProcessError(1, "ffmpeg"),
    ],
)
def test_failed_tool_probe_requires_install(working_runtime, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(bootstrap.subprocess, "run", fail)
    assert bootstrap.missing_packages("browser") == ["ffmpeg"]


def test_unavailable_opencv_libraries_preserve_original_package_names(
    working_runtime, monkeypatch
):
    def fail(name):
        raise OSError(name)

    monkeypatch.setattr(bootstrap.ctypes, "CDLL", fail)
    assert bootstrap.missing_packages("package") == ["libgl1", "libglib2.0-0"]


def test_prepare_installs_only_missing_and_rechecks(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "route_archives", lambda *args: [])
    probes = iter([["ffmpeg"], []])
    monkeypatch.setattr(bootstrap, "missing_packages", lambda profile: next(probes))
    commands = []
    monkeypatch.setattr(
        bootstrap.subprocess,
        "run",
        lambda command, **kw: commands.append((command, kw)),
    )
    result = bootstrap.prepare("python", "noble", tmp_path)
    assert result["installed_packages"] == ["ffmpeg"]
    assert commands == [
        (["apt-get", "update"], {"check": True}),
        (
            ["apt-get", "install", "--no-install-recommends", "-y", "ffmpeg"],
            {"check": True},
        ),
    ]


def test_working_runtime_avoids_apt(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "route_archives", lambda *args: [])
    monkeypatch.setattr(bootstrap, "missing_packages", lambda profile: [])
    monkeypatch.setattr(
        bootstrap.subprocess, "run", lambda *args, **kw: pytest.fail("apt must not run")
    )
    assert bootstrap.prepare("browser", "noble", tmp_path)["native_probes_passed"]


def test_install_failure_propagates(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "route_archives", lambda *args: [])
    monkeypatch.setattr(bootstrap, "missing_packages", lambda profile: ["ffmpeg"])

    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(bootstrap.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        bootstrap.prepare("browser", "noble", tmp_path)


def test_post_install_unavailable_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(bootstrap, "route_archives", lambda *args: [])
    monkeypatch.setattr(bootstrap, "missing_packages", lambda profile: ["ffmpeg"])
    monkeypatch.setattr(bootstrap.subprocess, "run", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="unavailable after bootstrap"):
        bootstrap.prepare("browser", "noble", tmp_path)


def test_unknown_profile_fails_before_sources_change(monkeypatch):
    monkeypatch.setattr(
        bootstrap, "route_archives", lambda *args: pytest.fail("source mutation")
    )
    with pytest.raises(ValueError, match="Unsupported dependency profile"):
        bootstrap.prepare("unknown", "noble")


def test_cli_refuses_developer_machine_before_any_source_action(monkeypatch):
    monkeypatch.setattr("sys.argv", ["bootstrap", "--profile", "python"])
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(
        bootstrap, "prepare", lambda *args: pytest.fail("bootstrap execution")
    )
    with pytest.raises(SystemExit, match="disposable Ubuntu"):
        bootstrap.main()


@pytest.mark.parametrize(
    "release",
    [
        {"ID": "ubuntu", "VERSION_ID": "99.04", "VERSION_CODENAME": "unknown"},
        {"ID": "ubuntu", "VERSION_ID": "24.04", "VERSION_CODENAME": "jammy"},
    ],
)
def test_cli_refuses_unknown_or_conflicting_release(monkeypatch, release):
    monkeypatch.setattr("sys.argv", ["bootstrap", "--profile", "python"])
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_OS", "Linux")
    monkeypatch.setattr(bootstrap.platform, "system", lambda: "Linux")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        bootstrap.platform, "freedesktop_os_release", lambda: release, raising=False
    )
    monkeypatch.setattr(
        bootstrap, "prepare", lambda *args: pytest.fail("bootstrap execution")
    )
    with pytest.raises(SystemExit, match="Unsupported Ubuntu release"):
        bootstrap.main()
