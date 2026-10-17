"""Prepare source-verified published descriptors for the stroke-side baseline."""

import argparse
import subprocess
from pathlib import Path

from badminton.config import DATA
from badminton.jobs import run_local_job
from badminton.storage import Store
from badminton.training_features import (
    file_sha,
    inspect_feature_archive,
    prepare_side_descriptors,
    training_recipe,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("data/datasets/shuttleset/v1")
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("data/datasets/shuttleset/published-features/dataset_npy.rar"),
    )
    parser.add_argument("--extractor", type=Path, required=True)
    parser.add_argument(
        "--extracted",
        type=Path,
        default=Path("data/datasets/shuttleset/published-features/extracted"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/datasets/shuttleset/side-descriptors-v1"),
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Extract after inspecting every archive path",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the pinned published archive if absent",
    )
    args = parser.parse_args()
    if args.download and not args.archive.exists():
        import gdown

        recipe = training_recipe()
        args.archive.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.archive.with_suffix(".download")
        result = gdown.download(
            id=recipe["feature_archive"]["google_drive_id"],
            output=str(temporary),
            use_cookies=False,
            resume=True,
        )
        if result is None or file_sha(temporary) != recipe["feature_archive"]["sha256"]:
            raise RuntimeError(
                "Published feature download does not match its pinned checksum"
            )
        temporary.replace(args.archive)
    members = inspect_feature_archive(args.archive, args.extractor, args.extracted)
    if args.extract:
        args.extracted.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                str(args.extractor),
                "x",
                str(args.archive),
                "-o" + str(args.extracted),
                "-y",
                "-bsp0",
                "-bso0",
            ],
            check=True,
        )
    result = run_local_job(
        Store(DATA),
        "feature-preparation",
        None,
        lambda job_id, progress: prepare_side_descriptors(
            args.dataset,
            args.extracted,
            members,
            args.output,
            progress=lambda message: print(message, flush=True),
            report_progress=progress,
        ),
    )
    print(
        f"Prepared {result['record_count']} source-verified descriptors: {result['split_counts']}"
    )
