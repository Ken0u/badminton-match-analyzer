"""Isolated generated-media boundary review QA; no sample files or weights."""

import sys
from pathlib import Path
from tempfile import mkdtemp

import uvicorn
from badminton.api import create_app
from badminton.config import ROOT

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from rally_fixture import catalog

if __name__ == "__main__":
    parent = ROOT / ".cache" / "rally-ui-test-data"
    parent.mkdir(parents=True, exist_ok=True)
    root = Path(mkdtemp(prefix="run-", dir=parent))
    data = root / "processed"
    catalog(root, data)
    print(f"Isolated rally QA data: {root}", flush=True)
    uvicorn.run(create_app(root, data), host="127.0.0.1", port=8003)
