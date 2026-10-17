"""Compare saved baseline proposals with v2 without changing runs or labels.

Example (use completed local job IDs):
  python scripts/benchmark_contacts.py VIDEO --shuttle-run ID --players-run ID
      --baseline-run ID --output .cache/contact-benchmark.json

The existing evaluator scores representative navigation times. For an occlusion
proposal that time is not a measured contact, so interval containment is reported
separately and must not be interpreted as exact timing accuracy.
"""

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

from badminton.cli import load_evaluation_run
from badminton.config import DATA
from badminton.contacts import METHOD, propose_contacts
from badminton.evaluation import evaluate_contacts
from badminton.storage import Store
from badminton.video import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    parser.add_argument("--shuttle-run", required=True)
    parser.add_argument("--players-run", required=True)
    parser.add_argument("--baseline-run", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    store = Store(DATA)
    video = store.video(args.video_id)
    annotations = store.annotations(args.video_id).model_dump()
    shuttle = load_evaluation_run(store, args.video_id, args.shuttle_run, "shuttle")
    players = load_evaluation_run(store, args.video_id, args.players_run, "players")
    baseline = load_evaluation_run(store, args.video_id, args.baseline_run, "contacts")
    source_copy = copy.deepcopy(shuttle)
    candidates = propose_contacts(shuttle, players, video)
    assert shuttle == source_copy, "Contact proposals must preserve raw observations"
    updated = {
        "stage": "contacts",
        "video_id": video["id"],
        "run_id": "benchmark-v2-unsaved-proposals",
        "start_frame": shuttle["start_frame"],
        "end_frame": shuttle["end_frame"],
        "candidates": candidates,
    }
    old_evaluation = evaluate_contacts(video, annotations, baseline)
    new_evaluation = evaluate_contacts(video, annotations, updated)
    report = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video_id": video["id"],
        "video_sha256": video["sha256"],
        "annotation_revision": annotations["revision"],
        "shuttle_run_id": args.shuttle_run,
        "player_run_id": args.players_run,
        "baseline_run_id": args.baseline_run,
        "method": METHOD,
        "raw_observations_modified": False,
        "limitations": [
            "Development pilot, not an independent accuracy benchmark.",
            "Occlusion representative frames are navigation locations, not measured hit times.",
            "Explicit cut metadata is honored; camera cuts are not automatically detected here.",
        ],
        "baseline": {
            "representative_time_evaluation": old_evaluation,
            "interval_coverage": old_evaluation["interval_coverage"],
        },
        "updated": {
            "representative_time_evaluation": new_evaluation,
            "interval_coverage": new_evaluation["interval_coverage"],
            "candidates": candidates,
        },
    }
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
