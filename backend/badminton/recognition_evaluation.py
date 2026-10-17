"""Recognition metrics require independent labels; model scores are not accuracy."""

from collections import Counter

from .evaluation import _metrics, _uncertain_candidate, evaluate_contacts

TARGET_FAMILIES = ("clear", "lift", "net", "drop", "smash", "drive")
CLASSES = (*TARGET_FAMILIES, "other", "serve")
SIDES = ("forehand", "backhand")


def _class(item):
    return "serve" if item.get("kind") == "serve" else item.get("family")


def _confusion_metrics(matrix, labels):
    per_class = {}
    for label in labels:
        tp = matrix[label][label]
        fn = sum(matrix[label].values()) - tp
        fp = sum(row[label] for name, row in matrix.items() if name != label)
        per_class[label] = _metrics(tp, fp, fn) | {"support": tp + fn}
    supported = [label for label in labels if per_class[label]["support"]]
    return {
        "per_class": per_class,
        "supported_classes": supported,
        "unsupported_classes": [label for label in labels if label not in supported],
        "macro_f1_supported": sum(per_class[label]["f1"] for label in supported)
        / len(supported)
        if supported
        else None,
    }


def evaluate_recognition(video, annotations, run, tolerance_s=0.12):
    """Score independent reviewed contacts, explicitly conditioning on input times.

    Timing coverage and one-to-one matching follow the contact evaluator. Missing
    predictions and abstentions count as unanswered, not correct classifications.
    Labels carrying classification provenance are excluded from accuracy metrics,
    including manually corrected model drafts, to avoid scoring a model against
    its own assisted labels. They remain contacts for matching/FP exclusion.
    """
    if run.get("stage") != "recognition" or run.get("video_sha256") != video["sha256"]:
        raise ValueError("Recognition artifact must match the source video and hash")
    candidates = []
    for candidate in run["candidates"]:
        if candidate.get("status") not in ("predicted", "abstained"):
            raise ValueError(
                "Recognition candidates require predicted/abstained status"
            )
        if candidate["status"] == "predicted" and _class(candidate) not in CLASSES:
            raise ValueError("Predicted recognition class is not supported")
        if candidate.get("side", "unknown") not in (*SIDES, "unknown"):
            raise ValueError("Recognition stroke side is not supported")
        candidates.append(
            candidate
            | {
                "start_frame": candidate.get("contact_start_frame")
                if candidate.get("contact_start_frame") is not None
                else candidate["frame"],
                "end_frame": candidate.get("contact_end_frame")
                if candidate.get("contact_end_frame") is not None
                else candidate["frame"],
            }
        )
    contact_view = run | {"stage": "contacts", "candidates": candidates}
    timing = evaluate_contacts(video, annotations, contact_view, tolerance_s)
    ranges = timing["coverage"]["frame_ranges"]

    def included(frame):
        return any(left <= frame < right for left, right in ranges)

    events = {
        e["id"]: e
        for e in annotations["events"]
        if e["kind"] in ("serve", "shot")
        and e["status"] in ("reviewed", "corrected")
        and included(e["frame"])
    }
    by_id = {c["id"]: c for c in candidates if included(c["frame"])}
    matches = {m["event_id"]: m["candidate_id"] for m in timing.get("matches", [])}
    matched_predictions = set(matches.values())
    matrix = {
        truth: dict.fromkeys((*CLASSES, "unanswered"), 0)
        for truth in (*CLASSES, "no_contact")
    }
    side_matrix = {truth: dict.fromkeys((*SIDES, "unanswered"), 0) for truth in SIDES}
    assisted, unknown_family, known_family, answered = [], [], [], []
    details, joint_truth, joint_correct = [], [], []
    known_hitters, correct_hitters = 0, 0
    for event_id, event in events.items():
        candidate_id = matches.get(event_id)
        candidate = by_id.get(candidate_id)
        if event.get("classification_run_id"):
            assisted.append(event_id)
            continue
        predicted = candidate is not None and candidate["status"] == "predicted"
        truth = _class(event)
        prediction = _class(candidate) if predicted else "unanswered"
        if truth in CLASSES:
            known_family.append(event_id)
            matrix[truth][prediction] += 1
            if predicted:
                answered.append(event_id)
        else:
            unknown_family.append(event_id)
        true_side = event.get("side")
        predicted_side = candidate.get("side", "unknown") if predicted else "unknown"
        if true_side in SIDES:
            side_matrix[true_side][
                predicted_side if predicted_side in SIDES else "unanswered"
            ] += 1
        true_player = event.get("player_id")
        predicted_player = (
            (candidate.get("hitter_hint") or {}).get("player_id") if predicted else None
        )
        if true_player is not None:
            known_hitters += 1
            correct_hitters += int(true_player == predicted_player)
        joint_eligible = (
            truth in CLASSES and true_side in SIDES and true_player is not None
        )
        if joint_eligible:
            joint_truth.append(event_id)
            if (
                predicted
                and prediction == truth
                and predicted_side == true_side
                and predicted_player == true_player
                and not _uncertain_candidate(candidate)
            ):
                joint_correct.append(candidate_id)
        details.append(
            {
                "event_id": event_id,
                "candidate_id": candidate_id,
                "true_class": truth,
                "predicted_class": prediction,
                "true_side": true_side,
                "predicted_side": predicted_side,
                "true_player": true_player,
                "predicted_player": predicted_player,
                "joint_label_eligible": joint_eligible,
            }
        )
    for candidate_id, candidate in by_id.items():
        if (
            candidate_id not in matched_predictions
            and candidate["status"] == "predicted"
        ):
            matrix["no_contact"][_class(candidate)] += 1
    family = _confusion_metrics(matrix, TARGET_FAMILIES)
    side = _confusion_metrics(side_matrix, SIDES)
    side["balanced_accuracy"] = (
        sum(side["per_class"][label]["recall"] for label in SIDES) / 2
        if len(side["supported_classes"]) == 2
        else None
    )
    # Joint FP counts only fully specified outputs in the eligible domain. Matched
    # unknown/assisted truth never becomes an FP merely for lacking gold labels.
    joint_domain = {matches[e] for e in joint_truth if e in matches} | (
        set(by_id) - matched_predictions
    )
    complete_claims = [
        c["id"]
        for c in by_id.values()
        if c["id"] in joint_domain
        and c["status"] == "predicted"
        and c.get("side") in SIDES
        and (c.get("hitter_hint") or {}).get("player_id") is not None
    ]
    result = {
        key: timing[key]
        for key in (
            "video_id",
            "video_sha256",
            "annotation_revision",
            "run_id",
            "run_start_frame",
            "run_end_frame",
            "coverage",
            "tolerance_s",
        )
    }
    result.update(
        {
            "stage": "recognition",
            "checkpoint_sha256": run.get("checkpoint_sha256"),
            "input_annotation_revision": run.get("annotation_revision"),
            "status": "scored"
            if known_family
            else "needs_independent_family_labels"
            if ranges
            else "needs_complete_live_review",
            "meaning": "Classification conditional on supplied contacts and reviewed track-player mappings; this is not an unattended full-video accuracy result",
            "contact_inputs": {
                "reviewed_event_targets": sum(
                    c.get("event_id") is not None for c in by_id.values()
                ),
                "proposal_targets": sum(
                    c.get("event_id") is None for c in by_id.values()
                ),
            },
            "labels": {
                "known_family_event_ids": known_family,
                "unknown_family_event_ids": unknown_family,
                "excluded_model_assisted_event_ids": assisted,
            },
            "family": family
            | {
                "known_contact_count": len(known_family),
                "answered_contact_count": len(answered),
                "coverage": len(answered) / len(known_family) if known_family else None,
                "macro_f1_all_six": family["macro_f1_supported"]
                if len(family["supported_classes"]) == 6
                else None,
                "confusion": matrix,
                "other_and_serve": _confusion_metrics(matrix, ("other", "serve"))[
                    "per_class"
                ],
            },
            "side": side | {"confusion": side_matrix},
            "hitter": {
                "known_contact_count": known_hitters,
                "correct_count": correct_hitters,
                "accuracy_including_unanswered": correct_hitters / known_hitters
                if known_hitters
                else None,
            },
            "complete_event": _metrics(
                len(joint_correct),
                len(complete_claims) - len(joint_correct),
                len(joint_truth) - len(joint_correct),
            )
            if joint_truth
            else None,
            "complete_event_label_count": len(joint_truth),
            "matches": details,
            "unmatched_candidate_ids": [
                identifier
                for identifier in by_id
                if identifier not in matched_predictions
            ],
            "unmatched_prediction_class_counts": dict(
                Counter(
                    _class(c)
                    for c in by_id.values()
                    if c["id"] not in matched_predictions and c["status"] == "predicted"
                )
            ),
        }
    )
    return result
