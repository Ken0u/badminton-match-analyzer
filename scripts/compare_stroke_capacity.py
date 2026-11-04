"""Compare two frozen development classifiers without accessing test sources."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.stroke_capacity import main

if __name__ == "__main__":
    main()
