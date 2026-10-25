"""Real offline CLI subprocesses on generated JSON only."""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_camera_evaluation import generated

CHECKOUT = Path(__file__).resolve().parents[1]


def files(tmp_path):
    paths = {}
    for name, value in zip(("video", "timestamps", "run", "reference"), generated()):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        paths[name] = path
    return paths


def launch(paths, output, *extra):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("BADMINTON_") or key in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "AGENT_PROJECT_TOKEN",
            "OPENAI_API_KEY",
            "CODEX_API_KEY",
        ):
            env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    command = [sys.executable, str(CHECKOUT / "scripts/evaluate_camera.py")]
    for name, path in paths.items():
        command.extend(["--" + name, str(path)])
    return subprocess.run(
        [*command, "--output", str(output), *extra],
        cwd=output.parent,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_cli_captures_exact_input_hashes_and_prints_aggregates_only(tmp_path):
    paths = files(tmp_path)
    original = {name: path.read_bytes() for name, path in paths.items()}
    output = tmp_path / "result.json"
    process = launch(paths, output, "--tolerance-s", "0")
    assert process.returncode == 0, process.stderr
    result = json.loads(output.read_bytes())
    assert json.loads(process.stdout) == result["summary"]
    assert result["summary"]["metrics"]["tp"] == 2
    assert result["input_sha256"] == {
        name: hashlib.sha256(raw).hexdigest() for name, raw in original.items()
    }
    assert "generated-only" not in process.stdout
    assert "reference:5" not in process.stdout
    assert "matches" not in process.stdout
    assert {name: path.read_bytes() for name, path in paths.items()} == original


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "nonfinite",
        "source",
        "clock",
        "corrected",
        "reference",
        "oversized",
        "tolerance",
    ],
)
def test_cli_invalid_input_preserves_all_bytes_and_existing_output(tmp_path, failure):
    paths = files(tmp_path)
    extra = []
    if failure == "duplicate":
        paths["video"].write_text('{"id":"first","id":"last"}', encoding="utf-8")
    elif failure == "nonfinite":
        paths["timestamps"].write_text("[NaN]", encoding="utf-8")
    elif failure == "oversized":
        paths["reference"].write_bytes(b" " * (16 * 1024**2 + 1))
    elif failure == "tolerance":
        extra = ["--tolerance-s", "nan"]
    else:
        name = (
            "timestamps"
            if failure == "clock"
            else "reference"
            if failure == "reference"
            else "run"
        )
        value = json.loads(paths[name].read_bytes())
        if failure == "source":
            value["video_sha256"] = "b" * 64
        elif failure == "clock":
            value.pop()
        elif failure == "corrected":
            value["camera_annotation_revision"] = 2
        else:
            value["windows"][0]["cuts_complete"] = "true"
        paths[name].write_text(json.dumps(value), encoding="utf-8")
    before = {name: path.read_bytes() for name, path in paths.items()}
    output = tmp_path / "result.json"
    output.write_bytes(b"preserve existing report\n")
    process = launch(paths, output, *extra)
    assert process.returncode == 2
    assert process.stdout == ""
    assert "Camera evaluation failed" in process.stderr
    assert output.read_bytes() == b"preserve existing report\n"
    assert {name: path.read_bytes() for name, path in paths.items()} == before
    fresh = tmp_path / "fresh.json"
    process = launch(paths, fresh, *extra)
    assert process.returncode == 2
    assert not fresh.exists()


def test_existing_output_is_exclusive_even_for_valid_inputs(tmp_path):
    paths = files(tmp_path)
    output = tmp_path / "result.json"
    output.write_bytes(b"retained")
    assert launch(paths, output).returncode == 2
    assert output.read_bytes() == b"retained"


def test_output_cannot_replace_an_input(tmp_path):
    paths = files(tmp_path)
    original = paths["video"].read_bytes()
    assert launch(paths, paths["video"]).returncode == 2
    assert paths["video"].read_bytes() == original


def test_symlink_input_is_rejected_when_available(tmp_path):
    paths = files(tmp_path)
    link = tmp_path / "linked.json"
    try:
        link.symlink_to(paths["video"])
    except OSError:
        pytest.skip("Creating a symlink requires local OS privileges")
    paths["video"] = link
    output = tmp_path / "result.json"
    assert launch(paths, output).returncode == 2
    assert not output.exists()


def test_incomplete_review_cli_succeeds_without_invented_scores(tmp_path):
    paths = files(tmp_path)
    reference = json.loads(paths["reference"].read_bytes())
    reference["windows"][0]["cuts_complete"] = False
    paths["reference"].write_text(json.dumps(reference), encoding="utf-8")
    output = tmp_path / "result.json"
    process = launch(paths, output)
    assert process.returncode == 0, process.stderr
    summary = json.loads(process.stdout)
    assert summary["status"] == "needs_complete_camera_review"
    assert summary["metrics"] is None
    assert summary["excluded_reference_cuts"] == 2
