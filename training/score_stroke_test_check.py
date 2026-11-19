"""One-look held-out test check of two frozen stroke-family candidates.

Run from this checkout with the project interpreter, in this order:

    .venv/Scripts/python training/score_stroke_test_check.py protocol
    .venv/Scripts/python training/score_stroke_test_check.py validate
    .venv/Scripts/python training/score_stroke_test_check.py test

`protocol` freezes hashes, test inventory and the decision rule without any
inference. `validate` re-runs this script's code path on the validation data
and must reproduce the candidates' archived validation counts exactly.
`test` scores the held-out test files that exist on this machine, once: it
refuses to run again when its report exists. Nothing is fitted, tuned,
selected or installed; `models/weights/` is only read.
"""

# ruff: noqa: E402 -- pin the real shared store before importing configuration.
import argparse
import gzip
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["BADMINTON_ROOT"] = str(ROOT)
os.environ["BADMINTON_DATA_DIR"] = str(ROOT / "data/processed")
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "training"))

import numpy as np
import torch
import train_doubles as td
import train_doubles_stroke_window as tdw
import train_events as te
import train_stroke_window as win
from badminton.config import DATA
from badminton.event_model import FAMILIES
from badminton.event_network import from_checkpoint
from badminton.jobs import run_local_job
from badminton.storage import Store

OUT = ROOT / ".cache/stroke-test-check"
PROTOCOL = OUT / "protocol.json"
VALIDATION = OUT / "validation-reproduction.json"
REPORT = OUT / "test-report.json"
SIX = ["clear", "lift", "net", "drop", "smash", "drive"]
K = len(FAMILIES)

INSTALLED_SINGLES = ROOT / "models/weights/events.pt"
INSTALLED_DOUBLES = ROOT / "models/weights/events_doubles.pt"
V4_DOUBLES = ROOT / "models/weights/events_doubles_v4.pt"
ENSEMBLE = ROOT / ".cache/stroke-sequence-v1/singles_family_ensemble.ts"
EXPERT = ROOT / ".cache/doubles-stroke-window-v1/expert.pt"
EXPERT_PROTOCOL = ROOT / ".cache/doubles-stroke-window-v1/protocol.json"
AICUP = ROOT / ".cache/training-run1/features"
SHUTTLESET = ROOT / ".cache/step3/features/shuttleset/features"
DSHUTTLENET = ROOT / ".cache/step3/features/dshuttlenet"
S2 = ROOT / ".cache/s2doubles/features"
SS_INDEX = ROOT / "data/datasets/shuttleset/index/strokes.jsonl"

PINNED = {
    "installed_singles": "4d2a8b54973396f4254108141e47c8a17858b0ba595be21e60b6336f74b5e981",
    "installed_doubles": "bfec7cf6b97963e219375ebdeeac2aa62645cc3ec2a9ec631ca8de2e3ffa98d6",
    "v4_doubles": "17615f55456a1d0e5c3412e430c11c9746d24e0d438d16a61bef0deac4823b31",
    "singles_ensemble": "654d3abe534d40f0bf3985d6941426be5635719aad5d23b14d84bc19c7bf4b17",
    "doubles_window_trainer": "b3e6b09d75c68388fdae33e80cbab79532b0c5138edf71ee3c3ee7c2c7b303fb",
    "historical_scorer": "bdd739bafbc47875bf7a0ef4567f5e0a28079047d9037a430f5d347035dc0f26",
    "dshuttlenet_splits": "05c659b62028ed3cb2d9cb1a91124a3be5293fdbebb63e4e0bee4c56fd59c5ec",
}

