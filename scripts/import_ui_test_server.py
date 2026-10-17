"""Empty isolated import UI server with generated media and a YouTube stub.

Run this helper, then ``node tests/import-browser.mjs``. Each invocation creates
a fresh directory under .cache/import-ui-test-data; sample catalogs are untouched.
The stub exercises the real import queue/ingester without a network download.
"""

import io
import os
import time
from uuid import uuid4

import av
import numpy as np
import uvicorn
from badminton import media_import
from badminton.api import create_app
from badminton.config import ROOT
from badminton.video import write_json


def fixture(path, color):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width = stream.height = 32
        stream.pix_fmt = "yuv420p"
        for index in range(25):
            image = np.zeros((32, 32, 3), np.uint8)
            image[:, :, color] = 60 + index * 5
            frame = av.VideoFrame.from_ndarray(image, format="rgb24")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


if __name__ == "__main__":
    base = ROOT / ".cache" / "import-ui-test-data"
    root = base / uuid4().hex
    root.mkdir(parents=True)
    upload_fixture = root / "upload-fixture.mp4"
    youtube_fixture = root / "youtube-fixture.mp4"
    fixture(upload_fixture, 1)
    fixture(youtube_fixture, 2)
    (root / "not-a-video.mp4").write_text("QA invalid video bytes", encoding="utf-8")

    def download_youtube(url, media_root, max_bytes, progress):
        canonical = media_import.canonical_youtube_url(url)
        progress(0.1)
        time.sleep(0.15)
        path = media_import.save_upload(
            io.BytesIO(youtube_fixture.read_bytes()),
            youtube_fixture.name,
            media_root,
            max_bytes=max_bytes,
        )
        progress(1)
        return path, {
            "source_type": "youtube",
            "url": canonical,
            "id": canonical.rsplit("=", 1)[1],
            "title": "QA YouTube fixture",
            "channel": "Generated interface test media",
        }

    media_import.download_youtube = download_youtube
    write_json(
        base / "current-fixtures.json",
        {
            "root": str(root),
            "upload": str(upload_fixture),
            "invalid": str(root / "not-a-video.mp4"),
            "pid": os.getpid(),
            "port": 8002,
        },
    )
    # Explicit blank credentials keep this local fixture server independent of
    # credentials configured for a real app instance.
    app = create_app(root, root / "processed", username="", password="")
    uvicorn.run(app, host="127.0.0.1", port=8002)
