"""Prepare prediction-blind review ledgers. No historical labels, predictions or Store writes."""

import argparse
import csv
import hashlib
import json
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(4 << 20), b""):
            h.update(b)
    return h.hexdigest()


def make(reservation, media, out):
    d = json.loads(reservation.read_bytes())
    entries = [d["source"], *(r["source"] for r in d["additional_reserved_matches"])]
    info = []
    blocks = []
    for e in entries:
        k = e["match_id"]
        p = media / (k + ".mp4")
        assert digest(p) == e["media_sha256"]
        s = d["timestamp_screen"][k]
        steps = s["steps"]
        assert (
            s["first_pts"] == 0
            and s["time_base"] == "1/15360"
            and len(steps) == 1
            and "512" in steps
            and s["packet_count_with_pts"] == steps["512"] + 1
        )
        end = s["last_pts"] + 512
        step = 180 * 15360
        start = 0
        while start < end:
            stop = min(start + step, end)
            blocks.append((k, start, stop, "unreviewed", "", ""))
            start = stop
        info.append(
            {
                "id": k,
                "video": str(p.resolve()),
                "sha256": e["media_sha256"],
                "pts_time_base": "1/15360",
                "presentation_step": 512,
                "end_pts_exclusive": end,
            }
        )
    out.mkdir(parents=True, exist_ok=False)

    def table(p, h, rows):
        with p.open("x", encoding="utf8", newline="") as f:
            w = csv.writer(f)
            w.writerow(h)
            w.writerows(rows)

    for name in ("review-A", "review-B"):
        q = out / name
        q.mkdir()
        (q / "media.json").write_text(json.dumps(info, indent=2))
        table(
            q / "coverage.csv",
            (
                "source",
                "start_pts_inclusive",
                "end_pts_exclusive",
                "status",
                "reviewer",
                "notes",
            ),
            blocks,
        )
        table(
            q / "contacts.csv",
            (
                "source",
                "earliest_contact_pts",
                "latest_contact_pts",
                "player",
                "family",
                "side",
                "notes",
            ),
            [],
        )
        table(
            q / "intervals.csv",
            ("source", "start_pts_inclusive", "end_pts_exclusive", "scene", "notes"),
            [],
        )
        (q / "instructions.txt").write_text(
            "Use original video only; do not open model results or publisher annotations. Review independently, all blocks, including zero-contact blocks. Blocks are scheduling aids, not cuts. Use video presentation timestamps, not elapsed player time or decode packet order. At block boundaries assign a contact once by earliest plausible timestamp. Record every plausible live racket contact; use unknown for ambiguous player, stroke family or forehand/backhand, not an invented label. Record served strokes as serve, separate from clear/lift/net/drop/smash/drive; record other (specify) distinctly, do not add half smash. Mark replays, nonplay, live and uncertain intervals. Name the actual player, not just near/far. Mark coverage complete only after full review, otherwise leave incomplete. Wider timing uncertainty is not an exact contact. Return the ledger to a coordinator without consulting the other reviewer. Do not label by prediction or use captions.\n"
        )
    (out / "receipt.json").write_text(
        json.dumps(
            {
                "reservation_sha256": digest(reservation),
                "blocks_per_reviewer": len(blocks),
                "media": info,
                "status": "empty independent review ledgers; not ground truth",
                "adjudication": "Reconcile two locked independent ledgers, preserving disagreements and unresolved timing/identity/families, before scoring. Neither a blank coverage ledger nor source-published intervals imply absence of contacts.",
            },
            indent=2,
        )
    )
    return len(blocks)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("reservation", type=Path)
    p.add_argument("media", type=Path)
    p.add_argument("out", type=Path)
    a = p.parse_args()
    print(make(a.reservation, a.media, a.out))
