"""Exercise the actual workflow's revision guard in a disposable repository."""

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"


def test_private_candidate_ci_read_is_limited_to_eligibility():
    release = (WORKFLOW.parent / "release.yml").read_text(encoding="utf-8")

    def permissions(block, indent):
        match = re.search(
            rf"(?m)^{indent}permissions:\n((?:{indent}  [^\n]+\n)+)", block + "\n"
        )
        return (
            dict(line.strip().split(": ", 1) for line in match[1].splitlines())
            if match
            else None
        )

    jobs = dict(re.findall(r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", release))
    # Eligibility reads CI history; installing packages receives no Actions
    # access, and only the image publisher retains its existing package write.
    assert permissions(release.split("\njobs:", 1)[0], "") == {"contents": "read"}
    assert permissions(jobs["eligibility"], "    ") == {
        "contents": "read",
        "actions": "read",
    }
    assert permissions(jobs["package"], "    ") is None
    assert permissions(jobs["images"], "    ") == {
        "contents": "read",
        "packages": "write",
    }


def revision_script():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    body = workflow.split("python - <<'PYTHON'\n", 1)[1].split("          PYTHON", 1)[0]
    return textwrap.dedent(body)


def git(root, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=root, text=True).strip()


@pytest.fixture
def history(tmp_path):
    git(tmp_path, "init", "-b", "main")
    (tmp_path / "source.txt").write_text("base\n")
    git(tmp_path, "add", "source.txt")
    git(
        tmp_path,
        "-c",
        "user.name=CI test",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "-m",
        "base",
    )
    base = git(tmp_path, "rev-parse", "HEAD")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", base)
    git(tmp_path, "checkout", "-b", "feature")
    (tmp_path / "source.txt").write_text("feature\n")
    git(tmp_path, "add", "source.txt")
    git(
        tmp_path,
        "-c",
        "user.name=CI test",
        "-c",
        "user.email=ci@example.invalid",
        "commit",
        "-m",
        "feature",
    )
    return tmp_path, base, git(tmp_path, "rev-parse", "HEAD")


def run_guard(root, requested, event_name="workflow_dispatch", event=None):
    event_file = root / "event.json"
    event_file.write_text(json.dumps(event or {}))
    env = os.environ | {
        "GITHUB_EVENT_PATH": str(event_file),
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_RUN_ID": "123",
        "GITHUB_OUTPUT": str(root / "output"),
        "VERIFY_SHA": requested,
    }
    return subprocess.run(
        [sys.executable, "-c", revision_script()],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("requested", ["main", "deadbeef", "a" * 40 + ";echo unsafe"])
def test_dispatch_rejects_non_exact_commit(history, requested):
    root, _, head = history
    result = run_guard(root, requested)
    assert result.returncode != 0
    assert git(root, "rev-parse", "HEAD") == head
    assert not (root / "output").exists()


def test_dispatch_rejects_unmerged_feature(history):
    root, _, head = history
    assert run_guard(root, head).returncode != 0
    assert not (root / "output").exists()


def test_dispatch_verifies_exact_main_ancestor(history):
    root, base, _ = history
    result = run_guard(root, base)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((root / ".cache/ci-revision.json").read_text())
    assert receipt["tested_sha"] == base
    assert git(root, "rev-parse", "HEAD") == base
    assert receipt["tested_tree"] == git(root, "rev-parse", "HEAD^{tree}")


def test_pr_receipt_distinguishes_published_head_from_tested_checkout(history):
    root, base, tested = history
    published_head = "c" * 40
    event = {"pull_request": {"head": {"sha": published_head}, "base": {"sha": base}}}
    result = run_guard(root, "", "pull_request", event)
    assert result.returncode == 0, result.stderr
    receipt = json.loads((root / ".cache/ci-revision.json").read_text())
    assert receipt["head_sha"] == published_head
    assert receipt["base_sha"] == base
    assert receipt["tested_sha"] == tested
