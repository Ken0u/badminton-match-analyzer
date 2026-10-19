"""Generate a rotated VFR source for the existing isolated browser server."""

import sys
from pathlib import Path

from test_orientation import write_rotated_video

if __name__ == "__main__":
    path = Path(sys.argv[1]).resolve()
    cache = Path(__file__).resolve().parents[1] / ".cache"
    if not path.is_relative_to(cache):
        raise ValueError("Browser fixtures must stay inside this worktree's cache")
    path.parent.mkdir(parents=True, exist_ok=True)
    write_rotated_video(path, 90)