RULE = (
    "Recommend installing a candidate only if, on its held-out test set, it "
    "(1) labels more known matched contacts correctly than the installed model "
    "overall, (2) is not worse on six-family macro F1 (clear, lift, net, drop, "
    "smash, drive), (3) has a positive paired net (fixed minus introduced) on a "
    "strict majority of test units, and (4) does not lower complete-event F1."
)
OPERATIONAL = {
    "scorer": "train_events.score at threshold 0.7 on the installed model's "
    "contact peaks (identical for both arms), with paired fixed/introduced "
    "counts from the same one-to-one matching",
    "tolerances_frames_30fps": [2, 4],
    "pass_requires": "all four conditions at both 2 and 4 frames on every "
    "test corpus of the candidate's mode",
    "units": {
        "singles": "ShuttleSet original test matches; AI CUP test capture "
        "groups (no match ids exist for AI CUP clips)",
        "doubles": "DShuttleNet test matches; S2 Doubles test match 3",
    },
    "ties": "equal correct count fails (1); equal macro or complete-event F1 "
    "passes (2)/(4); a unit with net 0 does not count as improved",
    "missing_corpora": "If any test corpus of a mode is not on this machine "
    "the rule is evaluated on the available corpora only. A failure there "
    "means do not install. A pass there is reported as 'undetermined: "
    "incomplete test set', never as a recommendation to install.",
    "secondary_reported_not_gating": [
        "AI CUP transfer-style scoring as in eval_stroke_sequence_transfer "
        "(no end variation, global nearest-first matching at +/-4 frames)",
        "weak-family macro F1",
        "hitter and joint accuracy",
    ],
}


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def gz(p):
    return json.loads(gzip.decompress(Path(p).read_bytes()))


def check_pins():
    actual = {
        "installed_singles": sha(INSTALLED_SINGLES),
        "installed_doubles": sha(INSTALLED_DOUBLES),
        "v4_doubles": sha(V4_DOUBLES),
        "singles_ensemble": sha(ENSEMBLE),
        "doubles_window_trainer": sha(ROOT / "training/train_doubles_stroke_window.py"),
        "historical_scorer": sha(ROOT / "training/train_events.py"),
        "dshuttlenet_splits": sha(td.DSHUTTLENET_SPLITS),
    }
    bad = {k: v for k, v in actual.items() if v != PINNED[k]}
    assert not bad, bad
    saved = torch.load(EXPERT, map_location="cpu", weights_only=True)
    assert saved["protocol_sha"] == sha(EXPERT_PROTOCOL)
    return {
        **actual,
        "doubles_expert": sha(EXPERT),
        "doubles_expert_protocol": sha(EXPERT_PROTOCOL),
        "window_expert_module": sha(ROOT / "training/train_stroke_window.py"),
        "doubles_scorer_module": sha(ROOT / "training/train_doubles.py"),
        "this_script": sha(Path(__file__)),
    }


def aicup_folds():
    groups = json.loads(te.GROUPS.read_text())["source_groups"]
    return {
        m.split(":")[1]: (g["fold"], g["id"])
        for g in groups
        for m in g["members"]
        if m.startswith("train:")
    }


def shuttleset_matches():
    split = defaultdict(set)
    with SS_INDEX.open(encoding="utf8") as fp:
        for r in map(json.loads, fp):
            split[r["split"]].add(r["match_id"])
    return {k: sorted(v) for k, v in split.items()}


def inventory():
    folds = aicup_folds()
    ai = {}
    for clip, (fold, group) in sorted(folds.items()):
        if fold == "test":
            p = AICUP / f"{clip}.json.gz"
            ai[clip] = [group, sha(p) if p.exists() else None]
    ss_test = shuttleset_matches()["test"]
    ss = {
        m: sorted(p.name for p in SHUTTLESET.glob(f"ss-{m}-*.json.gz")) for m in ss_test
    }
    splits = json.loads(td.DSHUTTLENET_SPLITS.read_text())
    ds = {
        m: sorted(p.name for p in DSHUTTLENET.rglob(f"ds-{m}-*.json.gz"))
        for m in splits["test"]
    }
    s2 = {p.name: sha(p) for p in sorted(S2.glob("s2-3-*.json.gz"))}
    return {
        "aicup_test_clips": ai,
        "aicup_test_missing": sorted(c for c, v in ai.items() if v[1] is None),
        "shuttleset_test_matches": ss_test,
        "shuttleset_test_files_found": {str(k): len(v) for k, v in ss.items()},
        "dshuttlenet_test_matches": splits["test"],
        "dshuttlenet_test_files_found": {str(k): len(v) for k, v in ds.items()},
        "s2_test_match": 3,
        "s2_test_files": s2,
    }


