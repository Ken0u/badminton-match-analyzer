"""Train the pinned experimental stroke-side head without test-set tuning."""

import argparse
from pathlib import Path

from badminton.config import DATA, WEIGHTS
from badminton.jobs import run_local_job
from badminton.storage import Store
from badminton.stroke_side import train_side_head

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--descriptors",
        type=Path,
        default=Path("data/datasets/shuttleset/side-descriptors-v1"),
    )
    parser.add_argument("--output", type=Path, default=WEIGHTS)
    args = parser.parse_args()
    result = run_local_job(
        Store(DATA),
        "side-training",
        None,
        lambda job_id, progress: train_side_head(
            args.descriptors,
            args.output,
            progress=lambda message: print(message, flush=True),
            report_progress=progress,
        ),
    )
    print("Validation balanced accuracy", result["validation"]["balanced_accuracy"])
    print("Frozen-test balanced accuracy", result["test"]["balanced_accuracy"])
