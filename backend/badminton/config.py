import os
from pathlib import Path

ROOT = Path(
    os.environ.get("BADMINTON_ROOT", Path(__file__).resolve().parents[2])
).resolve()
DATA = Path(os.environ.get("BADMINTON_DATA_DIR", ROOT / "data" / "processed"))
WEIGHTS = Path(os.environ.get("BADMINTON_WEIGHTS_DIR", ROOT / "models" / "weights"))
MAX_MEDIA_BYTES = int(os.environ.get("BADMINTON_MAX_MEDIA_BYTES", 2 * 1024**3))
MODEL_MANIFEST = Path(__file__).with_name("model_manifest.json")
