"""Publication visibility, legacy build identity and fail-closed receipts."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location(
    "candidate_under_test", SCRIPTS / "release_candidate.py"
)
candidate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate)

REPOSITORY = "Ken0u/badminton-match-analyzer"


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "commit.gpgsign=false", "commit", "--allow-empty", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def checkouts(tmp_path, monkeypatch):
    publisher = tmp_path / "publisher"
    publisher.mkdir()
    git(publisher, "init", "-q")
    git(publisher, "config", "user.name", "Fixture")
    git(publisher, "config", "user.email", "fixture@example.invalid")
    git(publisher, "config", "core.autocrlf", "false")
    (publisher / ".gitattributes").write_bytes(b"* text eol=lf\n")
    (publisher / ".github").mkdir()
    config = {"repository": REPOSITORY, "candidate_visibility": "private"}
    policy = publisher / ".github/automation.json"
    policy.write_text(json.dumps(config))
    (publisher / "uv.lock").write_bytes(b"original source lock\n")
    (publisher / "scripts").mkdir()
    (publisher / "scripts/release_candidate.py").write_text(
        "raise RuntimeError('obsolete private helper must not execute')\n"
    )
    source_sha = commit(publisher)
    config["candidate_visibility"] = "public"
    policy.write_text(json.dumps(config))
    (publisher / "uv.lock").write_bytes(b"different publisher lock\n")
    publisher_sha = commit(publisher)
    git(publisher, "update-ref", "refs/remotes/origin/main", publisher_sha)
    source = tmp_path / "source"
    subprocess.run(["git", "clone", "--quiet", str(publisher), str(source)], check=True)
    git(source, "checkout", "--quiet", "--detach", source_sha)
    monkeypatch.setattr(candidate, "ROOT", publisher)
    monkeypatch.setenv("SOURCE_SHA", source_sha)
    monkeypatch.setenv("PUBLISHER_SHA", publisher_sha)
    return publisher, source, source_sha, publisher_sha


class GitHub:
    def __init__(
        self, source, *, publisher=None, private=False, visibility="public", error=None
    ):
        self.repository = {"full_name": REPOSITORY, "private": private}
        self.runs = [
            {
                "id": 1,
                "event": "workflow_dispatch",
                "display_title": f"Verify {source}",
                "head_sha": source,
                "status": "completed",
                "conclusion": "success",
            }
        ]
        self.visibility = visibility
        self.error = error
        if publisher:
            self.runs.append(
                self.runs[0]
                | {
                    "id": 2,
                    "display_title": f"Verify {publisher}",
                    "head_sha": publisher,
                }
            )

    def repo(self, path=None):
        return {"workflow_runs": self.runs} if path else self.repository

    def api(self, path):
        if self.error:
            raise candidate.GitHubError(self.error)
        return {
            "name": path.rsplit("/", 1)[-1],
            "package_type": "container",
            "visibility": self.visibility,
        }


@pytest.mark.parametrize("visibility", ["public", "private"])
def test_explicit_mode_matches_repository_and_records_distinct_publisher(
    checkouts, monkeypatch, tmp_path, visibility
):
    publisher, _source, source_sha, _publisher_sha = checkouts
    path = publisher / ".github/automation.json"
    path.write_text(
        json.dumps({"repository": REPOSITORY, "candidate_visibility": visibility})
    )
    publisher_sha = commit(publisher)
    git(publisher, "update-ref", "refs/remotes/origin/main", publisher_sha)
    output = tmp_path / "outputs"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    result = candidate.validate(
        GitHub(source_sha, publisher=publisher_sha, private=visibility == "private"),
        source_sha,
    )
    assert result == {
        "source": source_sha,
        "publisher": publisher_sha,
        "visibility": visibility,
    }
    assert source_sha != publisher_sha
    assert (
        dict(line.split("=", 1) for line in output.read_text().splitlines()) == result
    )


@pytest.mark.parametrize("policy", [None, "internal", "", False])
def test_missing_or_invalid_visibility_has_no_private_or_public_fallback(policy):
    with pytest.raises(ValueError, match="Explicit"):
        candidate.visibility_policy(
            GitHub("a" * 40), {"repository": REPOSITORY, "candidate_visibility": policy}
        )


@pytest.mark.parametrize("mode,private", [("public", True), ("private", False)])
def test_visibility_mismatch_refuses_publication(mode, private):
    with pytest.raises(ValueError, match="match"):
        candidate.visibility_policy(
            GitHub("a" * 40, private=private),
            {"repository": REPOSITORY, "candidate_visibility": mode},
        )


def test_unverified_repository_metadata_cannot_claim_public_visibility():
    gh = GitHub("a" * 40)
    for metadata in ({"private": None}, {"private": False, "full_name": "other/repo"}):
        gh.repository = metadata
        with pytest.raises(ValueError, match="match"):
            candidate.visibility_policy(
                gh, {"repository": REPOSITORY, "candidate_visibility": "public"}
            )


@pytest.mark.parametrize(
    "status,conclusion",
    [("completed", "failure"), ("in_progress", None), ("queued", None)],
)
def test_latest_matching_main_run_must_have_completed_successfully(
    checkouts, status, conclusion
):
    _publisher, _source, source_sha, _publisher_sha = checkouts
    gh = GitHub(source_sha)
    gh.runs.append(gh.runs[0] | {"id": 2, "status": status, "conclusion": conclusion})
    with pytest.raises(ValueError, match="verification"):
        candidate.validate(gh, source_sha)


def test_unrelated_or_pr_checks_do_not_verify_source(checkouts):
    _publisher, _source, source_sha, _publisher_sha = checkouts
    gh = GitHub(source_sha)
    gh.runs[0].update(event="pull_request")
    with pytest.raises(ValueError, match="verification"):
        candidate.validate(gh, source_sha)
    gh.runs[0].update(event="push", head_sha="b" * 40)
    with pytest.raises(ValueError, match="verification"):
        candidate.validate(gh, source_sha)


@pytest.mark.parametrize("publisher_state", ["missing", "failed", "running"])
def test_verified_source_cannot_use_unverified_publisher(
    checkouts, monkeypatch, tmp_path, publisher_state
):
    _publisher, _source, source_sha, publisher_sha = checkouts
    gh = GitHub(source_sha, publisher=publisher_sha)
    if publisher_state == "missing":
        gh.runs.pop()
    elif publisher_state == "failed":
        gh.runs[-1]["conclusion"] = "failure"
    else:
        gh.runs[-1].update(status="in_progress", conclusion=None)
    output = tmp_path / "must-not-exist"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    with pytest.raises(ValueError, match="publisher"):
        candidate.validate(gh, source_sha)
    assert not output.exists()


def test_publisher_commit_must_also_belong_to_main(checkouts):
    publisher, _source, source_sha, _publisher_sha = checkouts
    (publisher / "unmerged.txt").write_text("not integrated")
    unmerged = commit(publisher)
    with pytest.raises(subprocess.CalledProcessError):
        candidate.validate(GitHub(source_sha, publisher=unmerged), source_sha)


def test_nonancestor_source_and_changed_checkouts_fail(checkouts):
    publisher, source, source_sha, publisher_sha = checkouts
    with pytest.raises(subprocess.CalledProcessError):
        candidate.validate(GitHub("f" * 40), "f" * 40)
    with pytest.raises(ValueError, match="checkout"):
        candidate.verified_checkout(source, publisher_sha)
    (source / "uv.lock").write_bytes(b"changed")
    with pytest.raises(subprocess.CalledProcessError):
        candidate.verified_checkout(source, source_sha)
    (publisher / "uv.lock").write_bytes(b"changed")
    with pytest.raises(subprocess.CalledProcessError):
        candidate.validate(GitHub(source_sha), source_sha)


@pytest.mark.parametrize("mode", ["public", "private"])
@pytest.mark.parametrize("target", ["review", "cpu"])
def test_pre_and_post_image_visibility_must_match_declared_mode(mode, target):
    gh = GitHub("a" * 40, visibility=mode)
    assert candidate.package_visibility(gh, target, mode)["visibility"] == mode
    gh.visibility = "private" if mode == "public" else "public"
    with pytest.raises(ValueError, match="visibility"):
        candidate.package_visibility(gh, target, mode, allow_missing=True)


@pytest.mark.parametrize("error", ["HTTP 403", "HTTP 500", "network unavailable"])
def test_package_api_errors_are_not_assumed_to_be_private_or_public(error):
    with pytest.raises(candidate.GitHubError):
        candidate.package_visibility(
            GitHub("a" * 40, error=error), "review", "public", allow_missing=True
        )


def test_missing_package_is_allowed_only_for_private_precreation():
    gh = GitHub("a" * 40, error="gh: Not Found (HTTP 404)")
    assert not candidate.package_visibility(
        gh, "review", "private", allow_missing=True
    )["exists"]
    for mode in ("public", "private"):
        with pytest.raises(ValueError, match="must exist"):
            candidate.package_visibility(gh, "review", mode)
    with pytest.raises(ValueError, match="must exist"):
        candidate.package_visibility(gh, "review", "public", allow_missing=True)


def test_inventory_of_legacy_source_uses_source_lock_and_current_publisher(
    checkouts, monkeypatch
):
    _publisher, source, source_sha, publisher_sha = checkouts
    dist = source / "dist"
    dist.mkdir()
    wheel = dist / "badminton_match_analyzer-0.1-py3-none-any.whl"
    sdist = dist / "badminton_match_analyzer-0.1.tar.gz"
    wheel.write_bytes(b"verified wheel")
    sdist.write_bytes(b"verified sdist")
    (dist / "unrelated-secret.txt").write_bytes(b"must never be inventoried")
    monkeypatch.setattr(
        sys, "argv", ["release_candidate.py", "inventory", "--source-root", str(source)]
    )
    monkeypatch.setattr(candidate, "GitHub", lambda _repo: GitHub(source_sha))
    candidate.main()
    receipt = json.loads((dist / "candidate.json").read_text())
    assert (
        receipt["source_sha"] == source_sha
        and receipt["publisher_sha"] == publisher_sha
    )
    assert receipt["visibility"] == "public"
    assert (
        receipt["lock_sha256"] == hashlib.sha256(b"original source lock\n").hexdigest()
    )
    assert receipt["files"] == {
        wheel.name: hashlib.sha256(wheel.read_bytes()).hexdigest(),
        sdist.name: hashlib.sha256(sdist.read_bytes()).hexdigest(),
    }
    assert receipt["deployment"] == "not performed"
    assert "not established" in receipt["annotation_accuracy"]
    assert candidate.checkout_sha(source) == source_sha
    assert "obsolete" in (source / "scripts/release_candidate.py").read_text()


def test_forbidden_metadata_with_404_in_its_text_is_not_a_missing_package():
    gh = GitHub("a" * 40, error="metadata 404 unavailable: Forbidden (HTTP 403)")
    with pytest.raises(candidate.GitHubError):
        candidate.package_visibility(gh, "review", "private", allow_missing=True)


@pytest.mark.parametrize(
    "defect", ["missing_sdist", "foreign_name", "two_wheels", "extra_wheel"]
)
def test_inventory_does_not_accept_incomplete_or_foreign_packages(checkouts, defect):
    _publisher, source, source_sha, publisher_sha = checkouts
    dist = source / "dist"
    dist.mkdir()
    names = ["badminton_match_analyzer-1.whl", "badminton_match_analyzer-1.tar.gz"]
    if defect == "missing_sdist":
        names.pop()
    elif defect == "foreign_name":
        names[0] = "other-1.whl"
    elif defect == "two_wheels":
        names[1] = "badminton_match_analyzer-2.whl"
    else:
        names.append("badminton_match_analyzer-2.whl")
    for name in names:
        (dist / name).write_bytes(b"package")
    with pytest.raises(ValueError, match="wheel and sdist"):
        candidate.inventory(
            source_sha,
            dist,
            source_root=source,
            publisher=publisher_sha,
            visibility="public",
        )
    assert not (dist / "candidate.json").exists()


def test_postpush_visibility_failure_creates_no_success_receipt(checkouts):
    _publisher, source, source_sha, publisher_sha = checkouts
    gh = GitHub(source_sha, visibility="private")
    kwargs = {
        "source_root": source,
        "publisher": publisher_sha,
        "visibility": "public",
        "config": {"repository": REPOSITORY},
    }
    digest = "sha256:" + "b" * 64
    with pytest.raises(ValueError, match="visibility"):
        candidate.image_receipt(gh, source_sha, "review", digest, **kwargs)
    assert not (source / "dist").exists()
    gh.visibility = "public"
    receipt = candidate.image_receipt(gh, source_sha, "review", digest, **kwargs)
    assert (
        receipt["visibility"] == "public" and receipt["publisher_sha"] == publisher_sha
    )
    assert receipt["image"] == f"ghcr.io/ken0u/badminton-match-analyzer-review@{digest}"
    assert json.loads((source / "dist/image-review.json").read_text()) == receipt


@pytest.mark.parametrize("publisher", ["", "c" * 40])
def test_missing_or_changed_publisher_binding_rejects_receipts(
    checkouts, monkeypatch, publisher
):
    _publisher, source, source_sha, _publisher_sha = checkouts
    monkeypatch.setenv("PUBLISHER_SHA", publisher)
    monkeypatch.setattr(candidate, "GitHub", lambda _repo: GitHub(source_sha))
    monkeypatch.setattr(
        sys, "argv", ["release_candidate.py", "inventory", "--source-root", str(source)]
    )
    with pytest.raises(ValueError):
        candidate.main()
    assert not (source / "dist").exists()
