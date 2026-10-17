"""Fetch verified public annotation CSVs; no videos or model trajectories."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen
from uuid import uuid4

from badminton.datasets import blob_sha, source_path
from badminton.doubles_data import pinned_source


def fetch_source(output):
    spec = pinned_source()

    def fetch(item):
        relative, expected = item
        path = source_path(output, relative)
        if path.is_file() and blob_sha(path.read_bytes()) == expected:
            return
        url = f"https://raw.githubusercontent.com/{spec['repository']}/{spec['commit']}/{quote(relative)}"
        with urlopen(url, timeout=30) as response:
            data = response.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024 or blob_sha(data) != expected:
            raise ValueError(f"Source size/hash mismatch: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f".{uuid4().hex}.tmp")
        try:
            temp.write_bytes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, spec["files"].items()))
    print(f"Verified {len(spec['files'])} pinned annotation/metadata files in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/datasets/s2doubles/source") / pinned_source()["commit"],
    )
    fetch_source(parser.parse_args().output)
