"""Prepare, run or verify the fixed AI CUP development pose-input pilot."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.aicup_pose_pilot import main

if __name__ == "__main__":
    main()
