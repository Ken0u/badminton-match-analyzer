"""Train the sequence rally outcome model (backend/badminton/rally_outcome_model.py).

Examples come from the extracted rally feature files, as for
training/train_rally_outcome.py: the app's shuttle and player tracks around
the labelled last stroke, the dataset's court corners, and the published
rally winner. Each rally gives

- "last" rows: the sequence around the labelled last hit (training rallies
  also at +-2 frames), target: did the last hitter's end win, and how the
  shot ended (in, out, net);
- "previous" rows: the sequence around the stroke before it, with that
  hitter's end, as if the application had missed the last contact. The
  target is still who won the rally.

Four fifths of the training matches train the networks, the other fifth
(match id divisible by five) chooses the epoch and is the fold on which
designs are compared; validation matches only report. Test matches are not
read.

    python training/train_rally_sequence.py --features F1 F2 ... \
        --cache .cache/step3/sequence_examples.npz \
        --output .cache/step3/rally_outcome_sequence_v2.json
"""

import argparse
import json
import sys
from collections import Counter
from functools import partial
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import rally_outcome_features
from badminton import rally_outcome_model as M
from badminton import rally_outcomes as R

LONG_S = 2.4  # stored per row; shorter looks are cut from it
# With --flight, rows place the landing with the last shot's 3D flight
# (rally_outcomes.placed_landing) and add rally_outcomes.FLIGHT_FEATURES.
FLIGHT = False


def target(label):
    if label["reason"] == "winner":
        return 0
    if label["reason"] == "error":
        return 1 if label["detail"] == "out" else 2
    return -1


def rows_of(example):
    """Feature rows of one labelled rally (see the module text)."""
    label, line = example["label"], example["timeline"]
    if label["last_hitter_end"] is None or label["winner_end"] is None:
        return
    mode = "singles" if example["dataset"] == "shuttleset" else "doubles"
    matrix = example["homography"]
    start = line["start_frame"]
    times, shuttle = line["times"], line["shuttle"]
    cuts = sorted(c - start for c in line["cuts"])
    anchors = [
        (
            "last",
            label["last_hit_frame"],
            label["last_hitter_end"],
            example["last_type"],
        )
    ]
    if len(label["hit_frames"]) >= 2:
        anchors.append(
            (
                "previous",
                label["hit_frames"][-2],
                R.other(label["last_hitter_end"]),
                None,
            )
        )
    for variant, frame, hitter, family in anchors:
        offsets = (
            (0, -2, 2) if example["split"] == "train" and variant == "last" else (0,)
        )
        for offset in offsets:
            after = frame - start + offset
            if not 0 <= after < len(times):
                continue
            until = next((c for c in cuts if c > after), len(times))
            since = max((c for c in cuts if c <= after), default=0)
            landing = R.find_landing(
                times, shuttle, after, until, line["aspect"], lambda i: matrix
            )
            if FLIGHT and landing is not None:
                search = min(
                    until,
                    int(
                        np.searchsorted(
                            times, times[after] + R.LANDING_SEARCH_S, "right"
                        )
                    ),
                )
                fit = R.shot_flight(
                    times,
                    shuttle,
                    after,
                    search,
                    line["aspect"],
                    lambda i: matrix,
                    hitter,
                    line["people"],
                    None if landing["kind"] == "track_end" else landing["index"],
                    landing["kind"] in R.GROUNDED_KINDS,
                )
                landing = R.placed_landing(
                    landing, fit, lambda i: matrix, line["aspect"]
                )
            summary = R.outcome_features(
                times,
                shuttle,
                line["players"],
                after,
                landing,
                hitter,
                mode,
                line["aspect"],
                family,
                R.FEATURES_FLIGHT if FLIGHT else R.FEATURES,
            )
            sequence = M.sequence_features(
                times,
                shuttle,
                line["people"],
                after,
                landing,
                hitter,
                line["aspect"],
                lambda i: matrix,
                lambda i, since=since, until=until: since <= i < until,
                LONG_S,
            )
            rule = R.rule_outcome(
                hitter,
                landing,
                mode,
                family in R.FAMILY_GROUPS and R.FAMILY_GROUPS[family] == "serve",
            )
            yield {
                "name": example["name"],
                "dataset": example["dataset"],
                "match_id": example["match_id"],
                "split": example["split"],
                "variant": variant,
                "offset": offset,
                "won": int(label["winner_end"] == hitter),
                "target": target(label) if variant == "last" else -1,
                "rule": None if rule is None else rule["detail"],
                "tail_s": times[min(until, len(times)) - 1] - times[after],
                "summary": summary,
                "sequence": sequence,
            }


