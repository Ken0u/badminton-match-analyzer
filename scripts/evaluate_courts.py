"""Compare court fits with frozen development references, never exact match truth."""

import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from badminton.court_detection import METHOD, detect_court
from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/manifests/court_detector_development.json"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; preserve previous evaluations")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True)
    reports = []
    for case in manifest["cases"]:
        path = Path(case["image_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["image_sha256"]:
            raise ValueError(f"Image bytes changed: {case['id']}")
        with Image.open(path) as source:
            image = source.convert("RGB")
        result = detect_court(np.asarray(image))
        iou = error = None
        reference = case["reference_corners_pixels"]
        if reference:
            ImageDraw.Draw(image).line(
                [tuple(p) for p in reference] + [tuple(reference[0])],
                fill="cyan",
                width=3,
            )
        if result["corners"] is not None:
            predicted = np.asarray(result["corners"], np.float32) * np.array(
                image.size, np.float32
            )
            poly = [tuple(p) for p in predicted]
            ImageDraw.Draw(image).line([*poly, poly[0]], fill="magenta", width=3)
            if reference:
                ref = np.asarray(reference, np.float32)
                intersection = cv2.intersectConvexConvex(predicted, ref)[0]
                iou = float(
                    intersection
                    / (
                        abs(cv2.contourArea(predicted))
                        + abs(cv2.contourArea(ref))
                        - intersection
                    )
                )
                error = float(np.linalg.norm(predicted - ref, axis=1).mean())
        image.save(args.output / f"{case['id']}.jpg", quality=92)
        reports.append(
            {
                "case": case["id"],
                "expected_full_court": case["expected_full_court"],
                "iou_against_weak_reference": iou,
                "mean_corner_error_px": error,
                "detector": result,
            }
        )
        print(
            case["id"],
            result["status"],
            "corner_error_px",
            round(error, 2) if error is not None else None,
            flush=True,
        )
    (args.output / "evaluation.json").write_text(
        json.dumps(
            {"method": METHOD, "truth": manifest["purpose"], "reports": reports},
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