def write_protocol():
    OUT.mkdir(parents=True, exist_ok=True)
    inv = inventory()
    missing = []
    if any(n == 0 for n in inv["shuttleset_test_files_found"].values()):
        missing.append(
            "ShuttleSet test rally feature files ss-<match>-<set>-<rally>.json.gz "
            "for matches "
            + ", ".join(
                k for k, n in inv["shuttleset_test_files_found"].items() if n == 0
            )
            + f" (expected beside the train/validation files in {SHUTTLESET.relative_to(ROOT)})"
        )
    if any(n == 0 for n in inv["dshuttlenet_test_files_found"].values()):
        missing.append(
            "DShuttleNet test rally feature files ds-<match>-<set>-<rally>.json.gz "
            "for matches "
            + ", ".join(
                k for k, n in inv["dshuttlenet_test_files_found"].items() if n == 0
            )
            + f" (expected under {DSHUTTLENET.relative_to(ROOT)}/w*/features)"
        )
    doc = {
        "purpose": "single held-out test look at two frozen validation-only candidates",
        "written_before_any_test_inference": True,
        "hashes": check_pins(),
        "frozen": {
            "singles": {
                "installed": "models/weights/events.pt (all heads)",
                "candidate": "singles_family_ensemble.ts: family logits = mean of "
                "three frozen family heads; hit/hitter/side/serve from events.pt",
                "threshold": 0.7,
                "aicup_inputs": "train_events.aicup_clip; historical scoring uses "
                "train_events.steady_ends exactly as the validation replay",
                "shuttleset_inputs": "train_events.shuttleset_clip, teacher "
                "snap with models/weights/events_v2.pt, steady_ends (not run: "
                "test files absent)",
            },
            "doubles": {
                "installed": "models/weights/events_doubles.pt (v5) with "
                "choose_partner hitter slots",
                "candidate": "0.65 * v5 family logits + 0.35 * four-player window "
                "expert logits at v5 contacts whose frame is calibration-valid; "
                "everything else from v5",
                "threshold": 0.7,
                "inputs": "train_doubles.doubles_clip via "
                "train_doubles_stroke_window.load, no end variation",
            },
        },
        "decision_rule": RULE,
        "operationalization": OPERATIONAL,
        "inventory": inv,
        "missing_on_this_machine": missing,
        "not_used": "no VM, downloads, spending, retraining, threshold or blend "
        "selection; test results are read once",
    }
    text = json.dumps(doc, indent=1)
    if PROTOCOL.exists():
        assert PROTOCOL.read_text() == text, "protocol changed after freezing"
    else:
        PROTOCOL.write_text(text)
    return doc


# ---------------------------------------------------------------- singles


class Adapter(torch.nn.Module):
    def __init__(self, net):
        super().__init__()
        self.net = net

    def forward(self, x):
        return dict(zip(("hit", "hitter", "family", "side", "serve"), self.net(x)))


def singles_models(dev):
    base = torch.load(INSTALLED_SINGLES, map_location=dev, weights_only=True)
    model = from_checkpoint(base).to(dev).eval()
    model.load_state_dict(base["state"])
    assert base["threshold"] == 0.7
    net = Adapter(torch.jit.load(str(ENSEMBLE), map_location=dev)).eval()
    return model, net


def timed_predict(model, items, dev):
    if dev == "cuda":
        torch.cuda.synchronize()
    t = time.perf_counter()
    out = te.predict(model, items, dev)
    if dev == "cuda":
        torch.cuda.synchronize()
    return out, time.perf_counter() - t


def paired(rows, tol, unit):
    """Per-unit fixed/introduced with train_events.score's matching order."""
    groups = defaultdict(Counter)
    for name, hits, a, b in rows:
        frames = te.peaks(a["hit"], 0.7)
        assert frames == te.peaks(b["hit"], 0.7)
        used = set()
        g = groups[unit(name)]
        for frame, _, family, _, _, mask in hits:
            opts = [f for f in frames if f not in used and abs(f - frame) <= tol]
            if not opts:
                continue
            f = min(opts, key=lambda f: abs(f - frame))
            used.add(f)
            if family < 0:
                continue
            x, y = bool(mask[a["family"][f]]), bool(mask[b["family"][f]])
            g["matched_known"] += 1
            g["installed_correct"] += int(x)
            g["candidate_correct"] += int(y)
            g["fixed"] += int(not x and y)
            g["introduced"] += int(x and not y)
    for g in groups.values():
        g["net"] = g["fixed"] - g["introduced"]
    return {k: dict(v) for k, v in sorted(groups.items())}


