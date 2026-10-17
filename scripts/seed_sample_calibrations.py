"""Add reviewed camera geometry only to the inspected baseline windows.

This does not create rally/contact labels or assign tracker IDs to players.
Existing calibrations and annotations are preserved.
"""

import json

from badminton.config import DATA, ROOT
from badminton.schemas import Calibration
from badminton.storage import Store

if __name__ == "__main__":
    store = Store(DATA)
    samples = json.loads(
        (ROOT / "data/manifests/samples.json").read_text(encoding="utf-8")
    )["videos"]
    expected = {sample["sha256"] for sample in samples}
    for video in store.videos():
        if video["sha256"] not in expected:
            continue
        start, end = (2000, 2250) if video["mode"] == "singles" else (600, 850)
        doc = store.annotations(video["id"])
        if not doc.calibrations:
            doc.calibrations.append(
                Calibration(
                    start_frame=start,
                    end_frame=end,
                    corners=[
                        {"x": x / 1280, "y": y / 720}
                        for x, y in ((437, 260), (842, 260), (994, 658), (289, 658))
                    ],
                )
            )
            store.save_annotations(video["id"], doc)
        video["review_start_frame"] = start
        store.register(video)
        print(video["name"], f"review window {start}:{end}")
