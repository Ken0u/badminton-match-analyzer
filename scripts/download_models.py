"""Fetch pinned player/shuttle checkpoints and record their provenance."""

import argparse
import hashlib
import json
import zipfile
from urllib.request import urlopen

from badminton.config import MODEL_MANIFEST, WEIGHTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kind", choices=["player", "shuttle", "all"], default="player"
    )
    args = parser.parse_args()
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    folder = WEIGHTS
    folder.mkdir(parents=True, exist_ok=True)
    for kind in ["player", "shuttle"] if args.kind == "all" else [args.kind]:
        entry = manifest["player_pose" if kind == "player" else "shuttle"]
        target = folder / entry["name"]
        if not target.exists():
            temp = target.with_suffix(".download")
            if kind == "player":
                with (
                    urlopen(entry["source"], timeout=60) as response,
                    temp.open("wb") as out,
                ):
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        out.write(chunk)
            else:
                import gdown

                archive = folder / "TrackNetV3_ckpts.zip"
                if not archive.exists():
                    partial = archive.with_suffix(".download")
                    result = gdown.download(
                        id="1CfzE87a0f6LhBp0kniSl1-89zaLCZ8cA",
                        output=str(partial),
                        use_cookies=False,
                    )
                    if result is None:
                        raise RuntimeError(
                            "Unable to download the official shuttle checkpoint"
                        )
                    partial.replace(archive)
                with zipfile.ZipFile(archive) as z:
                    temp.write_bytes(z.read(entry["archive_member"]))
            if hashlib.sha256(temp.read_bytes()).hexdigest() != entry["sha256"]:
                raise RuntimeError(
                    "Downloaded checkpoint did not match the pinned checksum"
                )
            temp.replace(target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry["sha256"]:
            raise RuntimeError("Local checkpoint did not match the pinned checksum")
        (folder / (target.stem + ".manifest.json")).write_text(
            json.dumps(entry, indent=2), encoding="utf-8"
        )
        print(json.dumps(entry, indent=2))


if __name__ == "__main__":
    main()
