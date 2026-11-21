"""Package the validated singles ensemble outside app weights; verify parity."""

import json
import time

import numpy as np
import torch
import train_stroke_sequence as exp
from torch import nn


class FamilyOnlyEnsemble(nn.Module):
    def __init__(self, experts):
        super().__init__()
        self.experts = nn.ModuleList(experts)

    def forward(self, x):
        a = self.experts[0](x)
        family = (
            a["family"] + self.experts[1](x)["family"] + self.experts[2](x)["family"]
        ) / 3
        return a["hit"], a["hitter"], family, a["side"], a["serve"]


def export(_id, progress):
    torch.manual_seed(173)
    torch.set_num_threads(2)
    protocol = json.loads((exp.OUT / "protocol.json").read_text())
    assert protocol["model_hashes"] == [exp.sha(p) for p in exp.MODELS]
    experts = []
    for p in exp.MODELS:
        ck = torch.load(p, map_location="cpu", weights_only=True)
        model = exp.from_checkpoint(ck).eval()
        model.load_state_dict(ck["state"])
        experts.append(model)
    mod = FamilyOnlyEnsemble(experts).eval()
    path = exp.OUT / "singles_family_ensemble.ts"
    tmp = path.with_suffix(".tmp")
    size = exp.PLAYER * 2 + 6
    with torch.inference_mode():
        compiled = torch.jit.script(mod)
        compiled.save(str(tmp))
        loaded = torch.jit.load(str(tmp)).eval()
        for length in (25, 103, 301):
            x = torch.randn(1, length, size)
            base = experts[0](x)
            actual = loaded(x)
            expected = mod(x)
            for i, key in ((0, "hit"), (1, "hitter"), (3, "side"), (4, "serve")):
                torch.testing.assert_close(actual[i], base[key])
            torch.testing.assert_close(actual[2], expected[2])
        tmp.replace(path)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        x = torch.randn(1, 300, size, device=device)
        bench = {}
        for name, net in [("installed", experts[0]), ("ensemble", loaded)]:
            net = net.to(device)
            net(x)

            def sync():
                if device == "cuda":
                    torch.cuda.synchronize()

            spans = []
            for _ in range(12):
                sync()
                t = time.perf_counter()
                net(x)
                sync()
                spans.append(1000 * (time.perf_counter() - t))
            bench[name] = round(float(np.median(spans)), 2)
    out = {
        "sha256": exp.sha(path),
        "source_hashes": protocol["model_hashes"],
        "input": "one 30 fps singles camera view, same normalized pose/shuttle features as events.pt",
        "outputs": ["hit", "hitter", "family", "side", "serve"],
        "family_order": list(exp.FAMILIES),
        "output_kind": "logits",
        "base_threshold": torch.load(
            exp.MODELS[0], map_location="cpu", weights_only=True
        )["threshold"],
        "file_bytes": path.stat().st_size,
        "synthetic_300_frame_median_ms": bench,
        "device": device,
        "parity_lengths": [25, 103, 301],
    }
    (exp.OUT / "ensemble-manifest.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    print(
        exp.run_local_job(
            exp.Store(exp.DATA), "stroke_family_export", "stroke-sequence-v1", export
        )
    )