def summary(rows, method, tol):
    s = tdw.scores([(r[0], r[1], *r[2:]) for r in rows], method, tol)
    raw = s.pop("historical_scorer")
    return {
        "matched_correct": int(s["matched_correct"]),
        "matched_known": int(s["matched_known"]),
        "six_macro_f1": float(s["six_macro"]),
        "drive_lift_drop_macro_f1": float(s["weak_macro"]),
        "family_f1": s["family_f1"],
        "complete_event_f1": raw["complete_event_f1"],
        "contact_f1": raw["contact_f1"],
        "historical_family_macro_f1_on_matched": raw["family_macro_f1_on_matched"],
        "hitter_correct": int(s["hitter_correct"]),
        "hitter_denominator": int(s["hitter_denominator"]),
        "joint_correct": int(s["joint_correct"]),
        "contacts": raw["contacts"],
        "family_confusion": raw["family_confusion"],
    }


def transfer(items, pa, pb):
    """eval_stroke_sequence_transfer scoring: raw clip ends, +/-4 nearest first."""
    tabs = [np.zeros((K, K), int), np.zeros((K, K), int)]
    for (_, _, hits), a, b in zip(items, pa, pb):
        fs = te.peaks(a["hit"], 0.7)
        used, matched = set(), set()
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
            y, mask = hits[h][2], hits[h][-1]
            if y < 0:
                continue
            for tab, p in zip(tabs, (a, b)):
                guess = int(p["family"][fs[j]])
                tab[y, y if mask[guess] else guess] += 1
    out = {}
    for key, tab in zip(("installed", "candidate"), tabs):
        f = 2 * tab.diagonal() / np.maximum(1, tab.sum(1) + tab.sum(0))
        out[key] = {
            "correct": int(tab.trace()),
            "known": int(tab.sum()),
            "six_macro_f1": float(np.mean([f[FAMILIES.index(t)] for t in SIX])),
        }
    return out


def singles_aicup(fold, dev):
    model, net = singles_models(dev)
    folds = aicup_folds()
    raw = []
    for clip, (f, group) in sorted(folds.items()):
        if f != fold:
            continue
        x, h = te.aicup_clip(gz(AICUP / f"{clip}.json.gz"))
        if h:
            raw.append((clip, x, h))
    unit = {c: g for c, (_, g) in folds.items()}
    # Transfer-style: raw ends.
    pa = te.predict(model, raw, dev)
    pb = te.predict(net, raw, dev)
    result = {"clips": len(raw), "transfer_pm4": transfer(raw, pa, pb)}
    # Historical: deterministic varied ends, as the validation replay.
    items = [te.steady_ends(i) for i in raw]
    te.predict(model, items[:2], dev)
    te.predict(net, items[:2], dev)
    pa, ta = timed_predict(model, items, dev)
    pb, tb = timed_predict(net, items, dev)
    rows = [(c, h, a, b) for (c, _, h), a, b in zip(items, pa, pb)]
    frames = sum(len(x) for _, x, _ in items)
    result["timing"] = {
        "frames": frames,
        "installed_s": ta,
        "candidate_s": tb,
        "extra_ms_per_1000_frames": 1000 * (tb - ta) / frames * 1000,
    }
    result["historical"] = {}
    for tol in (2, 4):
        result["historical"][str(tol)] = {
            "installed": summary(rows, 2, tol),
            "candidate": summary(rows, 3, tol),
            "paired_by_unit": paired(rows, tol, lambda c: unit[c]),
        }
    return result


# ---------------------------------------------------------------- doubles


