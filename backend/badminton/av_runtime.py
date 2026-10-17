"""App-owned media contexts must not call Python from FFmpeg worker logs."""

from contextlib import contextmanager

import av


@contextmanager
def open_media(*args, **kwargs):
    """Keep FFmpeg logging native while opening/closing a media container.

    Python callbacks can wait for the GIL while decoder teardown holds it and
    waits for the worker. Torchvision installs such a callback on import, so
    resetting only once at app startup is insufficient. Initialize inference
    libraries before opening threaded decoders. Native FFmpeg errors remain on
    stderr; container/decode exceptions still propagate to the caller.
    """
    av.logging.restore_default_callback()
    with av.open(*args, **kwargs) as container:
        try:
            yield container
        finally:
            av.logging.restore_default_callback()
