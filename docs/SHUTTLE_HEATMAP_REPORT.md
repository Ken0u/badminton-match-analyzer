# Frozen development heatmap diagnostic

Owning task: issue 149, under localization roadmap 65. Implementation and native
execution are pending. No new heatmaps or results are available yet.

This diagnostic retains the original 60 familiar development cases, including
25 visible/localizable, seven source-confirmed not-visible and 28 unknown cases.
It does not change model weights, 512x288 inference, the 0.5 detection threshold,
source annotations, the application output schema or default behavior. The
opt-in research observer receives an isolated read-only copy of each completed
temporal-ensemble heatmap. Default inference creates no extra heatmap artifacts.

The fixed [protocol](../data/manifests/shuttle_heatmap_protocol_v1.json) compares
the control's complete native rows to the existing frozen baseline before any
response interpretation. A mismatch blocks comparable interpretation. Raw
heatmaps remain ignored and are not distributed in packages or containers.
Research reproduction requires a clone, the original pinned ignored packet,
labels, baseline/source graph and checkpoint, and an actual resource grant with
the real original shared Store. Detailed process/runtime evidence stays local.

Local response statistics are descriptive diagnostics, not calibrated
probabilities or alternate detections. Unknown cases cannot become negatives,
and missing heatmaps remain explicit. Source-label uncertainty is reported
separately from the nominal fixed tolerance. No threshold sweep, model
selection, training, trajectory filling, new truth or model promotion is in
scope. These familiar agent-assessed sources cannot establish independent or
full-match annotation accuracy. The complete goal and parent 65 remain open.
