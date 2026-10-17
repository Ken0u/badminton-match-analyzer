"""Experimental pretrained singles family proposals with immutable provenance."""

import hashlib
import json
import time

import numpy as np

from .config import MODEL_MANIFEST, WEIGHTS
from .identity import resolve_contact_player
from .stroke_features import build_stroke_clip, summarize_probabilities
from .video import write_json


def recognition_targets(
    annotations,
    contact_run=None,
    include_reviewed=True,
    start_frame=None,
    end_frame=None,
):
    targets = []
    reviewed_frames = set()
    if include_reviewed:
        for event in annotations.events:
            if event.kind != "shot" or event.status not in ("reviewed", "corrected"):
                continue
            reviewed_frames.add(event.frame)
            targets.append(
                {
                    "frame": event.frame,
                    "event_id": event.id,
                    "player_id": event.player_id,
                    "contact_candidate_id": None,
                    "contact_start_frame": event.contact_start_frame,
                    "contact_end_frame": event.contact_end_frame,
                }
            )
    for candidate in contact_run.get("candidates", []) if contact_run else []:
        if any(
            candidate.get("start_frame", candidate["frame"])
            <= frame
            <= candidate.get("end_frame", candidate["frame"])
            for frame in reviewed_frames
        ):
            continue
        targets.append(
            {
                "frame": candidate["frame"],
                "event_id": None,
                "player_id": None,
                "contact_candidate_id": candidate["id"],
                "contact_start_frame": candidate.get("start_frame")
                if candidate.get("timing") == "uncertain_interval"
                else None,
                "contact_end_frame": candidate.get("end_frame")
                if candidate.get("timing") == "uncertain_interval"
                else None,
            }
        )
    for target in targets:
        key = f"{target['frame']}:{target['event_id']}:{target['contact_candidate_id']}"
        target["id"] = "stroke-" + hashlib.sha256(key.encode()).hexdigest()[:16]
    return sorted(
        (
            target
            for target in targets
            if (start_frame is None or target["frame"] >= start_frame)
            and (end_frame is None or target["frame"] < end_frame)
        ),
        key=lambda target: target["frame"],
    )


def recognize_strokes(
    video,
    times,
    annotations,
    player_run,
    shuttle_run,
    targets,
    player_run_id,
    progress,
    output,
    min_family_score=0.5,
    contacts_run_id=None,
):
    if not 0 <= min_family_score <= 1 or not np.isfinite(min_family_score):
        raise ValueError(
            "Family score threshold must be finite and between zero and one"
        )
    if video["mode"] != "singles":
        raise ValueError("The current pretrained classifier supports singles only")
    try:
        import torch

        from .vendor.bst.bst import BST_0
    except ImportError as exc:
        raise RuntimeError(
            "Install the tracking and recognition dependencies before classifying shots"
        ) from exc
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))["shot_classifier"]
    path = WEIGHTS / manifest["name"]
    if not path.is_file():
        raise RuntimeError(
            "Stroke model missing. Run scripts/download_models.py --kind stroke"
        )
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("Stroke checkpoint does not match the pinned model manifest")
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    model = BST_0(in_dim=72, seq_len=30, n_class=35)
    try:
        model.load_state_dict(
            torch.load(path, map_location="cpu", weights_only=True), strict=True
        )
        model = model.to(device).eval()
        candidates = []
        began = time.perf_counter()
        with torch.inference_mode():
            for number, target in enumerate(targets):
                clip = build_stroke_clip(
                    video,
                    times,
                    player_run,
                    shuttle_run,
                    annotations.calibrations,
                    target["frame"],
                )
                private = {"pose", "shuttle", "length"}
                prediction = target | {
                    key: value for key, value in clip.items() if key not in private
                }
                if clip["status"] == "ready":
                    logits = model(
                        torch.from_numpy(clip["pose"]).unsqueeze(0).to(device),
                        torch.from_numpy(clip["shuttle"]).unsqueeze(0).to(device),
                        torch.tensor([clip["length"]], device=device),
                    )
                    scores = torch.softmax(logits.float(), dim=1)[0].cpu().numpy()
                    summary = summarize_probabilities(scores)
                    prediction.update(summary)
                    known_family = summary["family"] != "unknown"
                    prediction.update(
                        status="predicted"
                        if known_family and summary["family_score"] >= min_family_score
                        else "abstained"
                    )
                    if prediction["status"] == "abstained":
                        prediction["reason"] = (
                            "The classifier did not separate a family confidently enough; inspect its ranked alternatives"
                        )
                    court_end = summary["top_classes"][0]["court_end"]
                    hint_track = clip["contact_tracks"].get(court_end)
                    prediction["hitter_hint"] = {
                        "court_end": court_end,
                        "track_id": hint_track,
                        "player_id": resolve_contact_player(
                            target["frame"],
                            hint_track,
                            annotations.track_assignments,
                            player_run_id,
                        ),
                    }
                candidates.append(prediction)
                progress((number + 1) / max(1, len(targets)))
        result = {
            "schema_version": 1,
            "stage": "recognition",
            "video_id": video["id"],
            "video_sha256": video["sha256"],
            "annotation_revision": annotations.revision,
            "model": "BST-0 singles ShuttleSet 35-class",
            "checkpoint_sha256": manifest["sha256"],
            "device": device,
            "min_family_score": min_family_score,
            "sequence_length": 30,
            "pose_adapter": "YOLO COCO-17 to published MMPose normalization; domain transfer unvalidated",
            "side_model": None,
            "player_run_id": player_run_id,
            "shuttle_run_id": shuttle_run.get("run_id"),
            "contacts_run_id": contacts_run_id,
            "start_frame": max(player_run["start_frame"], shuttle_run["start_frame"]),
            "end_frame": min(player_run["end_frame"], shuttle_run["end_frame"]),
            "score_meaning": "uncalibrated family softmax mass; not verified accuracy",
            "elapsed_s": round(time.perf_counter() - began, 3),
            "candidates": candidates,
            "candidate_count": len(candidates),
            "predicted_count": sum(c["status"] == "predicted" for c in candidates),
        }
        write_json(output, result)
        return {key: value for key, value in result.items() if key != "candidates"}
    finally:
        del model
        if device.startswith("cuda"):
            torch.cuda.empty_cache()
