"""Score rally boundaries, landings, winners, reasons and the running score.

Compares what the application produces for a labelled evaluation clip
(training/rally_clips.py) with the published labels (training/rally_labels.py):

- boundaries: each labelled rally (first serve to last stroke, plus
  DShuttleNet's rally end) against the predicted rallies; splits (one label
  rally over two or more predictions), merges (one prediction over two or more
  label rallies), misses and extras (predictions over no label rally, such as
  replays), and start/end errors in seconds for one-to-one matches;
- landing of the last shot (court metres), rally winner (by court end),
  winner/error and its detail, on one-to-one matches;
- the running score: the predicted rallies' winners counted in order from
  the clip start (which is the start of the first set), compared with the
  published score after every labelled rally. Winners are given by court end
  and turned into the label's two sides with the label's own ends, so the
  score measures outcomes and boundaries, not player identity.

Unknown predictions count as wrong; every denominator is printed.

    python training/rally_eval.py --data .cache/step3/processed \
        --claims .cache/step3/claims --split validation --method stage
"""

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import rally_labels

PAD_S = 0.5  # a label rally spans its first serve to last stroke, +- this
EDGE_S = 3.0  # predictions this far outside the labelled span are not scored


def label_window(rally, offset, fps, frame_count):
    """Clip-frame view of a label rally, or None outside the clip."""
    serve = rally["serve_frame"] - offset
    last = rally["last_hit_frame"] - offset
    end = None if rally["end_frame"] is None else rally["end_frame"] - offset
    if serve < 0 or (end if end is not None else last) >= frame_count:
        return None
    return {**rally, "serve": serve, "last": last, "end": end}


def clip_labels(rallies, offset, fps, frame_count):
    """Label rallies inside the clip, and the frame span that is scored.

    Rallies cut by the clip's edges are not scored; predictions outside the
    span from the first scored serve to the last scored end (+-EDGE_S) are
    ignored, so the clip edges make no extras.
    """
    inside = [
        w for r in rallies if (w := label_window(r, offset, fps, frame_count)) is not None
    ]
    if not inside:
        return [], (0, -1)
    edge = round(EDGE_S * fps)
    return inside, (
        min(r["serve"] for r in inside) - edge,
        max(r["end"] or r["last"] for r in inside) + edge,
    )


def in_span(predictions, span):
    return [p for p in predictions if span[0] <= p["start_frame"] and p["end_frame"] <= span[1]]


def _overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0) + 1)


def match_rallies(labels, predictions, fps):
    """One-to-one pairs by overlap; plus split, merge, miss, extra counts."""
    pad = round(PAD_S * fps)
    spans = [(r["serve"] - pad, (r["end"] or r["last"]) + pad) for r in labels]
    touches = [
        [
            j
            for j, p in enumerate(predictions)
            if _overlap(a, b, p["start_frame"], p["end_frame"])
            and any(a <= f <= b for f in p["shot_frames"])
        ]
        for a, b in spans
    ]
    covered = Counter(j for row in touches for j in row)
    pairs, used = {}, set()
    order = sorted(
        (
            -_overlap(
                *spans[i], predictions[j]["start_frame"], predictions[j]["end_frame"]
            ),
            i,
            j,
        )
        for i, row in enumerate(touches)
        for j in row
    )
    for _, i, j in order:
        if i in pairs or j in used:
            continue
        pairs[i] = j
        used.add(j)
    return {
        "pairs": pairs,
        "split": sum(len(row) >= 2 for row in touches),
        "merge": sum(c >= 2 for c in covered.values()),
        "missed": sum(not row for row in touches),
        "extra": sum(j not in covered for j in range(len(predictions))),
        "clean": sum(len(row) == 1 and covered[row[0]] == 1 for row in touches),
    }


def _side(winner_end, first_end):
    if winner_end is None or first_end is None:
        return None
    return "first" if winner_end == first_end else "second"


def score_clip(labels, predictions, fps):
    """Per-label-rally comparison of the running score (from the clip start)."""
    if not labels:
        return {"rallies": 0, "right": 0}
    first_end = Counter(r["first_end"] for r in labels if r["first_end"]).most_common(1)
    first_end = first_end[0][0] if first_end else None
    points = {"first": 0, "second": 0}
    events = sorted(
        [(p["end_frame"], 0, p) for p in predictions]
        + [((r["end"] or r["last"]) + round(2.5 * fps), 1, r) for r in labels],
        key=lambda e: (e[0], e[1]),
    )
    right, total, unknown = 0, 0, 0
    for _, kind, item in events:
        if kind == 0:
            side = _side(item.get("winner_end"), first_end)
            if side is None:
                unknown += 1
            else:
                points[side] += 1
        else:
            total += 1
            right += points == item["score_after"]
    last = labels[-1]["score_after"]
    return {
        "rallies": total,
        "right": right,
        "unknown_winners": unknown,
        "final_predicted": dict(points),
        "final_label": last,
    }


