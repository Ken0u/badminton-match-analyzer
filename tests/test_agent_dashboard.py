"""The control issue is an idempotent, quiet view, never an ownership grant."""

import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from devops.dashboard import MARKER, publish, render


def state():
    return {
        "paused": False,
        "workers": {"mac/s": {"actor": "Ken0u", "host_id": "mac", "session_id": "s"}},
        "tasks": {
            "1": {
                "status": "running",
                "reason": "needs | @human\n<input>",
                "claim": {
                    "actor": "Ken0u",
                    "host_id": "mac",
                    "session_id": "s",
                    "expires_at": 200,
                },
            }
        },
    }


def test_dashboard_describes_ownership_without_claiming_host_liveness():
    source = state()
    before = copy.deepcopy(source)
    current = render(source, "pilot", 100)
    assert "current lease" in current and "not proof" in current
    assert "needs &#124; &#64;human &lt;input&gt;" in current
    assert "expired ownership; recovery required" in render(source, "pilot", 201)
    assert source == before


def test_dashboard_updates_existing_body_once_without_comments():
    class GitHub:
        def __init__(self):
            self.issue = {"number": 74, "body": "Human control instructions"}
            self.writes = []

        def pages(self, path):
            return [self.issue]

        def repo(self, path, *, method, data):
            assert path == "issues/74" and method == "PATCH"
            self.writes.append(data)
            self.issue.update(data)

    gh = GitHub()
    publish(gh, state(), "observation", 100)
    publish(gh, state(), "observation", 101)
    assert len(gh.writes) == 1
    assert gh.issue["body"].startswith("Human control instructions\n\n" + MARKER)


def test_dashboard_lists_verified_sources_and_pending_delivery():
    source = state()
    source["tasks"]["1"].update(
        status="done", merge_sha="a" * 40, delivery_pending=True
    )
    result = render(source, "active", 100)
    assert "`" + "a" * 40 + "` — candidate pending" in result
    assert "registered; availability unconfirmed" in result
