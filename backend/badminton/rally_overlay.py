"""Deterministic saved-annotation overlays and audited annotated media exports."""

import copy
import hashlib

import av
import cv2
import numpy as np

from .rally_export import _canonical

OVERLAY_CONFIG = {
    "version": 2,
    "policy": "saved-reviewed-source-frames",
    "layering": "panel background, saved court edges, text, exact saved shuttle markers",
    "events": "reviewed/corrected native exact frames or inclusive uncertainty intervals",
    "predictions": "provenance only; excluded from burn-in",
    "shuttle": "visible saved positions on exact source frames only",
    "calibration": "saved range expires at next saved camera cut; no derived geometry",
    "identities": "saved event hitter only; no unavailable player positions",
    "text": "OpenCV Hershey Simplex; Unicode escaped as ASCII; wrapped; opaque top panel",
    "regions": "top text panel, exact shuttle circles and valid calibration edges; 16px codec verification guard",
    "colors_rgb": {
        "text": [255, 255, 255],
        "court": [0, 220, 255],
        "shuttle": [255, 220, 0],
    },
}


def _event_record(event, snapshot):
    prefix = "terminal" if event["kind"] == "rally_end" else "contact"
    uncertain = event.get(f"{prefix}_start_frame") is not None
    start = event[f"{prefix}_start_frame"] if uncertain else event["frame"]
    end = event[f"{prefix}_end_frame"] if uncertain else event["frame"]
    player = next(
        (p for p in snapshot["players"] if p["id"] == event.get("player_id")), None
    )
    hitter = f"{player['id']} ({player['name'] or 'unknown'})" if player else "unknown"
    text = f"{event['kind']} rally={event['rally_id']}"
    if event["kind"] != "rally_end":
        text += f" hitter={hitter}"
    if event["kind"] == "shot":
        text += f" family={event.get('family') or 'unknown'}"
    if event["kind"] != "rally_end":
        text += f" side={event.get('side') or 'unknown'}"
    text += (
        f" uncertain interval [{start},{end}]" if uncertain else f" exact frame {start}"
    )
    return {
        "id": event["id"],
        "kind": event["kind"],
        "status": event["status"],
        "uncertain": uncertain,
        "start_frame": start,
        "end_frame_inclusive": end,
        "text": text,
    }


def overlay_context(snapshot, frame_index):
    """Describe only saved evidence applicable to this exact native frame."""
    events = []
    for event in snapshot["events"]:
        if event["status"] not in ("reviewed", "corrected"):
            continue
        record = _event_record(event, snapshot)
        if record["start_frame"] <= frame_index <= record["end_frame_inclusive"]:
            events.append(record)
    scene = next(
        (
            s["scene"]
            for s in snapshot["scene_ranges"]
            if s["start_frame"] <= frame_index < s["end_frame"]
        ),
        "unknown",
    )
    cuts = [c["frame"] for c in snapshot["camera_corrections"] if c["is_cut"]]
    calibration = None
    for candidate in snapshot["calibrations"]:
        end = min(
            [
                candidate["end_frame"],
                *[cut for cut in cuts if candidate["start_frame"] < cut],
            ]
        )
        if candidate["start_frame"] <= frame_index < end:
            calibration = copy.deepcopy(candidate) | {"effective_end_frame": end}
            break
    camera = next(
        (c for c in snapshot["camera_corrections"] if c["frame"] == frame_index), None
    )
    shuttle = [
        copy.deepcopy(p)
        for p in snapshot["shuttle_points"]
        if p["frame"] == frame_index and p["visible"]
    ]
    return {
        "frame": frame_index,
        "events": events,
        "scene": scene,
        "camera_cut": frame_index in cuts,
        "camera_correction": copy.deepcopy(camera),
        "preceding_camera_cut": max(
            (c for c in cuts if c <= frame_index), default=None
        ),
        "calibration": calibration,
        "shuttle_points": shuttle,
        "player_positions": "unavailable",
        "text": [
            f"Frame {frame_index} scene={scene} court={'saved' if calibration else 'unavailable'} player positions unavailable",
            *(["Reviewed camera cut"] if frame_index in cuts else []),
            *(
                ["Reviewed camera: not a cut"]
                if camera and not camera["is_cut"]
                else []
            ),
            *[e["text"] for e in events],
        ],
    }


