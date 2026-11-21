"""Fetch pinned player, shuttle, stroke and project-trained checkpoints."""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

from badminton.config import MODEL_MANIFEST, WEIGHTS

PROJECT_MODELS = Path(__file__).with_name("project_models.json")


def _sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def project_models(folder=None, index=PROJECT_MODELS, opener=urlopen):
    """Install this project's trained models from its Hugging Face repository."""
    folder = Path(folder or WEIGHTS)
    spec = json.loads(Path(index).read_text(encoding="utf-8"))
    base = f"https://huggingface.co/{spec['repository']}/resolve/{spec['revision']}"
    installed = []
    for entry in spec["models"]:
        target = folder / entry["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            temp = target.with_name(target.name + ".download")
            with opener(f"{base}/{quote(entry['path'])}", timeout=60) as response:
                with temp.open("wb") as out:
                    for chunk in iter(lambda: response.read(1024 * 1024), b""):
                        out.write(chunk)
            if _sha(temp) != entry["sha256"]:
                temp.unlink()
                raise RuntimeError(f"{entry['path']} did not match its pinned checksum")
            temp.replace(target)
        elif _sha(target) != entry["sha256"]:
            raise RuntimeError(
                f"Local {entry['path']} did not match its pinned checksum"
            )
        installed.append(entry["path"])
    return installed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kind",
        choices=["player", "shuttle", "stroke", "project", "all"],
        default="player",
    )
    parser.add_argument("--player-model", choices=["small", "nano"], default="small")
    args = parser.parse_args()
    manifest = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))
    folder = WEIGHTS
    folder.mkdir(parents=True, exist_ok=True)
    if args.kind in ("project", "all"):
        for path in project_models(folder):
            print(f"Installed {path}")
        if args.kind == "project":
            return
    for kind in ["player", "shuttle", "stroke"] if args.kind == "all" else [args.kind]:
        entry = manifest[
            {
                "player": "player_pose_small"
                if args.player_model == "small"
                else "player_pose",
                "shuttle": "shuttle",
                "stroke": "shot_classifier",
            }[kind]
        ]
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
            elif kind == "stroke":
                import gdown

                if (
                    gdown.download(
                        id=entry["google_drive_id"], output=str(temp), use_cookies=False
                    )
                    is None
                ):
                    raise RuntimeError(
                        "Unable to download the official stroke checkpoint"
                    )
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
