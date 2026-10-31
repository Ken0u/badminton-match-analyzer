"""Check required hosted native coverage and exercise the workflow's actual gate."""

import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/ci.yml"
REQUIRED = {
    "revision",
    "python",
    "native",
    "repository",
    "package",
    "frontend",
    "browser-import",
    "container",
}


def jobs():
    return dict(
        re.findall(
            r"(?ms)^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)",
            WORKFLOW.read_text(encoding="utf-8"),
        )
    )


def test_native_matrix_uses_standard_supported_macos_and_retains_windows():
    native = jobs()["native"]
    matrix = re.search(r"(?m)^        os: \[([^\]]+)\]$", native)
    assert matrix and [value.strip() for value in matrix[1].split(",")] == [
        "macos-15",
        "windows-2022",
    ]
    assert "    runs-on: ${{ matrix.os }}\n" in native
    assert "      fail-fast: false\n" in native
    assert "    timeout-minutes: 30\n" in native
    assert "    needs: revision\n" in native
    assert "ref: ${{ needs.revision.outputs.tested_sha }}" in native
    assert "persist-credentials: false" in native


def test_native_coverage_retains_locked_environment_frontend_and_full_suite():
    native = jobs()["native"]
    for command in (
        "brew list ffmpeg || brew install ffmpeg",
        "choco install ffmpeg --no-progress -y",
        "uv sync --locked --python 3.12 --extra dev --extra youtube",
        "npm ci --ignore-scripts",
        "npm run frontend:test",
        "npm run frontend:build",
        "npm run frontend:stage:check",
        "npm run test:delivery --workspace @badminton/frontend",
        "uv pip check",
        "uv run --no-sync python -m pytest -q --basetemp .cache/pytest-native --junitxml .cache/test-results.xml",
    ):
        assert command in native
    assert 'BADMINTON_GPU_TESTS: "0"' in native
    assert 'python-version: "3.12"' in native
    assert "if: runner.os == 'macOS'" in native
    assert "if: runner.os == 'Windows'" in native
    assert "continue-on-error" not in native
    assert not re.search(r"(?m)^    if:", native)


def test_gate_retains_every_required_dependency_and_always_runs():
    gate = jobs()["gate"]
    needs = re.search(r"(?m)^    needs: \[([^\]]+)\]$", gate)
    assert needs and {value.strip() for value in needs[1].split(",")} == REQUIRED
    assert "    name: ci/gate\n" in gate
    assert "    if: always()\n" in gate
    assert "RESULTS: ${{ toJSON(needs) }}" in gate
    assert "continue-on-error" not in gate


def gate_script():
    body = (
        jobs()["gate"]
        .split("python - <<'PYTHON'\n", 1)[1]
        .split("          PYTHON", 1)[0]
    )
    return textwrap.dedent(body)


@pytest.mark.parametrize("dependency", sorted(REQUIRED))
@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped"])
def test_actual_gate_rejects_unsuccessful_native_and_other_dependencies(
    dependency, result
):
    results = {name: {"result": "success"} for name in REQUIRED}
    results[dependency]["result"] = result
    completed = subprocess.run(
        [sys.executable, "-c", gate_script()],
        env=os.environ | {"RESULTS": json.dumps(results)},
        capture_output=True,
        text=True,
    )
    assert completed.returncode != 0
    assert json.dumps({dependency: result}) in completed.stderr


def test_actual_gate_accepts_only_complete_successful_dependency_set():
    completed = subprocess.run(
        [sys.executable, "-c", gate_script()],
        env=os.environ
        | {"RESULTS": json.dumps({name: {"result": "success"} for name in REQUIRED})},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "Every required verification succeeded"
