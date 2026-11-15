"""OSNet for the training scripts: the app's copy, so both load the same weights.

The network lives in backend/badminton/osnet.py; this keeps `import osnet`
working for identity_probe.py, identity_preview.py, reid_crops.py and
finetune_reid.py.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.osnet import (
    MEAN,
    SIZE,
    SPREAD,
    OSNet,
    describe,
    load,
)

__all__ = ["MEAN", "SIZE", "SPREAD", "OSNet", "describe", "load"]
