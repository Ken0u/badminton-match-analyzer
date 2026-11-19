"""Read-only feasibility check: one vertical-offset refit, never install it.

Usage: python scripts/audit_net_refit.py PROCESSED_VIDEO_DIR ANALYSIS_KEY
First 60 continuing pairs in chronological rally order, including unavailable
cases. Fixed position/velocity except for initial height (gravity and drag are
translation invariant). For a strongly low baseline only, minimize image MSE
over seven equally spaced offsets from minimum +2 cm clearance to +0.50 m.
No refit if infeasible or if same-point RMS increases by >0.002 image heights.
This is not a ground-truth accuracy benchmark or a match-level fault detector.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from badminton import match_analysis as ma
from badminton import rally_outcomes as ro
from badminton import shuttle_flight as sf


def audit(directory, key):
    def read(path):
        return json.loads(path.read_text(encoding="utf-8"))

    plan = read(directory / "analysis" / key / "manifest.json")
    video = read(directory / "metadata.json")
    if not plan["processing_complete"] or plan["video_sha256"] != video["sha256"]:
        raise ValueError("Incomplete plan or mismatched source")
    runs = ma.load_plan_runs(
        SimpleNamespace(data=directory.parent), directory.name, plan, outcomes=False
    )
    times = read(directory / "timestamps.json")
    line = ro.timeline(ma.MatchInputs(video, times, plan, runs))
    contacts = line["contacts"]
    groups = ro.rallies_from_contacts(
        contacts, times, line["segments"], line["serves"], line["ends"]
    )
    pairs = [
        (contacts[i], contacts[j])
        for g in groups
        for i, j in zip(g["shots"], g["shots"][1:])
    ][:60]
    results = Counter()
    for a, b in pairs:
        i, j = a["frame"], b["frame"]
        end = a["court_end"]
        aspect = line["aspect"]
        if (
            end not in ro.ENDS
            or b["court_end"] != ro.other(end)
            or any(v != line["segments"][i] for v in line["segments"][i : j + 1])
        ):
            results["ineligible"] += 1
            continue

        def matrix(k):
            return ro._homography(line, k)

        fit = ro.shot_flight(
            times, line["shuttle"], i, j, aspect, matrix, end, ro._people(line)
        )
        if not fit:
            results["no_fit"] += 1
            continue
        start = fit["start_index"]
        state = np.array(fit["start"] + fit["velocity"])
        origin = fit.get("time_origin_s", times[start])
        duration = times[j] - origin
        check = sf.continuing_net_check(state, duration)
        if not check or check["net_check"] != "below_net":
            results[check["net_check"] if check else "no_crossing"] += 1
            continue
        lower = 0.0201 - check["net_clearance_m"]
        if lower > 0.5:
            results["offset_infeasible"] += 1
            continue
        indices = ro.flight(times, line["shuttle"], start, j, aspect)
        if line["shuttle"][start] is not None:
            indices = [start, *indices]
        indices = [
            k
            for k in indices
            if times[k] >= origin and k < fit.get("continuous_until", j)
        ]
        at = np.array([times[k] - origin for k in indices])
        obs = np.array([line["shuttle"][k] for k in indices])
        cam = ro.camera_for(matrix(i), aspect)
        positions = sf.positions_at(state[None], at)[0]

        def rms(offset):
            image, depth = cam.project(positions + np.array((0, 0, offset)))
            return (
                float(
                    np.sqrt(np.mean(np.sum(((image - obs) * [aspect, 1]) ** 2, axis=1)))
                )
                if np.all(depth > 0)
                else float("inf")
            )

        baseline = rms(0)
        error, offset = min((rms(v), v) for v in np.linspace(lower, 0.50, 7))
        state[2] += offset
        after = sf.continuing_net_check(state, duration)
        if not after or after["net_clearance_m"] < 0.02:
            raise AssertionError("candidate missed constraint")
        results[
            "candidate_pass" if error <= baseline + 0.002 else "image_error_reject"
        ] += 1
    return {
        "video_sha256": video["sha256"],
        "analysis_key": key,
        "pairs": len(pairs),
        "counts": dict(results),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("key")
    args = parser.parse_args()
    print(json.dumps(audit(args.directory, args.key), indent=2))
