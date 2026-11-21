"""Frozen AICup validation transfer check; never fits or installs a model."""

import gzip
import json

import numpy as np
import torch
import train_stroke_sequence as exp
from train_events import GROUPS, aicup_clip, peaks


def evaluate(job, progress):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    saved = torch.load(exp.OUT / "candidate.pt", map_location="cpu", weights_only=True)
    assert [exp.sha(p) for p in exp.MODELS] == saved["protocol"]["model_hashes"]
    model = exp.StrokeSequence(saved["features"]).to(device).eval()
    model.load_state_dict(saved["state"])
    experts = []
    for path in exp.MODELS:
        weights = torch.load(path, map_location="cpu", weights_only=True)
        net = exp.from_checkpoint(weights).to(device).eval()
        net.load_state_dict(weights["state"])
        experts.append(net)
        if len(experts) == 1:
            threshold = weights["threshold"]
    refs = {
        m.split(":")[1]: g["id"]
        for g in json.loads(GROUPS.read_text())["source_groups"]
        if g["fold"] == "validation"
        for m in g["members"]
        if m.startswith("train:")
    }
    inventory = {"requested": len(refs), "present": 0, "ref_hits": 0, "peaks": 0}
    rows = []
    with torch.inference_mode():
        for i, (clip, venue) in enumerate(sorted(refs.items())):
            if i % 50 == 0:
                progress(i / len(refs))
            path = exp.ROOT / ".cache/training-run1/features" / f"{clip}.json.gz"
            if not path.exists():
                continue
            inventory["present"] += 1
            x, hits = aicup_clip(json.loads(gzip.decompress(path.read_bytes())))
            inventory["ref_hits"] += len(hits)
            if not len(x):
                continue
            xx = torch.from_numpy(x)[None].to(device)
            o = [e(xx) for e in experts]
            fs = peaks(o[0]["hit"][0, :, 0].sigmoid().cpu().numpy(), threshold)
            inventory["peaks"] += len(fs)
            if not fs:
                continue
            z = exp.features(
                x,
                fs,
                o[0]["hitter"][0].argmax(1).cpu().numpy(),
                [a["family"][0].cpu().numpy() for a in o],
            )
            pred = (
                model(torch.from_numpy(z)[None].to(device), torch.tensor([len(fs)]))[0]
                .argmax(-1)
                .cpu()
                .numpy()
            )
            K = exp.K
            preds = [
                z[:, :K].argmax(1),
                z[:, : 3 * K].reshape(len(fs), 3, K).mean(1).argmax(1),
                pred,
            ]
            y = np.full(len(fs), -1)
            used = set()
            matched = set()
            for _, h, j in sorted(
                (abs(f - ref[0]), h, j)
                for h, ref in enumerate(hits)
                for j, f in enumerate(fs)
                if abs(f - ref[0]) <= 4
            ):
                if j in used or h in matched:
                    continue
                used.add(j)
                matched.add(h)
                y[j] = hits[h][2]
                mask = hits[h][-1]
                for p in preds:
                    if y[j] >= 0 and mask[p[j]]:
                        p[j] = y[j]
            rows.append((venue, y, *preds))
    result = {"inventory": inventory, "metrics": exp.metrics(rows)}
    (exp.OUT / "aicup-validation.json").write_text(json.dumps(result, indent=2))
    return inventory


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA),
            "stroke_sequence_transfer",
            "stroke-sequence-v1",
            evaluate,
        )
    )
