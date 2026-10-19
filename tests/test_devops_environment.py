"""Automation boundaries must fail closed without touching a live environment."""

import importlib.util
import json
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


environment = load("environment", SCRIPTS / "devops" / "environment.py")
repository = load("verify_repository", SCRIPTS / "verify_repository.py")
package = load("verify_package", SCRIPTS / "verify_package.py")


def test_bootstrap_refuses_primary_checkout(tmp_path):
    (tmp_path / ".git").mkdir()
    with pytest.raises(ValueError, match="linked Git worktree"):
        environment.bootstrap("review", tmp_path)


def test_bootstrap_never_syncs_existing_environment(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n")
    (tmp_path / ".venv").mkdir()
    with (
        patch.object(environment.shutil, "which", return_value="uv"),
        patch.object(environment.subprocess, "check_output", return_value="uv 0.9.4\n"),
        patch.object(environment.subprocess, "run") as run,
    ):
        with pytest.raises(ValueError, match="existing"):
            environment.bootstrap("review", tmp_path)
    run.assert_not_called()


def test_cuda_refused_on_mac_before_running_tools(tmp_path):
    (tmp_path / ".git").write_text("gitdir: elsewhere\n")
    with (
        patch.object(sys, "platform", "darwin"),
        patch.object(environment.subprocess, "run") as run,
    ):
        with pytest.raises(ValueError, match="CUDA"):
            environment.bootstrap("cuda", tmp_path)
    run.assert_not_called()


def test_doctor_does_not_expose_auth_output(tmp_path):
    (tmp_path / ".python-version").write_text("3.12\n")
    (tmp_path / "uv.lock").write_text("version = 1\n")
    with patch.object(environment.subprocess, "run") as run:
        run.return_value.returncode = 0
        run.return_value.stdout = "private-token"
        run.return_value.stderr = "secret"
        report = environment.doctor("review", tmp_path)
    assert report["ok"]
    assert "private-token" not in json.dumps(report)
    assert "secret" not in json.dumps(report)


def test_repository_rejects_encoding_json_and_missing_links(tmp_path):
    document = tmp_path / "guide.md"
    document.write_bytes(
        b"[missing](absent.md)\r\n[receipt](.cache/missing.json)\n[anchor](#heading)\n"
    )
    errors = repository.check_file(document, tmp_path)
    assert len(errors) == 2
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"value": NaN}')
    assert "invalid strict JSON" in repository.check_file(invalid, tmp_path)[0]
    invalid.write_bytes(b"\xff")
    assert "UTF-8" in repository.check_file(invalid, tmp_path)[0]


def test_secret_scan_redacts_value_and_skips_models(tmp_path):
    secret = "ghp_" + "a" * 36
    text = tmp_path / "credential.txt"
    text.write_text(secret)
    errors = repository.check_file(text, tmp_path)
    assert errors and secret not in str(errors)
    model = tmp_path / "weights.pt"
    model.write_bytes(b"\x00" + secret.encode())
    assert not repository.check_file(model, tmp_path)


def test_package_parity_rejects_changed_assets(tmp_path):
    wheel = tmp_path / "app.whl"
    sdist = tmp_path / "app.tar.gz"
    expected = {"badminton/assets/head.pt": b"expected"}
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("badminton/assets/head.pt", b"changed")
    with patch.object(package, "package_sources", return_value=expected):
        with pytest.raises(ValueError, match="Wheel package mismatch"):
            package.verify_archives(tmp_path, wheel, sdist)


def test_package_sdist_rejects_links(tmp_path):
    wheel = tmp_path / "app.whl"
    sdist = tmp_path / "app.tar.gz"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("badminton/__init__.py", b"")
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo("app/backend/badminton/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "../../outside"
        archive.addfile(member)
    with patch.object(
        package, "package_sources", return_value={"badminton/__init__.py": b""}
    ):
        with pytest.raises(ValueError, match="Unsafe"):
            package.verify_archives(tmp_path, wheel, sdist)


def test_package_rejects_unexpected_wheel_contents(tmp_path):
    wheel = tmp_path / "app.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("badminton/__init__.py", b"")
        archive.writestr(".cache/private.json", b"private")
    with patch.object(
        package, "package_sources", return_value={"badminton/__init__.py": b""}
    ):
        with pytest.raises(ValueError, match="Unexpected wheel"):
            package.verify_archives(tmp_path, wheel, tmp_path / "missing.tar.gz")