def doubles_rows(paths, dev, timer):
    models = []
    for p in (INSTALLED_DOUBLES, V4_DOUBLES):
        s = torch.load(p, map_location="cpu", weights_only=True)
        m = from_checkpoint(s).to(dev).eval()
        m.load_state_dict(s["state"])
        models.append(m)
    saved = torch.load(EXPERT, map_location="cpu", weights_only=True)
    expert = win.Expert(saved["dim"], K).to(dev)
    expert.load_state_dict(saved["state"])
    expert.eval()
    original = tdw.windows4

    def windows4(*a):
        t = time.perf_counter()
        z = original(*a)
        timer["windows_s"] += time.perf_counter() - t
        return z

    tdw.windows4 = windows4
    rows, audit = [], Counter()
    try:
        for p in paths:
            with torch.inference_mode():
                # "validation" only makes load also compute the v4 comparator.
                rec, a = tdw.load(p, *models, dev, "validation")
            audit.update(a)
            if rec is None:
                audit["excluded_refs"] += a["refs"]
                continue
            name, h, pred, old, fs, z, logits, ok = rec
            new = dict(pred, family=pred["family"].copy())
            if fs:
                if dev == "cuda":
                    torch.cuda.synchronize()
                t = time.perf_counter()
                with torch.inference_mode():
                    adj = expert(torch.from_numpy(z).to(dev)).cpu().numpy()
                bl = (1 - tdw.ALPHA) * logits + tdw.ALPHA * adj
                idx = np.array(fs)[ok]
                new["family"][idx] = bl[ok].argmax(1)
                timer["expert_s"] += time.perf_counter() - t
            rows.append((name, h, pred, old, new))
    finally:
        tdw.windows4 = original
    return rows, dict(audit)


def doubles_score(rows):
    out = {}
    for tol in (2, 4):
        out[str(tol)] = {
            "installed": summary([(r[0], r[1], r[2], r[4]) for r in rows], 2, tol),
            "candidate": summary([(r[0], r[1], r[2], r[4]) for r in rows], 3, tol),
            "v4_same_contacts": summary(
                [(r[0], r[1], r[3], r[4]) for r in rows], 2, tol
            ),
            "paired_by_unit": paired(
                [(r[0], r[1], r[2], r[4]) for r in rows],
                tol,
                lambda c: "-".join(c.split("-")[:2]),
            ),
        }
    return out


# ---------------------------------------------------------------- decision


def verdict(corpora, complete):
    checks = {}
    ok = True
    for tol in ("2", "4"):
        inst = Counter()
        cand = Counter()
        units = {}
        for name, res in corpora.items():
            h = res[tol]
            i, c = h["installed"], h["candidate"]
            checks[f"{name}@{tol}"] = {
                "more_known_correct": c["matched_correct"] > i["matched_correct"],
                "six_macro_not_worse": c["six_macro_f1"] >= i["six_macro_f1"],
                "complete_event_not_lower": c["complete_event_f1"]
                >= i["complete_event_f1"],
            }
            inst["correct"] += i["matched_correct"]
            cand["correct"] += c["matched_correct"]
            for u, g in h["paired_by_unit"].items():
                units[f"{name}:{u}"] = g["net"]
        improved = sum(v > 0 for v in units.values())
        checks[f"pooled@{tol}"] = {
            "more_known_correct": cand["correct"] > inst["correct"],
            "units_improved": f"{improved}/{len(units)}",
            "majority_units_improved": improved * 2 > len(units),
        }
        for c in checks.values():
            ok &= all(v for v in c.values() if isinstance(v, bool))
    if not ok:
        decision = "do not install"
    elif complete:
        decision = "install"
    else:
        decision = "undetermined: passes on the available test corpora, but the test set is incomplete"
    return {"checks": checks, "rule_passes_on_available": ok, "decision": decision}


# ---------------------------------------------------------------- jobs


