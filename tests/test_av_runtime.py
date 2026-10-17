"""Native FFmpeg logging must not re-enter Python during threaded teardown."""

import json
import subprocess
import sys

import av
import numpy as np
import pytest
from badminton.av_runtime import open_media


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "threaded-decoder.mp4"
    with open_media(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=25)
        stream.width, stream.height = 160, 96
        stream.pix_fmt = "yuv420p"
        stream.options = {"bf": "3", "g": "25", "preset": "veryfast"}
        for i in range(120):
            frame = av.VideoFrame.from_ndarray(
                np.full((96, 160, 3), (i * 17) % 255, np.uint8), "rgb24"
            )
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path


def test_native_diagnostics_and_consumer_errors_survive_library_rehook(source):
    # A spawned process captures the Windows DLL's native stderr reliably;
    # redirecting Python's CRT fd after loading FFmpeg does not necessarily do so.
    # torchvision.io makes the same callback change simulated here.
    script = r"""
import json
import sys
import av
from badminton.av_runtime import open_media

av.logging.set_libav_level(av.logging.ERROR)
av.logging.set_level(av.logging.ERROR)
with open_media(sys.argv[1]) as container:
    assert next(container.decode(video=0)).width == 160
    with av.logging.Capture(local=False) as captured:
        av.logging.log(av.logging.ERROR, 'decoder-qa', 'native-error-sentinel\n')
    assert captured == []
try:
    with open_media(sys.argv[1]):
        av.logging.set_level(av.logging.ERROR)
        raise RuntimeError('consumer interrupted')
except RuntimeError as error:
    assert str(error) == 'consumer interrupted'
else:
    raise AssertionError('Consumer error was swallowed')
with av.logging.Capture(local=False) as captured:
    av.logging.log(av.logging.ERROR, 'decoder-qa', 'after-failure-sentinel\n')
assert captured == []
with open_media(sys.argv[1]) as container:
    assert next(container.decode(video=0)).height == 96
print(json.dumps({'native_diagnostics': True, 'consumer_error_preserved': True}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(source)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "native_diagnostics": True,
        "consumer_error_preserved": True,
    }
    assert "native-error-sentinel" in result.stderr
    assert "after-failure-sentinel" in result.stderr


def test_repeated_threaded_seek_and_early_close_finishes_in_subprocess(source):
    # A deadlock must fail with a bounded child timeout instead of hanging pytest.
    script = """
import gc
import json
import sys
import av
from badminton.av_runtime import open_media

counts=[]
for cycle in range(16):
    av.logging.set_level(av.logging.ERROR)
    with open_media(sys.argv[1]) as container:
        stream=container.streams.video[0]
        stream.thread_type='AUTO'
        stream.thread_count=4
        container.seek(int((cycle % 3) / stream.time_base), stream=stream, backward=True)
        count=0
        for frame in container.decode(stream):
            count+=1
            if count==4:
                break
        counts.append(count)
    gc.collect()
print(json.dumps(counts))
"""
    result = subprocess.run(
        [sys.executable, "-c", script, str(source)],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [4] * 16
