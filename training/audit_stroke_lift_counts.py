"""Lift-count bias on already reported matched contacts (not full-match/player counts)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def lift(tab):
    true = sum(tab["lift"].values())
    pred = sum(v.get("lift", 0) for v in tab.values())
    correct = tab["lift"].get("lift", 0)
    return {
        "reference": true,
        "predicted": pred,
        "false_positive": pred - correct,
        "false_negative": true - correct,
        "signed_count_error": pred - true,
    }


def run():
    cache = ROOT / ".cache"
    s = json.loads(
        (cache / "lift-push-route-v1/historical-shuttleset.json").read_bytes()
    )["results"]["2"]["scores"]
    h = json.loads(
        (cache / "stroke-transfer-dev-0043/transfer-score.json").read_bytes()
    )["arms"]
    report = {}
    for name, arms, key in [
        ("Hangzhou", h, "confusion"),
        ("ShuttleSet", s, "family_confusion"),
    ]:
        report[name] = {k: lift(arms[k][key]) for k in ("ensemble", "window", "routed")}
        a = arms["window"][key]
        b = arms["routed"][key]
        assert set(a) == set(b)
        switched = {}
        for truth, row in a.items():
            nxt = b[truth]
            delta = row.get("lift", 0) - nxt.get("lift", 0)
            assert (
                delta == nxt.get("push", 0) - row.get("push", 0)
                and delta >= 0
                and all(
                    row.get(k, 0) == nxt.get(k, 0)
                    for k in (row.keys() | nxt.keys()) - {"lift", "push"}
                )
            )
            switched[truth] = delta
        report[name]["switched_lift_to_push_by_reference"] = {
            k: v for k, v in switched.items() if v
        }
        report[name]["false_lifts_removed"] = sum(switched.values()) - switched.get(
            "lift", 0
        )
        report[name]["true_lifts_removed"] = switched.get("lift", 0)
    return report


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