def validate(_, progress):
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    check_pins()
    ai = singles_aicup("validation", dev)
    progress(0.5)
    tr = ai["transfer_pm4"]
    hist = json.loads(
        (
            ROOT / ".cache/stroke-sequence-v1/historical-validation-replay.json"
        ).read_text()
    )["results"]["aicup"]["comparisons"]
    expect = [
        (
            tr["installed"]["correct"],
            tr["candidate"]["correct"],
            tr["installed"]["known"],
        ),
        (1450, 1466, 1646),
    ]
    for tol, h in zip(("2", "4"), hist):
        g = ai["historical"][tol]
        expect.append(
            (
                g["installed"]["historical_family_macro_f1_on_matched"],
                g["candidate"]["historical_family_macro_f1_on_matched"],
                g["installed"]["complete_event_f1"],
                g["candidate"]["complete_event_f1"],
                g["paired_by_unit"]["odense"]["fixed"],
                g["paired_by_unit"]["odense"]["introduced"],
            )
        )
        expect.append(
            (
                h["installed"]["family_macro_f1_on_matched"],
                h["candidate"]["family_macro_f1_on_matched"],
                h["installed"]["complete_event_f1"],
                h["candidate"]["complete_event_f1"],
                h["groups"]["Odense"]["fixed"],
                h["groups"]["Odense"]["introduced"],
            )
        )
    files = json.loads(EXPERT_PROTOCOL.read_text())["files"]
    paths = []
    for fold, ds, match, rel, digest in files:
        if fold == "validation" and ds == "s2":
            assert sha(ROOT / rel) == digest
            paths.append(ROOT / rel)
    timer = Counter()
    rows, audit = doubles_rows(paths, dev, timer)
    s2 = doubles_score(rows)
    archived = json.loads(
        (ROOT / ".cache/doubles-stroke-window-v1/report.json").read_text()
    )["corpora"]["s2"]["2"]
    expect.append(
        (
            s2["2"]["installed"]["matched_correct"],
            s2["2"]["candidate"]["matched_correct"],
            s2["2"]["installed"]["matched_known"],
            round(s2["2"]["installed"]["six_macro_f1"], 10),
            round(s2["2"]["candidate"]["six_macro_f1"], 10),
        )
    )
    expect.append(
        (
            archived["v5"]["matched_correct"],
            archived["new"]["matched_correct"],
            archived["v5"]["matched_known"],
            round(archived["v5"]["six_macro"], 10),
            round(archived["new"]["six_macro"], 10),
        )
    )
    pairs = [[expect[i], expect[i + 1]] for i in range(0, len(expect), 2)]
    exact = all(a == b for a, b in pairs)
    doc = {"exact": exact, "reproduced_vs_archived": pairs, "s2_audit": audit}
    VALIDATION.write_text(json.dumps(doc, indent=1))
    print(json.dumps(pairs), "exact", exact, flush=True)
    assert exact, "validation reproduction differs; not opening test"
    return {"exact": exact}


def test(_, progress):
    assert PROTOCOL.exists() and VALIDATION.exists()
    assert json.loads(VALIDATION.read_text())["exact"]
    assert not REPORT.exists(), "test was already scored once"
    protocol = write_protocol()  # asserts it is unchanged since freezing
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(2)
    inv = protocol["inventory"]
    report = {
        "protocol_sha": sha(PROTOCOL),
        "device": torch.cuda.get_device_name() if dev == "cuda" else dev,
    }
    assert not inv["aicup_test_missing"]
    ai = singles_aicup("test", dev)
    progress(0.6)
    paths = [S2 / n for n in sorted(inv["s2_test_files"])]
    for p in paths:
        assert sha(p) == inv["s2_test_files"][p.name]
    timer = Counter()
    rows, audit = doubles_rows(paths, dev, timer)
    s2 = doubles_score(rows)
    ss_complete = all(n > 0 for n in inv["shuttleset_test_files_found"].values())
    ds_complete = all(n > 0 for n in inv["dshuttlenet_test_files_found"].values())
    report["singles"] = {
        "aicup_test": ai,
        "shuttleset_test": "not scored: test feature files absent"
        if not ss_complete
        else "not implemented",
        "verdict": verdict({"aicup": ai["historical"]}, complete=False),
    }
    report["doubles"] = {
        "s2_test_match3": s2,
        "s2_audit": audit,
        "timing": {
            "rallies": len(rows),
            "windows_s": timer["windows_s"],
            "expert_and_blend_s": timer["expert_s"],
        },
        "dshuttlenet_test": "not scored: test feature files absent"
        if not ds_complete
        else "not implemented",
        "verdict": verdict({"s2": s2}, complete=False),
    }
    REPORT.write_text(json.dumps(report, indent=1))
    return {"report": str(REPORT)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=("protocol", "validate", "test"))
    step = ap.parse_args().step
    if step == "protocol":
        doc = write_protocol()
        print(json.dumps(doc["missing_on_this_machine"], indent=1))
    else:
        task = validate if step == "validate" else test
        print(
            run_local_job(
                Store(DATA), f"stroke_test_check_{step}", "stroke-test-check", task
            )
        )
