"""Run the frozen native diagnostic with original shared admission."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.shuttle_diagnostic import main

if __name__ == "__main__":
    main()