def _rows_of_files(paths, flight=False):
    global FLIGHT
    FLIGHT = flight
    rows = []
    for example in rally_outcome_features.examples((), paths):
        if example["split"] in ("train", "validation"):
            for row in rows_of(example):
                row["sequence"] = row["sequence"].astype(np.float16)
                rows.append(row)
    return rows


def build(folders, cache, workers=1, flight=False):
    if cache and cache.is_file():
        data = np.load(cache, allow_pickle=False)
        meta = json.loads(str(data["meta"]))
        return meta, data["summary"].astype(np.float32), data["sequence"]
    paths = rally_outcome_features.files(folders)
    chunks = [paths[i : i + 50] for i in range(0, len(paths), 50)]
    meta, summaries, sequences = [], [], []
    if workers > 1:
        from multiprocessing import Pool

        with Pool(workers) as pool:
            results = pool.imap(partial(_rows_of_files, flight=flight), chunks)
            for rows in results:
                for row in rows:
                    summaries.append(row.pop("summary"))
                    sequences.append(row.pop("sequence"))
                    meta.append(row)
                print(len(meta), "rows", flush=True)
    else:
        for chunk in chunks:
            for row in _rows_of_files(chunk, flight):
                summaries.append(row.pop("summary"))
                sequences.append(row.pop("sequence"))
                meta.append(row)
            print(len(meta), "rows", flush=True)
    summary = np.asarray(summaries, np.float32)
    sequence = np.stack(sequences)
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            cache, meta=json.dumps(meta), summary=summary, sequence=sequence
        )
    return meta, summary, sequence


def mirror_summary(summary):
    """Left and right swapped: only the image x changes (lateral distances
    and line distances are symmetric)."""
    out = summary.copy()
    x = R.FEATURES.index("image_x")
    found = summary[:, R.FEATURES.index("landing_found")] > 0
    out[found, x] = 1 - summary[found, x]
    return out


def network(hidden, dropout, use_sequence=True, summary_size=len(R.FEATURES)):
    import torch
    from torch import nn

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.input = nn.Linear(M.STEP_FEATURES, hidden)
            self.gru = nn.GRU(hidden, hidden, batch_first=True, bidirectional=True)
            self.summary = nn.Linear(summary_size, 32)
            self.hidden = nn.Linear(6 * hidden + 32, 64)
            self.classes = nn.Linear(64, len(R.CLASSES))
            self.won = nn.Linear(64, 1)
            self.drop = nn.Dropout(dropout)

        def forward(self, sequence, summary):
            x = torch.relu(self.input(sequence))
            states, _ = self.gru(self.drop(x))
            h = self.gru.hidden_size
            pooled = torch.cat(
                [
                    states.mean(1),
                    states.max(1).values,
                    states[:, -1, :h],
                    states[:, 0, h:],
                ],
                dim=1,
            )
            if not use_sequence:
                pooled = pooled * 0
            g = torch.relu(self.summary(summary))
            hid = torch.relu(self.hidden(self.drop(torch.cat([pooled, g], dim=1))))
            return self.classes(hid), self.won(hid)[:, 0]

    return Net()


