"""Extract perception, not predictions/labels, for the reserved 0058 development transfer probe."""

import gzip
import json
import os
from pathlib import Path

import numpy as np
import prepare_stroke_rgb as base
from badminton.ingest import inspect_video
from badminton.segments import scan_video
from badminton.shuttle import track_shuttle
from badminton.tracking import track_players
from badminton.video import timestamps_for
from extract_shuttleset import compact_players, compact_shuttle

exp = base.exp
OUT = exp.ROOT / ".cache/stroke-transfer-dev-0058"
SRC = exp.ROOT / ".cache/stroke-source-audit"
MATCH = "0058"


def protocol():
    meta = json.loads(
        (exp.ROOT / "backend/badminton/finebadminton_manifest.json").read_bytes()
    )
    row = next(x for x in meta["files"] if x["match_id"] == MATCH)
    source = SRC / (MATCH + ".mp4")
    refs = SRC / Path(row["path"]).name
    assert (
        base.digest(source) == row["media_sha256"]
        and base.digest(refs) == row["sha256"]
    )
    reserve = json.loads(
        (exp.ROOT / "docs/REVAMP_EXTERNAL_SINGLES_RESERVATION.json").read_bytes()
    )
    assert MATCH not in {
        r["match_id"]
        for r in [reserve["source"]]
        + [a["source"] for a in reserve["additional_reserved_matches"]]
    }
    data = json.loads(refs.read_bytes())
    bounds = [(r["start_frame"], r["end_frame"]) for r in data]
    assert len(bounds) == len(set(bounds)) == 15 and all(r["fps"] == 30 for r in data)
    return {
        "source": row,
        "role": "external development only, never fit or final acceptance; 2024 Korea Masters final Vitidsarn vs Wang Zheng Xing. Not either reserved tournament. Source-based rally boundaries; never use stroke boundaries, hitter, family, or court labels in extraction. Do not infer full-match event recall.",
        "revision": meta["dataset_revision"],
        "rallies_in_source_order": bounds,
        "pad_frames": 48,
        "script_sha": base.digest(Path(__file__)),
        "weights": {
            n: base.digest(exp.ROOT / "models/weights" / n)
            for n in ["yolo11s-pose.pt", "TrackNet_best.pt"]
        },
    }


def run(job, progress):
    spec = protocol()
    OUT.mkdir(exist_ok=True)
    path = OUT / "protocol.json"
    text = json.dumps(spec, indent=2)
    assert path.read_text() == text
    output = OUT / "features"
    output.mkdir(exist_ok=True)
    work = OUT / "perception"
    local = exp.Store(work)
    source = SRC / (MATCH + ".mp4")
    v = inspect_video(source, "singles", local, exp.ROOT, lambda f: progress(0.10 * f))
    assert v["sha256"] == spec["source"]["media_sha256"]
    times = np.array(timestamps_for(work, v["id"]))
    assert (
        len(times) == v["frame_count"]
        and np.max(abs(times - np.arange(len(times)) / 30)) < 0.001
    )
    scanfile = OUT / "scan.json"
    scan_video(v, exp.ROOT, work, lambda f: progress(0.1 + 0.1 * f), scanfile)
    scan = json.loads(scanfile.read_bytes())
    ann = local.annotations(v["id"])
    bounds = spec["rallies_in_source_order"]
    for i, (a, b) in enumerate(bounds):
        assert 0 <= a <= b < len(times)
        start = max(0, a - 48)
        end = min(len(times), b + 49)
        key = f"fb-{MATCH}-{i:03}"
        dest = output / (key + ".json.gz")
        assert not dest.exists(), (
            "preserve extraction artifacts; verify before recovery"
        )
        pp = OUT / (key + "-players.json")
        sp = OUT / (key + "-shuttle.json")

        def tick(s):
            return lambda f: progress(0.20 + 0.8 * (i + s + 0.5 * f) / len(bounds))

        track_players(
            v,
            exp.ROOT,
            work,
            ann,
            start,
            end,
            1,
            tick(0),
            pp,
            player_model="small",
            camera_scan=scan,
            skip_uncalibrated=True,
        )
        pl = json.loads(pp.read_bytes())
        track_shuttle(
            v,
            exp.ROOT,
            work,
            start,
            end,
            tick(0.5),
            sp,
            camera_scan=scan,
            skip_frames=[r["frame"] for r in pl["frames"] if r.get("skipped_no_court")],
        )
        sh = json.loads(sp.read_bytes())
        players = compact_players(pl)
        shuttle = compact_shuttle(sh)
        assert (
            [r["frame"] for r in players]
            == [r["frame"] for r in shuttle]
            == list(range(start, end))
        )
        doc = {
            "clip_id": key,
            "source_match": MATCH,
            "split": "development_transfer",
            "source_rally_index": i,
            "source_interval": [a, b],
            "start_frame": start,
            "video": {
                k: v[k]
                for k in ("id", "sha256", "width", "height", "fps", "frame_count")
            },
            "cut_frames": sorted(set(pl["cut_frames"]) | set(sh["cut_frames"])),
            "players": players,
            "shuttle": shuttle,
        }
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(
            gzip.compress(json.dumps(doc, separators=(",", ":")).encode(), mtime=0)
        )
        os.replace(tmp, dest)
        print(key, len(players), flush=True)
    return {"rallies": len(bounds), "features": str(output)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze", action="store_true")
    args = ap.parse_args()
    if args.freeze:
        OUT.mkdir(exist_ok=True)
        (OUT / "protocol.json").open("x").write(json.dumps(protocol(), indent=2))
    else:
        print(
            exp.run_local_job(
                exp.Store(exp.DATA),
                "stroke_transfer_perception",
                "fb-0058-transfer-only",
                run,
            )
        )
