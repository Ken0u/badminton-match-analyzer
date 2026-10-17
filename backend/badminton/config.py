import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("BADMINTON_DATA_DIR", ROOT / "data" / "processed"))
WEIGHTS = ROOT / "models" / "weights"
