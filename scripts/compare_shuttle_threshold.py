"""Run the prospectively fixed offline development threshold comparison."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.shuttle_threshold_comparison import main

if __name__ == "__main__":
    main()
