"""Audit the predeclared Hangzhou development gate without revising a prediction."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def assess(report):
    arms = report["arms"]
    out = {}
    for name, arm in arms.items():
        c = arm["confusion"]
        assert sum(sum(r.values()) for r in c.values()) == report["matched_known"]
        assert sum(r.get(k, 0) for k, r in c.items()) == arm["correct"]
        pair = []
        for k in ("lift", "push"):
            n = sum(c.get(k, {}).values())
            fp_tp = sum(row.get(k, 0) for row in c.values())
            pair.append(2 * c[k].get(k, 0) / (n + fp_tp) if n else None)
        out[name] = {
            "six": arm["six_macro"],
            "lift": pair[0],
            "push": pair[1],
            "pair_macro": sum(pair) / 2 if None not in pair else None,
            "correct": arm["correct"],
        }
    candidate = out["routed"]
    deltas = {}
    for name, s in out.items():
        if name == "routed":
            continue
        trans = report["routed_vs"][name]
        diff = candidate["correct"] - s["correct"]
        assert diff == trans["fixed"] - trans["introduced"]
        six = (
            candidate["six"] - s["six"]
            if None not in (candidate["six"], s["six"])
            else None
        )
        pair = (
            candidate["pair_macro"] - s["pair_macro"]
            if None not in (candidate["pair_macro"], s["pair_macro"])
            else None
        )
        deltas[name] = {
            **trans,
            "net": diff,
            "six_delta": six,
            "pair_delta": pair,
            "clears_thresholds": six is not None
            and pair is not None
            and six >= 0.02
            and pair >= 0.03
            and diff >= 0,
        }
    return {
        "all_source_actions": report["source_rows"],
        "intervals": report["interval_status_all_rows"],
        "matched_known": report["matched_known"],
        "scores": out,
        "paired": deltas,
        "development_gate": all(
            deltas[k]["clears_thresholds"] for k in ("ensemble", "window")
        ),
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "report",
        type=Path,
        nargs="?",
        default=ROOT / ".cache/stroke-transfer-dev-0043/transfer-score.json",
    )
    args = p.parse_args()
    print(json.dumps(assess(json.loads(args.report.read_bytes())), indent=2))
