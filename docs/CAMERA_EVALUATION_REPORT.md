# Offline camera-cut evaluation

[Issue #309](https://github.com/Ken0u/badminton-match-analyzer/issues/309) adds
the transition evaluator called for by the [camera-boundary milestone](CAMERA_BOUNDARY_REPORT.md).
It scores saved raw `segments` scans against explicitly supplied review windows.
It changes no detector, threshold, annotation, prediction or model. This increment
uses generated inputs only; real camera-cut accuracy remains unmeasured.

The pure `badminton.camera_evaluation.evaluate_camera` function requires matching
source IDs/SHA256 digests on video, run and reference, and a complete finite,
nonnegative, strictly increasing native timestamp list. Every original boundary
and reference is validated before filtering, including incomplete review.
Frame ordinals are strict integers and supplied times must match the native
frame within 20 microseconds. No nominal-FPS clock is substituted.

Only unreviewed raw boundaries qualify. Corrected overlays are rejected rather
than scored as automatic predictions. Sorted unique `cut_frames` must exactly
match the original boundary records. `visual_cut` and `timestamp_discontinuity`
remain separate; gap reasons must exactly match native timestamp steps above
the scan's positive declared gap threshold, using the producer's 10 ns margin.
The declared threshold is reported, not tuned by evaluation.

Reference schema 1 is an explicit JSON object:

```json
{
  "schema_version": 1,
  "video_id": "generated-example",
  "video_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "windows": [
    {
      "id": "review-window",
      "start_frame": 0,
      "end_frame": 20,
      "cuts_complete": true,
      "cuts": [{"id": "cut-reference", "frame": 5, "time_s": 7.2}]
    }
  ]
}
```

Windows are sorted, nonoverlapping half-open native ranges. A cut names the
first frame of a new view. Both adjacent frames must lie within the same
complete window and the run, and their transition must have no timestamp gap.
Adjacent windows do not supply their shared edge. Missing or incomplete review
never supplies negative truth. Unresolved transition intervals require incomplete
windows; this exact-cut schema cannot resolve uncertainty.

Matching maximizes one-to-one match count, then minimizes total absolute native
time error, separately within each uninterrupted reviewed window. Default
tolerance is explicitly 0.12 seconds. The report retains every original,
eligible and excluded cut count, skipped windows, timestamp gap counts and a
complete partition of run transitions into eligible, gap, window edge,
unreviewed and incomplete review. Detailed matches and unmatched IDs stay in
the private result. Missing complete transition coverage produces an explicit
status and null metrics. Negative-only complete review retains coverage and
undefined precision/recall/F1 as null, without inventing a true-negative score.

```text
python scripts/evaluate_camera.py --video VIDEO.json --timestamps TIMES.json --run RAW_SCAN.json --reference REVIEW.json --output PRIVATE_RESULT.json
```

`TIMES.json` is the native timestamp list. The CLI reads only the four explicit
ordinary JSON files and binds SHA256 hashes to the same captured bytes used for
parsing. Existing bounded JSON/path readers reject duplicate/nonfinite JSON,
symlink/reparse paths and observed read changes. Limits are 16 MiB per file,
64 MiB combined input/output, 1,000 windows, 10,000 cuts per stream and one
million matching cells across continuous ranges. Validation finishes before an
exclusive output is opened. Failure exits 2 and preserves input/existing-output
bytes. Stdout contains aggregate coverage and metrics only. There is no source
image, Store, credential, network, model, inference or training access.

Metadata validation cannot prove media-byte identity, assessor independence,
reference correctness or exhaustive inspection. Camera boundaries do not label
live/replay context or establish rally, contact, identity or stroke accuracy.
Complete scientific rally references remain **0/2**; the full analyzer objective
and source eligibility requirements remain open. No image assessment allowance
is renewed and no consumed holdout is accessed.

Verification: **449 focused and 4,867 full Python tests pass**, with four optional
GPU skips. Required Ruff lint/format, dependency consistency, repository
UTF-8/LF/JSON/local links and whitespace checks pass. Generated pure and actual
CLI subprocess tests cover positive/negative/missing outputs, competing matches,
VFR/nonzero clocks, review edges/partial coverage, gaps, malformed hidden rows,
corrected artifacts, strict JSON, size/path limits and input/output preservation.
Executable bytes stayed fixed during verification and all observed verification
lifetimes were independently terminal. Initial import ordering/lint cleanup and
a local checkpoint-helper encoding failure are preserved; the latter stopped
before any public write and did not affect production source.

Exact PR/main CI, controller integration and independent public delivery receipts
belong on the owning issue; software checks establish no source accuracy.
