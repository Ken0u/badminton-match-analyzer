"""Compare independent corpus label fields on timing-aligned *training* broadcasts.

Association uses no family/player prediction, class label or fitted time offset.
"""

import hashlib
import itertools
import json
from collections import Counter, defaultdict
from pathlib import Path

from badminton.event_model import FAMILIES
from evaluate_stroke_transfer_dev import MAP
from train_events import SHUTTLESET_FAMILY

ROOT = Path(__file__).resolve().parents[1]
PAIRS = {"0033": 29, "0034": 30, "0035": 6, "0036": 4}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def run():
    fb = ROOT / ".cache/stroke-source-audit"
    spec = json.loads(
        (ROOT / "backend/badminton/finebadminton_manifest.json").read_bytes()
    )
    files = {r["match_id"]: r for r in spec["files"]}
    groups = defaultdict(lambda: defaultdict(list))
    idx = ROOT / "data/datasets/shuttleset/index/strokes.jsonl"
    for line in idx.open(encoding="utf8"):
        r = json.loads(line)
        if r["match_id"] in PAIRS.values():
            assert r["split"] == "train"
            groups[r["match_id"]][r["set_id"], r["rally_id"]].append(r)
    by = {}
    joint = Counter()
    examples = []
    for fid, sid in PAIRS.items():
        fp = fb / (fid + "_updated.json")
        assert sha(fp) == files[fid]["sha256"]
        fr = json.loads(fp.read_bytes())
        refs = groups[sid]
        ss = {k: sorted(v, key=lambda r: r["stroke_order"]) for k, v in refs.items()}
        candidates = {}
        counter = Counter()
        tab = Counter()
        for i, r in enumerate(fr):
            h = r["hitting"]
            counter["published_actions"] += len(h)
            opts = []
            if len(h) < 4:
                continue
            for key, rows in ss.items():
                if len(rows) != len(h):
                    continue
                if not all(
                    type(s["source_frame"]) is int
                    and type(f.get("start_frame")) is int
                    and type(f.get("end_frame")) is int
                    for s, f in zip(rows, h)
                ):
                    continue
                if any(
                    left["source_frame"] >= right["source_frame"]
                    for left, right in itertools.pairwise(rows)
                ):
                    continue
                hits = sum(
                    f["start_frame"] < s["source_frame"] < f["end_frame"]
                    for s, f in zip(rows, h)
                )
                if hits / len(h) >= 0.8:
                    opts.append(key)
            if len(opts) == 1:
                candidates[i] = opts[0]
        dup = Counter(candidates.values())
        for i, key in candidates.items():
            if dup[key] != 1:
                continue
            counter["matched_rallies"] += 1
            h = fr[i]["hitting"]
            rows = ss[key]
            for s, f in zip(rows, h):
                if (
                    not f["start_frame"] < s["source_frame"] < f["end_frame"]
                    or sum(
                        u["start_frame"] <= s["source_frame"] <= u["end_frame"]
                        for u in h
                    )
                    != 1
                ):
                    continue
                counter["strict_timing_pairs"] += 1
                if s["issues"] or not s["family_eligible"]:
                    continue
                a = SHUTTLESET_FAMILY.get(s["source_type"])
                b = MAP.get(f.get("Foundational Actions Level", {}).get("hit type"))
                if a not in FAMILIES or b not in FAMILIES:
                    continue
                counter["eligible"] += 1
                counter["same_label"] += int(a == b)
                tab[a, b] += 1
                joint[a, b] += 1
                examples.append(
                    {
                        "fine": fid,
                        "ss": sid,
                        "set": key[0],
                        "rally": key[1],
                        "native_frame": s["source_frame"],
                        "interval": [f["start_frame"], f["end_frame"]],
                        "ss_family": a,
                        "fine_family": b,
                    }
                )
        by[fid] = {
            "ss": sid,
            "counts": counter,
            "confusion": {
                a: {b: n for (aa, b), n in tab.items() if aa == a}
                for a in sorted({a for a, _ in tab})
            },
        }
    return {
        "index_sha": sha(idx),
        "basis": "Preselected training match pairs; equal action counts >=4, strictly increasing published ShuttleSet ordinals, >=80% same-order frames strictly inside corresponding action intervals, unique rally in both directions. Count only known, issue-free ShuttleSet rows with a frame in exactly one FineBadminton action. No offset fitting. Association uses source ordinals, not exact-contact gold or independent adjudication.",
        "by_match": by,
        "confusion": {
            a: {b: n for (aa, b), n in joint.items() if aa == a}
            for a in sorted({a for a, _ in joint})
        },
        "examples": examples,
    }


if __name__ == "__main__":
    d = run()
    p = ROOT / ".cache/stroke-source-audit/train-taxonomy.json"
    p.write_text(json.dumps(d, indent=2))
    print({k: r["counts"] for k, r in d["by_match"].items()})
    print(d["confusion"])