def evaluate_clip(labels, predictions, fps):
    result = match_rallies(labels, predictions, fps)
    rows = []
    for i, j in sorted(result["pairs"].items()):
        label, pred = labels[i], predictions[j]
        row = {
            "label": f"{label['set']}-{label['rally']}",
            "start_err_s": (pred["start_frame"] - label["serve"]) / fps,
            "end_minus_last_hit_s": (pred["end_frame"] - label["last"]) / fps,
            "end_err_s": None
            if label["end"] is None
            else (pred["end_frame"] - label["end"]) / fps,
            "winner_label": label["winner_end"],
            "winner_pred": pred.get("winner_end"),
            "reason_label": label["reason"],
            "reason_pred": pred.get("reason"),
            "detail_label": label["detail"],
            "detail_pred": pred.get("detail"),
            "landing_label": label["landing"],
            "landing_pred": pred.get("landing"),
            "last_hitter_label": label["last_hitter_end"],
            "last_hitter_pred": pred.get("last_hitter_end"),
        }
        if row["landing_label"] and row["landing_pred"]:
            a, b = row["landing_label"], row["landing_pred"]
            row["landing_err_m"] = ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5
        rows.append(row)
    result["rows"] = rows
    result["score"] = score_clip(labels, predictions, fps)
    result["labels"] = len(labels)
    result["predictions"] = len(predictions)
    return result


def _share(n, d):
    return None if not d else round(n / d, 3)


def summarize(clips):
    """Pool clip results into one report (per dataset)."""
    rows = [row for c in clips for row in c["rows"]]
    labels = sum(c["labels"] for c in clips)
    out = {
        "clips": len(clips),
        "label_rallies": labels,
        "predicted_rallies": sum(c["predictions"] for c in clips),
        "clean_one_to_one": _share(sum(c["clean"] for c in clips), labels),
        "split": sum(c["split"] for c in clips),
        "merge": sum(c["merge"] for c in clips),
        "missed": sum(c["missed"] for c in clips),
        "extra": sum(c["extra"] for c in clips),
        "matched": len(rows),
    }
    starts = [abs(r["start_err_s"]) for r in rows]
    if starts:
        out["start_abs_err_s_median"] = round(statistics.median(starts), 2)
        out["start_within_1s"] = _share(sum(s <= 1 for s in starts), labels)
    tails = [r["end_minus_last_hit_s"] for r in rows]
    if tails:
        out["end_minus_last_hit_s_median"] = round(statistics.median(tails), 2)
        out["end_before_last_hit_0.5s"] = sum(t < -0.5 for t in tails)
    ends = [abs(r["end_err_s"]) for r in rows if r["end_err_s"] is not None]
    if ends:
        out["end_abs_err_s_median"] = round(statistics.median(ends), 2)
        out["end_within_1s"] = _share(sum(e <= 1 for e in ends), labels)

    def accuracy(key):
        known = [r for r in rows if r[f"{key}_label"] is not None]
        # Over every label rally: unmatched and unknown count as wrong.
        denominator = sum(1 for c in clips for _ in range(c["labels"]))
        right = sum(r[f"{key}_label"] == r[f"{key}_pred"] for r in known)
        return {
            "right": right,
            "matched_known": len(known),
            "predicted": sum(r[f"{key}_pred"] is not None for r in known),
            "of_matched": _share(right, len(known)),
            "of_all_labels": _share(right, denominator),
        }

    out["winner"] = accuracy("winner")
    out["reason"] = accuracy("reason")
    out["last_hitter"] = accuracy("last_hitter")
    detail_rows = [r for r in rows if r["detail_label"] in ("in", "out", "net")]
    out["detail_in_out_net"] = {
        "right": sum(r["detail_label"] == r["detail_pred"] for r in detail_rows),
        "of": len(detail_rows),
        "confusion": dict(
            Counter(f"{r['detail_label']}->{r['detail_pred']}" for r in detail_rows)
        ),
    }
    errors = sorted(r["landing_err_m"] for r in rows if "landing_err_m" in r)
    out["landing"] = {
        "with_both": len(errors),
        "matched_with_label": sum(r["landing_label"] is not None for r in rows),
        "median_err_m": round(statistics.median(errors), 2) if errors else None,
        "within_0.5m": sum(e <= 0.5 for e in errors),
        "within_1m": sum(e <= 1.0 for e in errors),
    }
    score = [c["score"] for c in clips]
    out["score"] = {
        "label_rallies": sum(s["rallies"] for s in score),
        "right": sum(s["right"] for s in score),
        "share": _share(
            sum(s["right"] for s in score), sum(s["rallies"] for s in score)
        ),
        "finals": [(s.get("final_predicted"), s.get("final_label")) for s in score],
    }
    return out


