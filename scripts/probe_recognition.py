"""Inspect raw-video recognition at unverified reference frames, without labels.

This diagnostic cannot establish accuracy. It intentionally avoids creating
reviewed events or treating externally supplied timestamps as exact contacts.
"""

import argparse
import json
from pathlib import Path

from badminton.cli import load_evaluation_run
from badminton.config import DATA, ROOT
from badminton.jobs import run_local_job
from badminton.recognition import recognize_strokes
from badminton.storage import Store
from badminton.video import resolve_source, timestamps_for, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--players-run", required=True)
    parser.add_argument("--shuttle-run", required=True)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.data)
    video = store.video(args.video_id)
    resolve_source(video, ROOT)
    players = load_evaluation_run(store, args.video_id, args.players_run, "players")
    shuttle = load_evaluation_run(store, args.video_id, args.shuttle_run, "shuttle")
    start = max(players["start_frame"], shuttle["start_frame"])
    end = min(players["end_frame"], shuttle["end_frame"])
    if any(not start <= frame < end for frame in args.frames):
        parser.error("Reference frames must lie within both perception runs")
    annotations = store.annotations(args.video_id)
    times = timestamps_for(args.data, args.video_id)
    targets = [
        {
            "id": f"probe-{frame}",
            "frame": frame,
            "event_id": None,
            "player_id": None,
            "contact_candidate_id": None,
            "contact_start_frame": None,
            "contact_end_frame": None,
        }
        for frame in sorted(set(args.frames))
    ]

    def task(_identifier, progress):
        recognize_strokes(
            video,
            times,
            annotations,
            players,
            shuttle,
            targets,
            args.players_run,
            progress,
            args.output,
        )
        result = json.loads(args.output.read_text(encoding="utf-8"))
        result.update(
            probe_only=True,
            target_semantics="unverified reference frames",
            strict_accuracy=None,
            source_contact_adjudication="required",
        )
        write_json(args.output, result)
        return {
            "video_id": args.video_id,
            "probe_only": True,
            "candidate_count": len(result["candidates"]),
            "output": str(args.output),
        }

    # Use the app's admission store even when input artifacts live separately.
    summary = run_local_job(Store(DATA), "feature-preparation", None, task)
    assert store.annotations(args.video_id) == annotations
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
