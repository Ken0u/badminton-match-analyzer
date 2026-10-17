"""Download only pinned public labels/metadata; no match videos or model outputs."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import uuid4

from badminton.datasets import blob_sha, pinned_source, source_path


def fetch_source(output):
    spec = pinned_source()
    entries = [
        {
            "path": path,
            "repository": spec["repository"],
            "commit": spec["commit"],
            "source_path": path,
            "git_blob_sha1": sha,
        }
        for path, sha in spec["files"].items()
    ] + spec["references"]

    def fetch(entry):
        path = source_path(output, entry["path"])
        if path.is_file() and blob_sha(path.read_bytes()) == entry["git_blob_sha1"]:
            return
        url = f"https://raw.githubusercontent.com/{entry['repository']}/{entry['commit']}/{quote(entry['source_path'])}"
        request = Request(
            url, headers={"User-Agent": "badminton-source-label-importer"}
        )
        with urlopen(request, timeout=60) as response:
            data = response.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024 or blob_sha(data) != entry["git_blob_sha1"]:
            raise ValueError(f"Public source size/hash mismatch: {entry['path']}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            temp.write_bytes(data)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, entries))
    print(f"Verified {len(entries)} pinned label/metadata/reference files in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("data/datasets/shuttleset/source")
    )
    fetch_source(parser.parse_args().output)
