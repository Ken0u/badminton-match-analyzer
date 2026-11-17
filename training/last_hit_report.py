"""Score dumped doubles hit curves on the last hit of each rally.

Reads the predictions_<fold>.json.gz files train_doubles.py writes and reports,
per threshold: contact precision and recall, how often the labelled last hit
is found (and with the right court end), and how often a contact is found
after it. Out-of-fold dumps (--holdout runs) give these on training matches
the model did not learn from, so a threshold can be chosen there.

    python training/last_hit_report.py run_a/fold*/predictions_heldout.json.gz
"""

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

THRESHOLDS = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8)


def peaks(probability, threshold, radius=4):
    found = []
    for index in np.argsort(-probability):
        if probability[index] < threshold:
            break
        if all(abs(index - other) > radius for other in found):
            found.append(int(index))
    return sorted(found)


def report(rows, threshold, tolerance=2):
    tp = fp = fn = last = last_end = after = clean = 0
    for row in rows:
        curve = np.asarray(row["hit"], float)
        frames = peaks(curve, threshold)
        hits = row["hits"]
        used = set()
        for frame in hits:
            options = [
                f for f in frames if f not in used and abs(f - frame) <= tolerance
            ]
            if options:
                used.add(min(options, key=lambda f: abs(f - frame)))
        tp += len(used)
        fn += len(hits) - len(used)
        fp += len(frames) - len(used)
        final = max(hits)
        who = row["hitters"][hits.index(final)]
        near = [f for f in frames if abs(f - final) <= tolerance]
        found = bool(near)
        late = any(f > final + tolerance for f in frames)
        last += found
        if found and who >= 0:
            best = min(near, key=lambda f: abs(f - final))
            last_end += row["hitter"][best] // 2 == who // 2
        after += late
        clean += found and not late
    count = max(1, len(rows))
    return {
        "threshold": threshold,
        "rallies": len(rows),
        "contact_precision": tp / max(1, tp + fp),
        "contact_recall": tp / max(1, tp + fn),
        "last_hit_found": last / count,
        "last_hit_found_right_end": last_end / count,
        "contact_after_last_hit": after / count,
        "last_hit_found_nothing_after": clean / count,
    }


def load(paths):
    rows = []
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8") as source:
            rows += json.load(source)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path, nargs="+")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows = load(args.predictions)
    results = [report(rows, t) for t in THRESHOLDS]
    for result in results:
        print(
            " ".join(
                f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}"
                for k, v in result.items()
            )
        )
    if args.output:
        args.output.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
