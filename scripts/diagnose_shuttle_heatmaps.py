"""Capture and interpret frozen development heatmaps under real admission."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.shuttle_heatmaps import main

if __name__ == "__main__":
    main()
