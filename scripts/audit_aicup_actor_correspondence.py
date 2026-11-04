"""Freeze, audit or verify weak AI CUP image-foot/native-pose correspondence."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.aicup_actor_correspondence import main

if __name__ == "__main__":
    main()
