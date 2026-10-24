"""Compare explicit pinned local label revisions; never acquire research inputs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.shuttle_label_comparison import main

if __name__ == "__main__":
    main()
