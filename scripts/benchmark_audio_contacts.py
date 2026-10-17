"""Compare opt-in acoustic/visual review proposals without changing labels."""

import argparse
import copy
import json
from pathlib import Path

from badminton.audio import extract_audio_cues
from badminton.audio_contacts import METHOD, add_audio_support
from badminton.cli import load_evaluation_run
from badminton.config import DATA, ROOT
from badminton.contacts import propose_contacts
from badminton.evaluation import evaluate_contacts
from badminton.scene_review import reviewed_run
from badminton.storage import Store
from badminton.video import timestamps_for, validate_range, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video_id")
    parser.add_argument("--shuttle-run", required=True)
    parser.add_argument("--players-run", required=True)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    store = Store(args.data)
    video = store.video(args.video_id)
    annotations = store.annotations(args.video_id).model_dump()
    shuttle = load_evaluation_run(store, args.video_id, args.shuttle_run, "shuttle")
    players = load_evaluation_run(store, args.video_id, args.players_run, "players")
    original = copy.deepcopy((shuttle, players, annotations))
    shuttle_view, player_view = (
        reviewed_run(shuttle, annotations),
        reviewed_run(players, annotations),
    )
    if (
        shuttle_view["requires_tracking_rerun"]
        or player_view["requires_tracking_rerun"]
    ):
        raise ValueError(
            "Camera corrections changed these inputs; rerun tracking before benchmarking"
        )
    times = timestamps_for(args.data, args.video_id)
    start, end = shuttle["start_frame"], shuttle["end_frame"]
    validate_range(video, times, start, end)
    end_s = times[end] if end < len(times) else video["duration_s"]
    audio = extract_audio_cues(video, ROOT, times[start], end_s)
    visual = propose_contacts(shuttle_view, player_view, video)
    supported = add_audio_support(visual, shuttle_view, player_view, video, audio)
    result = {
        "schema_version": 1,
        "video_id": args.video_id,
        "video_sha256": video["sha256"],
        "annotation_revision": annotations["revision"],
        "player_run_id": args.players_run,
        "shuttle_run_id": args.shuttle_run,
        "method": METHOD,
        "audio": audio,
        "limitations": [
            "Development examples; not a held-out accuracy benchmark.",
            "Audio onsets can be crowd, shoe, or other-court noise.",
            "AV offset is not calibrated; intervals are review bounds, not exact hits.",
            "Unreviewed/unknown-scene footage is excluded from strict metrics.",
        ],
    }
    for name, candidates in (("visual_only", visual), ("audio_supported", supported)):
        artifact = {
            "stage": "contacts",
            "video_id": args.video_id,
            "start_frame": start,
            "end_frame": end,
            "candidates": candidates,
        }
        result[name] = {
            "candidate_count": len(candidates),
            "candidates": candidates,
            "evaluation": evaluate_contacts(video, annotations, artifact),
        }
    assert original == (shuttle, players, annotations)
    assert store.annotations(args.video_id).model_dump() == annotations
    write_json(args.output, result)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "audio_status": audio["status"],
                "audio_peaks": len(audio["peaks"]),
                "visual_count": len(visual),
                "supported_count": len(supported),
            }
        )
    )


if __name__ == "__main__":
    main()
