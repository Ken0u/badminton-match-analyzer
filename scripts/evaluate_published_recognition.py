"""Frozen-test component benchmark on published features, not uploaded-video accuracy."""

import argparse
from pathlib import Path

import numpy as np
from badminton.config import WEIGHTS
from badminton.recognition_evaluation import (
    CLASSES,
    TARGET_FAMILIES,
    _confusion_metrics,
)
from badminton.stroke_features import summarize_probabilities
from badminton.stroke_side import load_side_predictor, side_metrics, training_arrays
from badminton.training_features import file_sha
from badminton.video import write_json


def evaluate(descriptors, output):
    import torch
    from badminton.vendor.bst.bst import BST_0

    torch.set_num_threads(4)
    arrays, metadata = training_arrays(descriptors)
    selected = arrays["splits"] == "test"
    features = arrays["features"][selected]
    truth = arrays["families"][selected]
    sides = arrays["labels"][selected]
    model = BST_0(in_dim=72, seq_len=30, n_class=35)
    if (
        file_sha(WEIGHTS / "bst_0_JnB_bone_2.pt")
        != metadata["recipe"]["base_checkpoint_sha256"]
    ):
        raise ValueError(
            "Benchmark family checkpoint does not match the frozen descriptor source"
        )
    model.load_state_dict(
        torch.load(
            WEIGHTS / "bst_0_JnB_bone_2.pt", map_location="cpu", weights_only=True
        ),
        strict=True,
    )
    model.eval()
    predictor = load_side_predictor("cpu")
    if predictor is None:
        raise ValueError("A stroke-side head is required for this component benchmark")
    with torch.inference_mode():
        family_probabilities = (
            model.mlp_head(torch.from_numpy(features[:, :300])).softmax(1).numpy()
        )
    summaries = [summarize_probabilities(p) for p in family_probabilities]
    families = np.asarray(
        [
            ("serve" if r["kind"] == "serve" else r["family"])
            if r["family_score"] >= 0.5 and r["family"] != "unknown"
            else "unanswered"
            for r in summaries
        ]
    )
    matrix = {
        name: dict.fromkeys((*CLASSES, "unanswered"), 0)
        for name in (*CLASSES, "no_contact")
    }
    for target, guess in zip(truth, families, strict=True):
        matrix[str(target)][str(guess)] += 1
    ends = np.asarray([r["hitter_court_end"] for r in summaries])
    true_ends = np.where(features[:, -2] == 1, "far", "near")
    modified = features.copy()
    modified[:, -2:] = np.stack((ends == "far", ends == "near"), axis=1)
    with torch.inference_mode():

        def probabilities(x):
            return (
                predictor["model"](
                    (torch.from_numpy(x) - predictor["mean"]) / predictor["std"]
                )
                .softmax(1)
                .numpy()
            )

        oracle = probabilities(features)
        predicted = probabilities(modified)
    labels = predicted.argmax(1)
    accepted = (
        np.isin(families, TARGET_FAMILIES)
        & np.isin(ends, ["far", "near"])
        & (predicted.max(1) >= predictor["metadata"]["recipe"]["threshold"])
    )
    confusion = np.zeros((2, 3), dtype=np.int64)
    for truth_side, guess, answered in zip(sides, labels, accepted, strict=True):
        confusion[int(truth_side), int(guess) if answered else 2] += 1
    strict = float(np.mean([confusion[i, i] / np.sum(sides == i) for i in (0, 1)]))
    joint = (families == truth) & (ends == true_ends) & (labels == sides) & accepted
    report = {
        "schema_version": 1,
        "dataset": "ShuttleSet published MMPose feature subset",
        "split": "test",
        "contact_count": len(features),
        "source_archive_sha256": metadata["recipe"]["feature_archive"]["sha256"],
        "label_index_sha256": metadata["label_index_sha256"],
        "descriptor_cache_sha256": metadata["array_sha256"],
        "base_checkpoint_sha256": metadata["recipe"]["base_checkpoint_sha256"],
        "side_checkpoint_sha256": predictor["metadata"]["checkpoint_sha256"],
        "scope": "Given source contacts and cached MMPose poses/shuttle observations; no raw-video tracking, automatic identities, rally boundaries, doubles, or YOLO transfer claim",
        "family": _confusion_metrics(matrix, TARGET_FAMILIES)
        | {"coverage": float(np.mean(families != "unanswered")), "confusion": matrix},
        "hitter_court_end_accuracy": float(np.mean(ends == true_ends)),
        "side_with_known_hitter": side_metrics(
            sides, oracle, predictor["metadata"]["recipe"]["threshold"]
        ),
        "side_with_predicted_family_and_hitter": {
            "confusion_rows_true_columns_forehand_backhand_unanswered": confusion.tolist(),
            "coverage": float(accepted.mean()),
            "answered_count": int(accepted.sum()),
            "accuracy_of_answered": float(np.mean(labels[accepted] == sides[accepted]))
            if accepted.any()
            else None,
            "balanced_recall_counting_abstentions_as_misses": strict,
        },
        "conditional_family_court_end_side_tuple": {
            "correct_count": int(joint.sum()),
            "contact_count": len(features),
            "accuracy_including_unanswered": float(joint.mean()),
            "meaning": "Correct family, court end and stroke side on supplied source contacts; this is not complete-event video accuracy",
        },
    }
    write_json(output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--descriptors",
        type=Path,
        default=Path("data/datasets/shuttleset/side-descriptors-v1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".cache/published-recognition-evaluation.json"),
    )
    args = parser.parse_args()
    report = evaluate(args.descriptors, args.output)
    print("Published-input family macro F1", report["family"]["macro_f1_supported"])
    print(
        "Conditional family/court-end/side tuple accuracy",
        report["conditional_family_court_end_side_tuple"][
            "accuracy_including_unanswered"
        ],
    )