def overlay_frame(pixels, snapshot, frame_index):
    """Return (RGB pixels, exact changed-region boolean mask, saved context).

    The source pixels must already be display-oriented. Geometry uses normalized
    saved display coordinates. No tracking files or inferred positions are read.
    """
    source_frame = pixels if isinstance(pixels, av.VideoFrame) else None
    if source_frame is not None:
        pixels = source_frame.to_ndarray(format="rgb24")
    result = np.array(pixels, dtype=np.uint8, copy=True)
    height, width = result.shape[:2]
    mask = np.zeros((height, width), dtype=np.uint8)
    context = overlay_context(snapshot, frame_index)
    scale = max(0.25, min(0.65, width / 1000))
    thickness = 1
    line_height = max(10, round(22 * scale / 0.5))
    # Wrap every record rather than silently truncating unknown labels/intervals.
    lines = []
    for text in context["text"]:
        text = text.encode("ascii", "backslashreplace").decode("ascii")
        line = ""
        for word in text.split():
            proposed = (line + " " + word).strip()
            if (
                cv2.getTextSize(proposed, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[
                    0
                ][0]
                <= width - 8
            ):
                line = proposed
                continue
            if line:
                lines.append(line)
                line = ""
            # Keep ordinary words together, but retain long unbroken names/IDs
            # by splitting only tokens that cannot fit on an empty line.
            while (
                word
                and cv2.getTextSize(word, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)[
                    0
                ][0]
                > width - 8
            ):
                length = 1
                while (
                    length < len(word)
                    and cv2.getTextSize(
                        word[: length + 1], cv2.FONT_HERSHEY_SIMPLEX, scale, thickness
                    )[0][0]
                    <= width - 8
                ):
                    length += 1
                lines.append(word[:length])
                word = word[length:]
            line = word
        if line:
            lines.append(line)
    panel_height = min(height // 2, max(line_height + 4, len(lines) * line_height + 4))
    # At very small resolutions text is proportionally reduced to retain the
    # complete evidence, keeping at least half the source outside the panel.
    if len(lines) * line_height + 4 > panel_height:
        factor = max(0.05, (panel_height - 4) / max(1, len(lines) * line_height))
        scale *= factor
        line_height = max(1, (panel_height - 4) // max(1, len(lines)))
    # Compose the opaque background first, preserving saved spatial evidence
    # even when its native coordinates intersect the text panel.
    result[:panel_height] = 0
    mask[:panel_height] = 1
    calibration = context["calibration"]
    if calibration:
        corners = np.array(
            [
                (round(p["x"] * (width - 1)), round(p["y"] * (height - 1)))
                for p in calibration["corners"]
            ],
            dtype=np.int32,
        )
        cv2.polylines(result, [corners], True, (0, 220, 255), 2, cv2.LINE_8)
        cv2.polylines(mask, [corners], True, 1, 2, cv2.LINE_8)
    for index, text in enumerate(lines):
        cv2.putText(
            result[:panel_height],
            text,
            (3, min(panel_height - 1, (index + 1) * line_height)),
            cv2.FONT_HERSHEY_SIMPLEX,
            scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_8,
        )
    # Exact saved shuttle positions take visual priority over text glyphs.
    for point in context["shuttle_points"]:
        center = (round(point["x"] * (width - 1)), round(point["y"] * (height - 1)))
        cv2.circle(result, center, 4, (255, 220, 0), 2, cv2.LINE_8)
        cv2.circle(mask, center, 4, 1, 2, cv2.LINE_8)
    if source_frame is not None:
        rendered = av.VideoFrame.from_ndarray(result, format="rgb24")
        rendered.pts, rendered.time_base = source_frame.pts, source_frame.time_base
        return rendered, mask.astype(bool), context
    return result, mask.astype(bool), context


class _SavedOverlay:
    def __init__(self, snapshot):
        self.snapshot = copy.deepcopy(snapshot)
        self.config = copy.deepcopy(OVERLAY_CONFIG)
        self.config_sha256 = hashlib.sha256(_canonical(self.config)).hexdigest()

    def draw(self, pixels, index):
        return overlay_frame(pixels, self.snapshot, index)

    def event_receipt(self, intervals):
        records = []
        for event in self.snapshot["events"]:
            record = _event_record(event, self.snapshot)
            reason = None
            if event["status"] not in ("reviewed", "corrected"):
                reason = "predicted_not_reviewed_truth"
            elif not any(
                max(start, record["start_frame"])
                < min(end, record["end_frame_inclusive"] + 1)
                for start, end in intervals
            ):
                reason = "outside_exported_ranges"
            records.append(record | {"included": reason is None, "reason": reason})
        included = sum(e["included"] for e in records)
        return {
            "total": len(records),
            "included": included,
            "excluded": len(records) - included,
            "events": records,
        }


def render_annotated_videos(
    store, plan, root, output, *, scope="full", progress=lambda value: None
):
    """Burn selected saved evidence into full source media or eligible rallies."""
    from .rally_video import _render_videos

    if scope not in ("full", "rallies"):
        raise ValueError("Annotated export scope must be full or rallies")
    return _render_videos(
        store,
        plan,
        root,
        output,
        progress,
        overlay=_SavedOverlay(plan["annotations"]),
        scope=scope,
    )
