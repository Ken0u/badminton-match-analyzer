"""Audit the frozen singles development gate. Reads aggregate reports, never weights."""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".cache"


def assess(report, protocol, historical):
    ids = {int(i) for i in protocol["split_matches"]["validation"]}
    assert len(ids) == 5
    comparisons = {}
    for offset, tol in enumerate((2, 4)):
        res = report["results"][str(tol)]
        s = res["scores"]
        for arm, name in (("ensemble", "baseline"), ("window", "candidate")):
            assert s[arm] == historical[offset][name], "historical replay mismatch"
            rows = res["paired"][arm]
            assert len(rows) == len(ids) and {int(k) for k in rows} == ids
            assert all(
                r["candidate_correct"] - r["installed_correct"]
                == r["fixed"] - r["introduced"]
                for r in rows.values()
            )
            for key in ("contacts", "clips", "contact_recall", "contact_precision"):
                assert s[arm][key] == s["visual"][key], "contact population changed"
            for key in (arm, "visual"):
                tab = s[key]["family_confusion"]
                assert sum(sum(r.values()) for r in tab.values()) == sum(
                    r["matched_known"] for r in rows.values()
                )
            gain = (
                s["visual"]["family_macro_f1_on_matched"]
                - s[arm]["family_macro_f1_on_matched"]
            )
            weak = res["weak_f1"]["visual"] - res["weak_f1"][arm]
            full = s["visual"]["complete_event_f1"] - s[arm]["complete_event_f1"]
            wins = sum(r["fixed"] > r["introduced"] for r in rows.values())
            comparisons[f"{arm}_tol{tol}"] = {
                "family_delta": gain,
                "weak_delta": weak,
                "complete_delta": full,
                "matches_improved": wins,
                "fixed": sum(r["fixed"] for r in rows.values()),
                "introduced": sum(r["introduced"] for r in rows.values()),
                "per_match": rows,
                "clears_primary_thresholds": (
                    gain >= 0.02 and weak >= 0.03 and full >= 0 and wins >= 4
                )
                if tol == 2
                else None,
            }
    return {
        "development_gate_passed": all(
            comparisons[f"{arm}_tol2"]["clears_primary_thresholds"]
            for arm in ("ensemble", "window")
        ),
        "coverage": report["coverage"],
        "comparisons": comparisons,
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    root = ap.parse_args().root

    def read(path):
        return json.loads((root / path).read_text(encoding="utf-8"))

    print(
        json.dumps(
            assess(
                read("stroke-rgb-v1/rgb-validation.json"),
                read("stroke-rgb-v1/protocol.json"),
                read("stroke-window-v1/report.json")["scores"]["shuttleset"],
            ),
            indent=2,
        )
    )
