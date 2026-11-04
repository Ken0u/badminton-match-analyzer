"""Fixed private static/temporal pose study; no model installation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from badminton.aicup_pose_learning import main

if __name__ == "__main__":
    main()
