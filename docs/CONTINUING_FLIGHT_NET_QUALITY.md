# Continuing-flight net clearance: backend quality check

For newly calculated per-shot fits, an exchange between opposite court ends in the same camera segment is checked up to the next contact timestamp. At the interpolated crossing between the posts, `net_clearance_m` is the fitted centre height minus the fitter's 1.53 m reference. `below_net` (more than 10 cm low) takes precedence over the image-fit quality, including a speed bound, and yields `poor_fit`. `near_tape` (within 10 cm on either side) is diagnostic, not a fault call. This margin is a triage policy, not a measured error bar. `clear` does not certify 3D accuracy. Last shots, unknown/uncheckable crossings and old summaries have no assessment. The original apex, speed and rally outcome are retained. An old outcomes artifact must be recomputed to gain the new diagnostic; merely re-exporting it does not backfill clearance.

## Read-only refit feasibility check

Separate local input clips, distinct from the Floodlit samples; no human 3D ground truth or claim of upstream training independence. Protocol in `scripts/audit_net_refit.py`: use the first 60 chronological continuing pairs (or all if fewer). For a clearly low fit, try changing only launch height, preserving the drag trajectory and velocity. Minimize same-point reprojection RMS over seven offsets between the minimum needed for +2 cm clearance and +0.50 m. Reject any increase greater than 0.002 normalized image heights. This is a narrow feasibility test, not validation of trajectory accuracy. No offsets were applied to any stored fit.

| Clip (processed directory) | Pairs | Results |
| --- | ---: | --- |
| S2 doubles (`e252f592724aba84`) | 41 | 41 ineligible; no informative refit result. |
| ShuttleSet singles (`fa754e1d46cb9fd4`) | 60 | 46 clear, 2 near tape, 7 without a checkable crossing, 5 clearly low. Of the 5, 4 needed more than +0.50 m and 1 failed the image-error limit. |

Reproduce from the checkout with the original local artifacts (not included in a clone):

```text
python scripts/audit_net_refit.py data/processed/e252f592724aba84 dcc39c147883027cc770c491f50c999ea9914506de4a3268ada42c0eac94fe76
python scripts/audit_net_refit.py data/processed/fa754e1d46cb9fd4 5990d6a1de89ae301a6b5a8813ff79de71350af765e9282c7ae2676124100e33
```

Keep the quality check; do not promote the offset refit. A future joint position/velocity refit needs independent crossing evidence, not just agreement with its own clearance constraint. The reserved external singles benchmark was not used.

## What was adopted

Adopted as described: `net_check` and `net_clearance_m` are stored on each assessed `shot.flight`, and `below_net` makes the fit `poor_fit`, so its speed leaves the speed statistics and the app shows no number for it. The weak receiver prior in the fit is kept. The offset refit is not used. On the two supplied videos (re-run 2026-11-19), see `docs/CLIP_STATS.md`, "On the supplied videos", for how many fits this marked.
