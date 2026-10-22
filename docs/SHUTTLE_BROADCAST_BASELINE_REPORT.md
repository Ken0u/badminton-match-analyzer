# Frozen broadcast shuttle diagnostic

Issue [#179](https://github.com/Ken0u/badminton-match-analyzer/issues/179)
prospectively diagnoses the unchanged TrackNet adapter on the complete
128-center cohort from the [source-only assessment](SHUTTLE_SOURCE_ASSESSMENT_REPORT.md).
This is an agent-labeled development agreement diagnostic. It does not establish
expert accuracy, unseen-match generalization, persistent trajectories or complete
badminton annotations. No model, threshold or application truth is changed.

## Fixed inputs and recipe

The [public protocol](../data/manifests/shuttle_broadcast_baseline_protocol_v1.json)
pins the original two source/clock/packet identities, assessment manifest and
aggregate, existing checkpoint, exact windows and interpretation. Each original
center `c` requests `[max(0,c-32),min(N,c+33))`, giving 8,192 requested rows across
128 windows. Original PTS, native ordinals, orientation and camera boundaries
remain authoritative. Center-only scene labels cannot certify surrounding scene
or calibration intervals.

Inference uses unchanged 512 × 288 inputs, CUDA float16, the eight-frame weighted
overlapping ensemble, source-resolution median backgrounds and default 0.5
components/source-motion selection. Requested output rows are reported separately
from decoder yields, background samples and overlapping model-frame calls.

The primary localization disk has radius `0.005 * hypot(display_width,
display_height)`. All 37 localizable cases remain in its denominator, including
missing or unavailable outputs. Agreement inside the original assessment
uncertainty radius is a separate sensitivity. Five supported negatives report
false observations, absence and unavailable results. The one unlocalizable case
and 85 unknown cases retain availability and observation/component counts without
invented coordinate errors or negative truth. Difficulty groups overlap.

Comparing default selection with any already observed component inside the fixed
disk describes a possible component-selection failure; it never substitutes an
oracle detector. Rights, original-match overlap and upstream membership remain
unresolved. Training, independent-test, model-deployment and redistribution
eligibility all remain false.

## Reproduction and execution status

Use the existing project environment. The CLI clears account credentials and
pins the original root, real shared Store and installed weights before imports.
`prepare` verifies the frozen source lineage and exclusively seals prospective
memberships, consumers, inputs and runtime. Commit and externally timestamp the
seal before `run`. Native execution requires the real shared `run_local_job`
admission; an isolated research Store or CPU fallback is refused. `interpret`
requires externally sealed outputs and original-host process/Store proof.

```powershell
.venv/Scripts/python.exe <task-checkout>/scripts/diagnose_shuttle_broadcasts.py prepare --root . --packet-root .cache/shuttle-source-packets160-v2 --assessments .cache/shuttle172-freeze-v1 --output .cache/broadcast179-native-v1
```

Run and interpretation additionally require the hashes and terminal receipt
printed by their predecessor commands; local private artifacts are not supplied
by a clone. Never overwrite an occupied output or restart a live process after an
observation timeout. Preserve successful windows and partial failures with exact
resume lineage and unchanged context. The task limits native work to 1,800
cumulative seconds and all new outputs, including failed attempts/tests/review,
to 256 MiB.

Pre-native verification passes all 62 focused generated regressions and the
complete project suite: 1,866 passed and 162 optional skips. Ruff checks and
format verification pass across 182 files; environment dependencies and the five
granted UTF-8/LF/JSON/link checks also pass. These checks establish implementation
behavior, not shuttle accuracy. Native capture and interpretation have not
started. Results will be added after the prospective freeze and verified run.