def fit(
    train,
    check,
    hidden,
    dropout,
    epochs,
    seed,
    use_sequence=True,
    lr=2e-3,
    decay=1e-2,
    keep_last=False,
):
    """Train one network; keep the epoch with the best check-fold loss.

    With ``keep_last`` the last epoch is kept instead: the check rallies are
    then part of the training rows and cannot choose anything.
    """
    import torch

    torch.manual_seed(seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    net = network(hidden, dropout, use_sequence, train[1].shape[1]).to(device)

    def tensors(part):
        return [torch.tensor(a).to(device) for a in part]

    xs, gs, won, cls = tensors(train)
    cxs, cgs, cwon, _ = tensors(check)
    optimizer = torch.optim.AdamW(net.parameters(), lr=lr, weight_decay=decay)
    schedule = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, lr, total_steps=epochs * (len(xs) // 128 + 1)
    )
    bce = torch.nn.BCEWithLogitsLoss()
    ce = torch.nn.CrossEntropyLoss(ignore_index=-1)
    best = (1e9, None, 0)
    for epoch in range(epochs):
        net.train()
        order = torch.randperm(len(xs), device=device)
        for start in range(0, len(xs), 128):
            batch = order[start : start + 128]
            optimizer.zero_grad()
            logits, logit = net(xs[batch], gs[batch])
            loss = bce(logit, won[batch]) + 0.5 * ce(logits, cls[batch])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
            optimizer.step()
            schedule.step()
        net.eval()
        with torch.no_grad():
            value = float(bce(net(cxs, cgs)[1], cwon))
        if keep_last or value < best[0]:
            state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
            best = (value, state, epoch)
    return {k: v.numpy() for k, v in best[1].items()}, best[0], best[2]


def predict(members, sequence, summary, use_sequence=True):
    """Averaged (class probabilities [N, 3], P(hitter's end won) [N])."""
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    classes, won = [], []
    for state, hidden in members:
        net = network(hidden, 0.0, use_sequence, summary.shape[1]).to(device)
        net.load_state_dict({k: torch.tensor(v) for k, v in state.items()})
        net.eval()
        with torch.no_grad():
            logits, logit = net(
                torch.tensor(sequence).to(device), torch.tensor(summary).to(device)
            )
        classes.append(torch.softmax(logits, 1).cpu().numpy())
        won.append(torch.sigmoid(logit).cpu().numpy())
    return np.mean(classes, 0), np.mean(won, 0)


def scores(meta, classes, won):
    """Winner and in/out/net accuracy of rows with their predictions."""
    if not meta:
        return {"n": 0}
    truth = np.array([m["won"] for m in meta])
    said = won >= 0.5
    out = {
        "n": len(meta),
        "winner_right": int(np.sum(truth == said)),
        "winner": round(float(np.mean(truth == said)), 3),
    }
    known = [i for i, m in enumerate(meta) if m["target"] >= 0]
    if known:
        t = np.array([meta[i]["target"] for i in known])
        p = np.where(
            said[known], 0, np.where(classes[known, 1] >= classes[known, 2], 1, 2)
        )
        out["class"] = round(float(np.mean(t == p)), 3)
        out["confusion"] = dict(
            sorted(
                Counter(f"{R.CLASSES[a]}->{R.CLASSES[b]}" for a, b in zip(t, p)).items()
            )
        )
    return out


RULE_WON = {"in": 1, "out": 0, "net": 0, None: 0}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, nargs="+", required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--hidden", type=int, default=48)
    parser.add_argument("--dropout", type=float, default=0.3)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--after", type=float, default=M.AFTER_S)
    parser.add_argument(
        "--previous",
        type=float,
        default=1.0,
        help="share of the 'previous' rows (a missed last contact) used in training",
    )
    parser.add_argument(
        "--all-training",
        action="store_true",
        help="fit on every training match, the check fold included, for the "
        "fixed number of epochs (after the design is chosen with the fold)",
    )
    parser.add_argument("--no-sequence", action="store_true", help="summary only")
    parser.add_argument(
        "--flight",
        action="store_true",
        help="place the landing with the 3D flight and add its features "
        "(use a separate --cache)",
    )
    parser.add_argument("--name", default="rally outcome sequence v2")
    parser.add_argument(
        "--base-features",
        action="store_true",
        help="with --flight: leave the flight features out of the network",
    )
    parser.add_argument("--workers", type=int, default=1, help="to read the files")
    parser.add_argument(
        "--report-validation",
        action="store_true",
        help="also score the validation matches (after the design is fixed)",
    )
    args = parser.parse_args()
    meta, summary, sequence = build(
        args.features, args.cache, args.workers, args.flight
    )
    names = R.FEATURES_FLIGHT if args.flight else R.FEATURES
    if summary.shape[1] != len(names):
        raise SystemExit("The cached rows were built with the other feature set")
    if args.base_features:
        # Landing placed by the flight, but only the plain landing features.
        summary, names = summary[:, : len(R.FEATURES)], R.FEATURES
    count = M.steps(args.after)
    sequence = sequence[:, :count].astype(np.float32)
    # Steps beyond this look are the same as never stored.
    is_train = np.array([m["split"] == "train" for m in meta])
    is_check = is_train & np.array([m["match_id"] % 5 == 0 for m in meta])
    is_fit = is_train if args.all_training else is_train & ~is_check
    rng = np.random.default_rng(0)
    previous = np.array([m["variant"] == "previous" for m in meta])
    keep = ~previous | (rng.random(len(meta)) < args.previous)
    plain = np.array([m["offset"] == 0 for m in meta])
    mean = summary[is_fit].mean(0)
    scale = summary[is_fit].std(0) + 1e-6

    def part(mask, mirror=False):
        index = np.flatnonzero(mask)
        s, g = sequence[index], summary[index]
        if mirror:
            s = np.concatenate([s, np.stack([M.mirrored(x) for x in s])])
            g = np.concatenate([g, mirror_summary(g)])
            index = np.concatenate([index, index])
        return (
            s,
            ((g - mean) / scale).astype(np.float32),
            np.array([meta[i]["won"] for i in index], np.float32),
            np.array([meta[i]["target"] for i in index], np.int64),
        )

    train = part(is_fit & keep, mirror=True)
    check_mask = is_check & plain & ~previous
    check = part(check_mask)
    print(
        f"{len(train[0])} training rows (mirrored), {len(check[0])} check rallies, "
        f"look {args.after} s, {count} steps",
        flush=True,
    )
    members = []
    for seed in range(args.seeds):
        state, loss, epoch = fit(
            train,
            check,
            args.hidden,
            args.dropout,
            args.epochs,
            seed,
            not args.no_sequence,
            keep_last=args.all_training,
        )
        members.append((state, args.hidden))
        print(f"seed {seed}: epoch {epoch}, check loss {loss:.4f}", flush=True)

    def report(mask):
        out = {}
        for dataset in ("shuttleset", "dshuttlenet"):
            for variant in ("last", "previous"):
                index = [
                    i
                    for i in np.flatnonzero(mask & plain)
                    if meta[i]["dataset"] == dataset and meta[i]["variant"] == variant
                ]
                if not index:
                    continue
                rows = [meta[i] for i in index]
                g = ((summary[index] - mean) / scale).astype(np.float32)
                classes, won = predict(
                    members, sequence[index], g, not args.no_sequence
                )
                entry = {"model": scores(rows, classes, won)}
                rule = np.array([RULE_WON[m["rule"]] for m in rows], float)
                entry["rule_winner"] = round(
                    float(np.mean(rule == np.array([m["won"] for m in rows]))), 3
                )
                out[f"{dataset} {variant}"] = entry
        return out

    # With --all-training the fold was trained on: its score is not a check.
    result = {"fitted_fold" if args.all_training else "check_fold": report(is_check)}
    if args.report_validation:
        result["validation"] = report(~is_train)
    print(json.dumps(result, indent=1))
    if args.no_sequence:
        return  # a comparison only; the stored network always reads the sequence
    document = {
        "format": M.FORMAT,
        "name": args.name,
        "features": list(names),
        "classes": list(R.CLASSES),
        "step_features": M.STEP_FEATURES,
        "after_s": args.after,
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "members": [
            {k: M.encode_array(v) for k, v in state.items()} for state, _ in members
        ],
        "training": {
            "hidden": args.hidden,
            "dropout": args.dropout,
            "epochs": args.epochs,
            "seeds": args.seeds,
            "previous": args.previous,
            "all_training": args.all_training,
            "sequence": not args.no_sequence,
            "flight": args.flight,
            **result,
        },
    }
    # The stored networks must give the same answer through the numpy code.
    model = M.SequenceOutcomeModel(document)
    index = np.flatnonzero(check_mask)[:20]
    g = ((summary[index] - mean) / scale).astype(np.float32)
    _, won = predict(members, sequence[index], g)
    again = [model.probabilities(sequence[i], summary[i])[1] for i in index]
    if not np.allclose(won, again, atol=1e-4):
        raise SystemExit("The numpy network disagrees with the trained one")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(document) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
