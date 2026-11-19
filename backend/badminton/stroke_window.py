"""Four-player stroke-family window for the doubles event model.

A small network reads 40 steps around each contact the doubles event model
finds (16 before, 24 after, clipped at the neighbouring contacts and the view
edges): the hitter's pose relative to their feet, the boxes of the hitter,
their partner and both opponents (left to right), and the shuttle. Its family
logits are blended with the event model's at contacts whose frame has a court
calibration: (1 - BLEND) * event model + BLEND * window. Everything else
(contacts, hitter, side, serve type) comes from the event model, and contacts
without a court calibration keep the event model's family.

Trained by training/train_doubles_stroke_window.py (DShuttleNet training
matches, fixed v5 contacts); the weights, blend and calibration rule were
frozen on validation before one held-out test check (DShuttleNet test
matches and S2 Doubles match 3), recorded in .cache/stroke-test-check.
This module is the inference part of that script, unchanged in arithmetic.
"""

import numpy as np

from .event_model import PLAYER

BLEND = 0.35
BEFORE, AFTER = 36, 54


def windows(x, steps, slots, segment, valid):
    """Window inputs, one (40, 81) array per contact step.

    x is the event model's input (doubles observations with motion) at the
    trained frame rate; slots the chosen hitter slot of each step; segment
    and valid per step: camera segment number and court calibration. Steps
    in another segment or without calibration are zeroed.
    """
    f = np.array(steps)
    left = np.maximum.reduce([np.zeros_like(f), f - BEFORE, np.r_[0, f[:-1] + 1]])
    right = np.minimum.reduce(
        [np.full_like(f, len(x) - 1), f + AFTER, np.r_[f[1:] - 1, len(x) - 1]]
    )
    ix = np.rint(
        np.c_[np.linspace(left, f, 16).T, np.linspace(f, right, 25).T[:, 1:]]
    ).astype(int)
    v = x[ix]
    slots = np.array(slots)
    n = np.arange(len(f))[:, None]
    j = np.arange(40)[None, :]
    bs = v[:, :, : 4 * PLAYER].reshape(len(f), 40, 4, PLAYER)
    me = bs[n, j, slots[:, None]]
    mate = bs[n, j, (slots ^ 1)[:, None]]
    a = bs[n, j, ((1 - slots // 2) * 2)[:, None]]
    b = bs[n, j, ((1 - slots // 2) * 2 + 1)[:, None]]
    # Opponents by horizontal position, not by arbitrary slot order.
    flip = a[:, :, 51:52] > b[:, :, 51:52]
    feet = np.stack(((me[:, :, 51] + me[:, :, 53]) / 2, me[:, :, 54]), 2)
    height = np.maximum(0.05, me[:, :, 54:55] - me[:, :, 52:53])
    sk = me[:, :, :51].reshape(len(f), 40, 17, 3)
    pose = np.concatenate(
        (
            (sk[:, :, :, :2] - feet[:, :, None, :])
            / height[:, :, :, None]
            * (sk[:, :, :, 2:] > 0),
            sk[:, :, :, 2:],
        ),
        3,
    ).reshape(len(f), 40, 51)
    ball = v[:, :, -6:]
    rel = (
        (ball[:, :, :2] - feet[:, 15:16])
        / height[:, 15:16]
        * ball[:, :, 2:3]
        * me[:, 15:16, 55:56]
    )
    dt = np.broadcast_to(
        np.stack((f - left, right - f), 1)[:, None] / 30, (len(f), 40, 2)
    )
    z = np.concatenate(
        (
            pose,
            me[:, :, 51:56],
            mate[:, :, 51:56],
            np.where(flip, b[:, :, 51:56], a[:, :, 51:56]),
            np.where(flip, a[:, :, 51:56], b[:, :, 51:56]),
            rel,
            ball,
            dt,
        ),
        2,
    )
    ok = (segment[ix] == segment[f, None]) & valid[ix] & valid[f, None]
    return (np.clip(z, -10, 10) * ok[:, :, None]).astype("f")


def expert_network(dim, classes):
    """The window network (same layout as training/train_stroke_window.py)."""
    import torch
    from torch import nn

    class Expert(nn.Module):
        def __init__(self, d, k):
            super().__init__()
            self.input = nn.Sequential(
                nn.Conv1d(d, 80, 1), nn.BatchNorm1d(80), nn.SiLU()
            )
            self.blocks = nn.ModuleList(
                [
                    nn.Sequential(
                        nn.Conv1d(80, 80, 3, padding=i, dilation=i),
                        nn.BatchNorm1d(80),
                        nn.SiLU(),
                        nn.Dropout(0.12),
                        nn.Conv1d(80, 80, 1),
                    )
                    for i in (1, 2, 4)
                ]
            )
            self.head = nn.Sequential(
                nn.Linear(80 * 5, 128),
                nn.LayerNorm(128),
                nn.SiLU(),
                nn.Dropout(0.25),
                nn.Linear(128, k),
            )

        def forward(self, x):
            h = self.input(x.transpose(1, 2))
            for b in self.blocks:
                h = h + b(h)
            return self.head(
                torch.cat(
                    [
                        h[:, :, a:b].mean(2)
                        for a, b in [(0, 9), (9, 15), (14, 18), (18, 29), (29, 40)]
                    ],
                    1,
                )
            )

    return Expert(dim, classes)


def load(path, classes, device):
    import torch

    saved = torch.load(path, map_location="cpu", weights_only=True)
    network = expert_network(saved["dim"], classes)
    network.load_state_dict(saved["state"])
    return network.to(device).eval()


def blend(expert, logits, z, ok, device):
    """Blended family logits at the contacts whose ok is true.

    logits: (n, K) event model family logits at the contact steps; z their
    windows; ok: court calibration at each contact. Other rows are returned
    unchanged.
    """
    import torch

    out = np.array(logits, np.float32, copy=True)
    if len(out):
        with torch.inference_mode():
            window = expert(torch.from_numpy(z).to(device)).float().cpu().numpy()
        mixed = (1 - BLEND) * out + BLEND * window
        out[ok] = mixed[ok]
    return out