# Predictions --------------------------------------------------------------


def document_rallies(document):
    """Predicted rallies of a MatchAnalysis (schema 2 or later)."""
    result = []
    for rally in document.rallies:
        outcome = getattr(rally, "outcome", None)
        last = rally.shots[-1]
        landing = getattr(last, "landing", None)
        result.append(
            {
                "start_frame": rally.start_frame,
                "end_frame": rally.end_frame,
                "shot_frames": [s.frame for s in rally.shots],
                "winner_end": getattr(outcome, "winner_end", None),
                "reason": getattr(outcome, "reason", None),
                "detail": getattr(outcome, "detail", None),
                "last_hitter_end": getattr(outcome, "last_hitter_end", None),
                "landing": None
                if landing is None
                else [landing.position.x, landing.position.y],
            }
        )
    return result


def stage_rallies(records):
    """Predicted rallies from rally_outcomes.analyse records."""
    result = []
    for r in records:
        outcome = r.get("outcome") or {}
        result.append(
            {
                "start_frame": r["start_frame"],
                "end_frame": r["end_frame"],
                "shot_frames": r["shot_frames"],
                "winner_end": outcome.get("winner_end"),
                "reason": outcome.get("reason"),
                "detail": outcome.get("detail"),
                "last_hitter_end": r.get("last_hitter_end"),
                "landing": None if not r.get("landing") else r["landing"]["court"],
            }
        )
    return result


def load_clip(data, record):
    from badminton.match_analysis import build_match_analysis, load_match_inputs
    from badminton.storage import Store

    store = Store(Path(data))
    inputs = load_match_inputs(store, record["video_id"])
    return inputs, build_match_analysis(inputs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--data", type=Path, nargs="+", required=True, help="Store data folders"
    )
    parser.add_argument("--claims", type=Path, required=True)
    parser.add_argument("--split", choices=["validation", "test"], default="validation")
    parser.add_argument("--dataset", choices=["shuttleset", "dshuttlenet"])
    parser.add_argument("--clips", nargs="*", help="only these clip names")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--rows", action="store_true", help="print per-rally rows")
    parser.add_argument(
        "--method",
        choices=["document", "stage"],
        default="stage",
        help="document: the builder as stored processing gives it; stage: "
        "rally_outcomes.analyse on the stored runs with this checkout's code",
    )
    parser.add_argument("--model", type=Path, help="outcome model JSON (stage method)")
    args = parser.parse_args()
    model = None
    if args.model:
        from badminton.rally_outcomes import OutcomeModel

        model = OutcomeModel(json.loads(args.model.read_text(encoding="utf-8")))
    records = []
    for path in sorted(args.claims.glob("*/result.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record["split"] != args.split or not record.get("ok"):
            continue
        if args.dataset and record["dataset"] != args.dataset:
            continue
        if args.clips and record["name"] not in args.clips:
            continue
        records.append(record)
    if args.split == "test":
        print("Scoring TEST clips: settings must already be frozen.", flush=True)
    per_dataset = {}
    report = {"split": args.split, "clips": {}}
    for record in records:
        data = next(
            d for d in args.data if (d / record["video_id"] / "metadata.json").is_file()
        )
        inputs, document = load_clip(data, record)
        fps = document.video.fps
        labels, span = clip_labels(
            rally_labels.rallies(record["dataset"], record["match_id"]),
            record["start_frame"],
            fps,
            document.video.frame_count,
        )
        if args.method == "document":
            predictions = document_rallies(document)
        else:
            from badminton import rally_outcomes

            predictions = stage_rallies(
                rally_outcomes.analyse(rally_outcomes.timeline(inputs), model)
            )
        result = evaluate_clip(labels, in_span(predictions, span), fps)
        per_dataset.setdefault(record["dataset"], []).append(result)
        summary = summarize([result])
        report["clips"][record["name"]] = {
            k: v for k, v in result.items() if k != "rows"
        } | {"summary": summary}
        print(
            record["name"],
            json.dumps(
                {
                    k: summary[k]
                    for k in (
                        "label_rallies",
                        "predicted_rallies",
                        "clean_one_to_one",
                        "split",
                        "merge",
                        "missed",
                        "extra",
                    )
                }
            ),
            flush=True,
        )
        if args.rows:
            for row in result["rows"]:
                print("  ", json.dumps(row))
    for dataset, clips in sorted(per_dataset.items()):
        summary = summarize(clips)
        report[dataset] = summary
        print(f"== {dataset} {args.split}")
        print(json.dumps(summary, indent=1))
    if args.output:
        args.output.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
