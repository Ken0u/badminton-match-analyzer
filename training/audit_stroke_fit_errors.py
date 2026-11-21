"""Training-only diagnostic: which errors could be corrected by reranking two candidates?"""

import json
import pickle
from collections import Counter
from pathlib import Path

import numpy as np
from badminton.event_model import FAMILIES


def run(root):
    cfg = json.loads((root / "stroke-flight-video-v2/protocol.json").read_bytes())
    src = root / "stroke-rgb-v1"
    excluded = set(cfg["diagnostic_matches"])
    counts = Counter()
    pairs = Counter()
    fam = {}
    groups = {}
    for m in cfg["fit_matches"]:
        assert m not in excluded
        b = pickle.loads((src / f"train-{m}.pkl").read_bytes())
        group = Counter()
        for r in b["clips"]:
            fs = np.array(r["frames"])
            used = set()
            logits = r["window"]
            order = np.argsort(-logits, axis=1, kind="stable")
            for f, actor, k, side, serve, mask in r["hits"]:
                opts = [j for j in np.flatnonzero(abs(fs - f) <= 2) if j not in used]
                counts["references"] += 1
                if not opts:
                    continue
                j = min(opts, key=lambda j: abs(fs[j] - f))
                used.add(j)
                if k < 0:
                    continue
                a, b = map(int, order[j, :2])
                wrong = not bool(mask[a])
                rank2 = wrong and bool(mask[b])
                name = FAMILIES[k]
                fc = fam.setdefault(name, Counter())
                is_actor_known = actor >= 0
                actor_wrong = is_actor_known and r["pred"]["hitter"][fs[j]] != actor
                for c in (counts, group, fc):
                    c["matched_known"] += 1
                    c["wrong"] += int(wrong)
                    c["correct_second_among_errors"] += int(rank2)
                    c["wrong_family_known_actor"] += int(wrong and is_actor_known)
                    c["wrong_family_and_actor"] += int(wrong and actor_wrong)
                    c["wrong_family_missing_hitter_crop"] += int(
                        wrong and not r["ok"][j]
                    )
                if wrong:
                    pairs[(name, FAMILIES[a])] += 1
        groups[m] = dict(group)
    return {
        "scope": "27 fit matches; frozen incumbent in-sample; not held-out performance or a reranker accuracy forecast",
        "counts": dict(counts),
        "families": fam,
        "matches": groups,
        "most_frequent_errors": [
            {"reference": k, "predicted": a, "count": n}
            for (k, a), n in pairs.most_common(20)
        ],
    }


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1] / ".cache"
    d = run(root)
    (root / "stroke-flight-video-v2/fit-only-error-audit.json").write_text(
        json.dumps(d, indent=2)
    )
    print(d["counts"])
    print(d["most_frequent_errors"][:6])
