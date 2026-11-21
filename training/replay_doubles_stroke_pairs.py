"""Recover paired doubles transitions without refitting or opening any final test."""

import json
from collections import Counter, defaultdict

import torch
import train_doubles_stroke_window as dw


def run(job, progress):
    meta = dw.freeze()
    report = json.loads((dw.OUT / "report.json").read_bytes())
    out = dw.OUT / "paired-transitions.json"
    assert not out.exists()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    path = dw.OUT / "expert.pt"
    chk = torch.load(path, map_location="cpu", weights_only=True)
    assert chk["protocol_sha"] == dw.fingerprint(dw.OUT / "protocol.json")
    expert = dw.win.Expert(chk["dim"], dw.exp.K).to(dev).eval()
    expert.load_state_dict(chk["state"])
    models = []
    for name in ("events_doubles.pt", "events_doubles_v4.pt"):
        s = torch.load(
            dw.exp.ROOT / "models/weights" / name, map_location="cpu", weights_only=True
        )
        m = dw.exp.from_checkpoint(s).to(dev).eval()
        m.load_state_dict(s["state"])
        models.append(m)
    selected = [row for row in meta["files"] if row[0] == "validation"]
    res = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    with torch.inference_mode():
        for i, (fold, ds, match, rel, sha) in enumerate(selected):
            if i % 100 == 0:
                progress(i / len(selected))
            p = dw.exp.ROOT / rel
            assert dw.fingerprint(p) == sha
            rec, _ = dw.load(p, *models, dev, fold)
            if rec is None:
                continue
            _, hits, pred, _, fs, z, logits, ok = rec
            if not fs:
                continue
            a = pred["family"][fs]
            b = a.copy()
            blended = (1 - dw.ALPHA) * logits + dw.ALPHA * expert(
                torch.from_numpy(z).to(dev)
            ).cpu().numpy()
            b[ok] = blended[ok].argmax(1)
            for tol in (2, 4):
                cnt = res[ds][str(tol)][str(match)]
                used = set()
                for frame, _, family, _, _, mask in hits:
                    opts = [
                        (abs(f - frame), j)
                        for j, f in enumerate(fs)
                        if j not in used and abs(f - frame) <= tol
                    ]
                    if not opts:
                        continue
                    _, j = min(opts)
                    used.add(j)
                    if family < 0:
                        continue
                    x, y = bool(mask[a[j]]), bool(mask[b[j]])
                    cnt["matched"] += 1
                    cnt["v5_correct"] += int(x)
                    cnt["new_correct"] += int(y)
                    cnt["fixed"] += int(y and not x)
                    cnt["introduced"] += int(x and not y)
    for ds, ts in report["corpora"].items():
        for tol, v in ts.items():
            rows = res[ds][tol]
            assert {
                k: [r["v5_correct"], r["new_correct"]] for k, r in rows.items()
            } == v["per_match_correct"]
            assert (
                sum(r["matched"] for r in rows.values())
                == v["v5"]["matched_known"]
                == v["new"]["matched_known"]
            )
    out.write_text(
        json.dumps(
            {
                "expert_sha": dw.fingerprint(path),
                "report_sha": dw.fingerprint(dw.OUT / "report.json"),
                "matches": res,
            },
            indent=2,
        )
    )
    return {"report": str(out)}


if __name__ == "__main__":
    print(
        dw.exp.run_local_job(
            dw.exp.Store(dw.exp.DATA),
            "doubles_paired_validation",
            "doubles-stroke-paired",
            run,
        )
    )
