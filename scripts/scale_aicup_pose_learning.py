"""Fixed private training-data scaling; no app model installation."""

import sys
from pathlib import Path


def arithmetic(argv):
    """Separate calculation: never import the scientific feature/metric producer."""
    import argparse
    import hashlib
    import json
    import math

    import numpy as np
    import torch

    parser = argparse.ArgumentParser(description=arithmetic.__doc__)
    parser.add_argument("--prospective", type=Path, required=True)
    parser.add_argument("--prospective-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)

    def read(path):
        return json.loads(Path(path).read_bytes())

    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def equal(a, b):
        if isinstance(a, dict):
            assert isinstance(b, dict) and a.keys() == b.keys()
            for key in a:
                equal(a[key], b[key])
        elif isinstance(a, list):
            assert isinstance(b, list) and len(a) == len(b)
            for left, right in zip(a, b, strict=True):
                equal(left, right)
        elif type(a) is float:
            assert type(b) in (float, int) and math.isclose(
                a, b, rel_tol=1e-12, abs_tol=1e-12
            )
        else:
            assert type(a) is type(b) and a == b

    assert sha(args.prospective) == args.prospective_sha256
    plan, output = read(args.prospective), args.output.resolve()
    assert plan["output"] == str(output)
    assert not any(name.startswith("badminton") for name in sys.modules)
    protocol = plan["protocol"]
    labels = [protocol["labels"]["family"], protocol["labels"]["side"]]
    rows, cohort = read(output / "features.json"), read(output / "cohort.json")
    completion = read(output / "completion.json")
    assert completion["prospective_sha256"] == args.prospective_sha256
    receipts = completion["receipts"]
    assert [r["key"] for r in receipts] == cohort["new_keys"]
    assert sum(r["frames"] for r in receipts) == protocol["expected"]["new_frames"]
    assert (
        sum(r["decoded_frame_visits"] for r in receipts)
        == 2 * protocol["expected"]["new_frames"]
    )
    assert (
        sum(r["model_frame_observations"] for r in receipts)
        == protocol["expected"]["new_frames"]
    )
    assert all(
        r["decoded_frame_visits"] == 2 * r["frames"]
        and r["model_frame_observations"] == r["frames"]
        for r in receipts
    )
    original = Path(plan["control"])
    assert sha(original / "features.json") == protocol["original"]["control_features"]
    assert sha(original / "static/model.pt") == protocol["original"]["control_model"]
    assert (
        sha(original / "static/statistics.json")
        == protocol["original"]["control_statistics"]
    )
    old_rows = read(original / "features.json")
    old_by_id = {r["id"]: r for r in old_rows}
    assert len(old_by_id) == len(old_rows) == protocol["expected"]["reused_rows"]
    assert (
        len(rows)
        == protocol["expected"]["train_rows"] + protocol["expected"]["validation_rows"]
    )
    assert [r["id"] for r in rows] == [r["id"] for r in cohort["reference_rows"]]
    assert [r for r in rows if r["fold"] == "validation"] == [
        r for r in old_rows if r["fold"] == "validation"
    ]
    assert all(r == old_by_id[r["id"]] for r in rows if r["id"] in old_by_id)
    assert sum(r["fold"] == "train" for r in rows) == protocol["expected"]["train_rows"]
    assert len(cohort["new_keys"]) == protocol["expected"]["new_clips"]
    assert len(cohort["reused_keys"]) == protocol["expected"]["reused_clips"]
    assert all(
        r["fold"] in ("train", "validation")
        and not r["training_ready"]
        and r["scene_truth"] == r["actor_truth"] == "unknown"
        for r in rows
    )

    def infer(items, folder):
        statistics = read(folder / "statistics.json")
        values = np.asarray([r["static"] for r in items], np.float32)
        selected = np.asarray([r["fold"] == "train" and r["available"] for r in items])
        train = values[selected].astype(np.float64)
        equal(train.mean(0).tolist(), statistics["mean"])
        equal(np.maximum(train.std(0), 0.05).tolist(), statistics["std"])
        equal(int(selected.sum()), statistics["normalization_rows"])
        for head, field in enumerate(("family", "side")):
            counts = [
                int(
                    sum(
                        r[field] == i and use
                        for r, use in zip(items, selected, strict=True)
                    )
                )
                for i in range(len(labels[head]))
            ]
            equal(counts, statistics["counts"][head])
            equal([count > 0 for count in counts], statistics["support"][head])
            weights = [1 / math.sqrt(count) if count else 0 for count in counts]
            average = math.fsum(weights) / sum(count > 0 for count in counts)
            equal([weight / average for weight in weights], statistics["weights"][head])
        values = np.clip(
            (values - np.asarray(statistics["mean"], np.float32))
            / np.asarray(statistics["std"], np.float32),
            -10,
            10,
        )
        weights = {
            key: value.numpy()
            for key, value in torch.load(
                folder / "model.pt", map_location="cpu", weights_only=True
            ).items()
        }
        assert sum(w.size for w in weights.values()) == 9386
        assert set(weights) == {
            prefix + suffix
            for prefix in ("body.0", "body.3", "family", "side")
            for suffix in (".weight", ".bias")
        }
        hidden = np.maximum(
            values @ weights["body.0.weight"].T + weights["body.0.bias"], 0
        )
        hidden = np.maximum(
            hidden @ weights["body.3.weight"].T + weights["body.3.bias"], 0
        )
        predictions = []
        for head, name in enumerate(("family", "side")):
            logits = hidden @ weights[name + ".weight"].T + weights[name + ".bias"]
            logits[:, ~np.asarray(statistics["support"][head], bool)] = -np.inf
            prediction = logits.argmax(1)
            prediction[~np.asarray([r["available"] for r in items])] = -1
            predictions.append(prediction.tolist())
        equal(predictions, read(folder / "predictions.json"))
        return predictions

    def classes(truth, predicted, names):
        size = len(names)
        matrix = [[0] * (size + 1) for _ in names]
        for target, prediction in zip(truth, predicted, strict=True):
            if target >= 0:
                matrix[target][prediction if prediction >= 0 else size] += 1
        per = {}
        for index, name in enumerate(names):
            support = sum(matrix[index])
            total = sum(row[index] for row in matrix)
            tp = matrix[index][index]
            per[name] = {
                "support": support,
                "predictions_on_known_truth": total,
                "tp": tp,
                "precision": tp / total if total else 0.0,
                "recall": tp / support if support else None,
                "f1": 2 * tp / (support + total) if support + total else None,
            }
        supported = [name for name in names if per[name]["support"]]
        known = sum(t >= 0 for t in truth)
        return {
            "source_rows": len(truth),
            "known_targets": known,
            "unknown_targets": len(truth) - known,
            "predictions_on_unknown_truth": sum(
                t < 0 <= p for t, p in zip(truth, predicted, strict=True)
            ),
            "unanswered_known_targets": sum(
                p < 0 <= t for t, p in zip(truth, predicted, strict=True)
            ),
            "confusion_columns": [*names, "unanswered"],
            "confusion": matrix,
            "per_class": per,
            "supported_classes": supported,
            "macro_f1": math.fsum(per[n]["f1"] for n in supported) / len(supported)
            if supported
            else None,
            "balanced_recall": math.fsum(per[n]["recall"] for n in supported)
            / len(supported)
            if supported
            else None,
            "strict_known_accuracy": sum(
                t == p and t >= 0 for t, p in zip(truth, predicted, strict=True)
            )
            / known
            if known
            else None,
        }

    def metrics(items, predictions):
        indices = [i for i, r in enumerate(items) if r["fold"] == "validation"]
        truth = [[items[i][field] for i in indices] for field in ("family", "side")]
        predicted = [[p[i] for i in indices] for p in predictions]
        available = [items[i]["available"] for i in indices]
        known = [f >= 0 and s >= 0 for f, s in zip(*truth, strict=True)]
        correct = [
            k and f == pf and s == ps
            for k, f, s, pf, ps in zip(known, *truth, *predicted, strict=True)
        ]
        paired = [a and k for a, k in zip(available, known, strict=True)]
        per = {}
        for f, name in enumerate(labels[0]):
            for s, side in enumerate(labels[1]):
                targets = [tf == f and ts == s for tf, ts in zip(*truth, strict=True)]
                outputs = [
                    pf == f and ps == s and k
                    for pf, ps, k in zip(*predicted, known, strict=True)
                ]
                support, total = sum(targets), sum(outputs)
                tp = sum(t and p for t, p in zip(targets, outputs, strict=True))
                per[name + "/" + side] = {
                    "support": support,
                    "predictions_on_known_truth": total,
                    "tp": tp,
                    "precision": tp / total if total else 0.0,
                    "recall": tp / support if support else None,
                    "f1": 2 * tp / (support + total) if support + total else None,
                }
        family = classes(truth[0], predicted[0], labels[0])
        requested = [
            family["per_class"][name]["f1"]
            for name in labels[0][:6]
            if family["per_class"][name]["support"]
        ]
        return {
            "source_rows": len(indices),
            "weak_pairs": sum(available),
            "unavailable_rows": len(indices) - sum(available),
            "unknown_joint_targets": len(indices) - sum(known),
            "family": family,
            "side": classes(truth[1], predicted[1], labels[1]),
            "requested_six_macro_f1": math.fsum(requested) / len(requested)
            if requested
            else None,
            "family_side": per,
            "correct_joint": sum(correct),
            "strict_joint_all_source_rows": sum(correct) / len(indices),
            "strict_joint_known_targets": sum(correct) / sum(known)
            if any(known)
            else None,
            "conditional_joint_given_weak_pair_and_known_targets": sum(
                c and p for c, p in zip(correct, paired, strict=True)
            )
            / sum(paired)
            if any(paired)
            else None,
            "conditional_denominator": sum(paired),
            "independent_accuracy": False,
        }

    results = {}
    for name, items, folder in (
        ("candidate", rows, output / "candidate"),
        ("control", old_rows, original / "static"),
    ):
        values = metrics(items, infer(items, folder))
        equal(values, read(folder / "result.json")["validation"])
        results[name] = {
            "family_macro_f1": values["family"]["macro_f1"],
            "joint_correct": values["correct_joint"],
            "validation_rows": values["source_rows"],
        }

    # Recalculate representative raw-pose centers without producer feature code.
    refs = {r["id"]: r for r in cohort["reference_rows"]}
    old_freeze = read(Path(plan["prepared"]) / "freeze.json")
    old_clips = {c["key"]: (i, c) for i, c in enumerate(old_freeze["clips"])}
    new_clips = {key: i for i, key in enumerate(cohort["new_keys"])}
    old_diagnostics = {
        r["reference_id"]: r for r in read(Path(plan["audit"]) / "diagnostics.json")
    }
    sources, sample_count = {}, 0
    selected = sorted(
        {
            0,
            len(rows) - 1,
            *range(0, len(rows), 127),
            next(i for i, r in enumerate(rows) if r["id"] in old_by_id),
        }
    )
    for index in selected:
        row, ref = rows[index], refs[rows[index]["id"]]
        key = row["clip_key"]
        if key not in sources:
            if key in old_clips:
                number, clip = old_clips[key]
                folder = Path(plan["prepared"]) / clip["folder"]
                result = read(Path(plan["native"]) / f"clip-{number:02d}/players.json")
                diagnostics = old_diagnostics
            else:
                folder = output / f"clip-{new_clips[key]:03d}"
                result = read(folder / "players.json")
                diagnostics = {
                    r["reference_id"]: r for r in read(folder / "diagnostics.json")
                }
            sources[key] = read(folder / "video.json"), result, diagnostics
        video, result, diagnostics = sources[key]
        pair, h = diagnostics[ref["id"]]["weak_pair"], ref["source_contact_frame"]
        center = []
        camera = (
            result["frames"][h]["camera_segment_start_frame"]
            if pair is not None
            else None
        )
        for role in ("hitter", "defender"):
            for joint in range(5, 11):
                points = []
                if pair is not None:
                    for frame in result["frames"][h - 1 : h + 1]:
                        people = [
                            p for p in frame["players"] if p["track_id"] == pair[role]
                        ]
                        if (
                            frame["camera_segment_start_frame"] != camera
                            or frame["calibration_valid"] is not True
                            or len(people) != 1
                        ):
                            continue
                        person = people[0]
                        box, joints = person["box"], person["keypoints"]
                        if (
                            len(box) != 4
                            or not all(math.isfinite(v) for v in box)
                            or not (
                                0 <= box[0] < box[2] <= video["width"]
                                and 0 <= box[1] < box[3] <= video["height"]
                            )
                            or len(joints) != 17
                        ):
                            continue
                        x, y, confidence = joints[joint]
                        if not all(
                            math.isfinite(v) for v in (x, y, confidence)
                        ) or not (
                            0 <= x < video["width"]
                            and 0 <= y < video["height"]
                            and 0.25 <= confidence <= 1
                        ):
                            continue
                        height = box[3] - box[1]
                        points.append(
                            (
                                (x - (box[0] + box[2]) / 2) / height,
                                (y - box[3]) / height,
                                confidence,
                            )
                        )
                center.extend(
                    [
                        math.fsum(p[axis] for p in points) / len(points)
                        if points
                        else 0.0
                        for axis in (0, 1)
                    ]
                )
                center.append(math.fsum(p[2] for p in points) / 2)
        equal(center + center + [0.0] * 36, row["static"])
        sample_count += 1
    summary = {
        "verified_rows": len(rows),
        "reused_rows": len(old_rows),
        "new_clips": len(cohort["new_keys"]),
        "new_native_frames": sum(r["frames"] for r in receipts),
        "new_decoded_frame_visits": sum(r["decoded_frame_visits"] for r in receipts),
        "raw_pose_samples": sample_count,
        "validation": results,
        "feature_producer_imported": False,
        "refitted": False,
        "independent_accuracy_established": False,
    }
    assert not any(name.startswith("badminton") for name in sys.modules)
    with args.receipt.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(summary, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "arithmetic":
        arithmetic(sys.argv[2:])
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
        from badminton.aicup_pose_scaling import main

        main()
