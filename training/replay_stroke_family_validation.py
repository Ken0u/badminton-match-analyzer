"""Replay archived singles validation with the original scorer, no fresh test use."""

import gzip
import json
from collections import Counter, defaultdict

import torch
import train_events as te
import train_stroke_sequence as exp


class Adapter(torch.nn.Module):
    def __init__(self, net):
        super().__init__()
        self.net = net

    def forward(self, x):
        return dict(zip(("hit", "hitter", "family", "side", "serve"), self.net(x)))


def counts(items, aa, bb, threshold, tolerance):
    groups = defaultdict(Counter)
    for (clip, _, hits), a, b in zip(items, aa, bb):
        frames = te.peaks(a["hit"], threshold)
        assert frames == te.peaks(b["hit"], threshold)
        used = set()
        g = groups[clip.split("-")[1] if clip.startswith("ss-") else "Odense"]
        for frame, _, family, _, _, mask in hits:
            opts = [f for f in frames if f not in used and abs(f - frame) <= tolerance]
            if not opts:
                continue
            f = min(opts, key=lambda f: abs(f - frame))
            used.add(f)
            if family < 0:
                continue
            x = bool(mask[a["family"][f]])
            y = bool(mask[b["family"][f]])
            g["matched_known"] += 1
            g["installed_correct"] += int(x)
            g["candidate_correct"] += int(y)
            g["fixed"] += int(not x and y)
            g["introduced"] += int(x and not y)
    return dict(groups)


def run(_, progress):
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    archive = json.loads(
        (exp.ROOT / "models/weights/events.validation_report.json").read_text()
    )
    base = torch.load(exp.MODELS[0], map_location=dev, weights_only=True)
    model = exp.from_checkpoint(base).to(dev).eval()
    model.load_state_dict(base["state"])
    threshold = archive["threshold"]
    assert threshold == base["threshold"]
    manifest = json.loads((exp.OUT / "ensemble-manifest.json").read_text())
    candidate = exp.OUT / "singles_family_ensemble.ts"
    assert (
        exp.sha(candidate) == manifest["sha256"]
        and exp.sha(exp.MODELS[0]) == manifest["source_hashes"][0]
    )
    result = {}
    teacher = exp.ROOT / "models/weights/events_v2.pt"
    groups = json.loads(te.GROUPS.read_text())["source_groups"]
    ai = []
    ss = []
    for name in sorted(
        m.split(":")[1]
        for g in groups
        if g["fold"] == "validation"
        for m in g["members"]
        if m.startswith("train:")
    ):
        d = json.loads(
            gzip.decompress(
                (
                    exp.ROOT / ".cache/training-run1/features" / f"{name}.json.gz"
                ).read_bytes()
            )
        )
        x, h = te.aicup_clip(d)
        if h:
            ai.append((name, x, h))
    with (exp.ROOT / "data/datasets/shuttleset/index/strokes.jsonl").open(
        encoding="utf8"
    ) as fp:
        ids = {r["match_id"] for r in map(json.loads, fp) if r["split"] == "validation"}
    for p in sorted(exp.FEATURE.glob("ss-*.json.gz")):
        if int(p.name.split("-")[1]) not in ids:
            continue
        doc = json.loads(gzip.decompress(p.read_bytes()))
        if doc["split"] != "validation":
            continue
        x, h = te.shuttleset_clip(doc)
        if h:
            ss.append((doc["clip_id"], x, h))
    ss = te.snap(ss, teacher, dev)
    progress(0.25)
    net = Adapter(torch.jit.load(str(candidate), map_location=dev)).eval()
    for name, raw in [("aicup", ai), ("shuttleset", ss)]:
        # Replay v6 deterministic validation clip ends (bce0ba5).
        vary = True
        items = [te.steady_ends(item) for item in raw]
        pred = te.predict(model, items, dev)
        old = [te.score(items, pred, threshold, t) for t in (2, 4)]
        diffs = [
            {k: [o[k], rec[name][k]] for k in o if o[k] != rec[name][k]}
            for o, rec in zip(old, archive["validation"])
        ]
        exact = not any(diffs)
        print(name, "archived differences", [list(d) for d in diffs], flush=True)
        print(
            name,
            "contact/family replay vs archived",
            [
                [o[k], rec[name][k]]
                for o, rec in zip(old, archive["validation"])
                for k in ("contact_f1", "family_macro_f1_on_matched")
            ],
            flush=True,
        )
        other = te.predict(net, items, dev)
        cmp = []
        for t, baseline in zip((2, 4), old):
            new = te.score(items, other, threshold, t)
            paired = counts(items, pred, other, threshold, t)
            cmp.append({"installed": baseline, "candidate": new, "groups": paired})
            print(
                name,
                vary,
                t,
                baseline["family_macro_f1_on_matched"],
                new["family_macro_f1_on_matched"],
                flush=True,
            )
        result[name] = {
            "historical_table_exact": exact,
            "baseline_differences": diffs,
            "vary_ends": vary,
            "comparisons": cmp,
        }
        progress(0.55 if name == "aicup" else 0.98)
    path = exp.OUT / "historical-validation-replay.json"
    path.write_text(
        json.dumps(
            {
                "scorer_sha": exp.sha(exp.ROOT / "training/train_events.py"),
                "teacher_sha": exp.sha(teacher),
                "candidate_sha": manifest["sha256"],
                "threshold": threshold,
                "results": result,
            },
            indent=2,
        )
    )
    return {"report": str(path)}


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA),
            "historical_stroke_validation",
            "stroke-sequence-v1",
            run,
        )
    )
