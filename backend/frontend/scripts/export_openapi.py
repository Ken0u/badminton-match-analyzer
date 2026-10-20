"""Export the actual application schema without touching an existing catalog."""

import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[3]
    with tempfile.TemporaryDirectory(prefix="badminton-openapi-") as temporary:
        temporary_root = Path(temporary).resolve()
        data = temporary_root / "processed"
        # Configuration has import-time defaults. Pin these before any backend import.
        os.environ["BADMINTON_ROOT"] = str(root)
        os.environ["BADMINTON_DATA_DIR"] = str(data)
        os.environ["BADMINTON_EXPORT_DIR"] = str(temporary_root / "exports")
        os.environ.pop("BADMINTON_USERNAME", None)
        os.environ.pop("BADMINTON_PASSWORD", None)
        sys.path.insert(0, str(root / "backend"))
        from badminton.api import create_app

        app = create_app(root=root, data=data)
        # No lifespan/startup, workers, HTTP listener or inference is started.
        sys.stdout.write(json.dumps(app.openapi(), sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
