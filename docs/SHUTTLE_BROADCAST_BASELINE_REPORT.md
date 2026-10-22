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
behavior, not shuttle accuracy. The bounded native run and fixed interpretation
are now recorded below.

## Results on the frozen development cohort

All results describe agreement with the immutable agent source assessments. The fixed localization disk is 11.015 pixels at 1920 by 1080. No threshold, source membership or model changed after predictions.

| Reference state | Cases | Output available | Selected observations | Observed components |
| --- | ---: | ---: | ---: | ---: |
| not_visible | 5 | 5 | 0 | 0 |
| unknown | 85 | 85 | 32 | 71 |
| visible_localizable | 37 | 37 | 22 | 39 |
| visible_unlocalizable | 1 | 1 | 0 | 0 |

For all 37 localizable references, the default point is within the fixed disk in 16 cases (43.24%), displaced in 6, missing in 15, and unavailable in 0. The original-uncertainty sensitivity contains 16/37 default points; it does not replace the fixed disk.

An already observed component falls inside the fixed disk in 17/37 cases. In one case only an alternate component agrees. This describes component selection and supplies no replacement detector or oracle result. Twenty localizable cases have no agreeing observed component, so a component-selection change alone cannot resolve those cases under this recipe.

Among all five supported negatives, 0 have false observations, 5 have absence, and 0 are unavailable. The one unlocalizable and 85 unknown cases have no fabricated coordinate errors or negative labels.

Every planned center has an available output; no unavailable cases were removed.

### Source support

| Group | Cases | Available | Localizable | Within | Displaced | Missing | Unavailable localizable | Negative support | False observations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| H1setLK1tig | 64 | 64 | 15 | 3 | 3 | 9 | 0 | 3 | 0 |
| go2uajSiBnE | 64 | 64 | 22 | 13 | 3 | 6 | 0 | 2 | 0 |

Agreement is 13/22 for the singles source and 3/15 for the doubles source. These
small, agent-labeled source strata do not establish generalization or compare
the difficulty of singles and doubles in general.

### Center-only scene support

| Group | Cases | Available | Localizable | Within | Displaced | Missing | Unavailable localizable | Negative support | False observations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| non_play | 82 | 82 | 14 | 0 | 4 | 10 | 0 | 5 | 0 |
| play_view | 41 | 41 | 21 | 16 | 2 | 3 | 0 | 0 | 0 |
| replay | 3 | 3 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |
| unknown | 2 | 2 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |

### Overlapping difficulty support

| Group | Cases | Available | Localizable | Within | Displaced | Missing | Unavailable localizable | Negative support | False observations |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| blur | 29 | 29 | 19 | 11 | 2 | 6 | 0 | 0 | 0 |
| camera_transition | 4 | 4 | 1 | 0 | 1 | 0 | 0 | 0 | 0 |
| distractor | 38 | 38 | 5 | 4 | 0 | 1 | 0 | 0 | 0 |
| fast_flight | 3 | 3 | 3 | 2 | 0 | 1 | 0 | 0 | 0 |
| non_play | 80 | 80 | 13 | 0 | 4 | 9 | 0 | 5 | 0 |
| occlusion | 36 | 36 | 5 | 0 | 0 | 5 | 0 | 0 | 0 |
| ordinary | 2 | 2 | 2 | 0 | 1 | 1 | 0 | 0 | 0 |
| small_far | 32 | 32 | 19 | 14 | 2 | 3 | 0 | 0 | 0 |
| unresolved | 87 | 87 | 1 | 0 | 0 | 1 | 0 | 0 | 0 |

Difficulty groups overlap and cannot be added as disjoint supports. A zero localizable support has undefined agreement. Center-only scene observations do not establish the scene of the complete processing window.

## Execution and seals

The original-host process exited and the exact shared Store job is `completed`. Worker wall time is 1310.375 seconds across one preserved attempt; 128/128 windows have successful raw output. The task permits 1,800 cumulative seconds; no retries or replacement inference were used.

| Accounting | Count |
| --- | ---: |
| Requested output rows | 8192 |
| background_reader_yields | 8192 |
| camera_scan_yields | 10712 |
| decoder_frames_background | 20632 |
| decoder_frames_camera_scan | 22093 |
| decoder_frames_inference | 20632 |
| decoder_frames_total | 63357 |
| decoder_opens | 422 |
| inference_reader_yields | 8192 |
| median_background_samples | 2952 |
| model_background_slots | 7175 |
| model_calls | 7175 |
| model_sequence_slots | 57400 |

Decoder totals include seek/preroll decoding; reader yields, source-resolution median samples and overlapping model slots are separate quantities. Each unchanged model call consumes eight sequence frames and one background slot. Outputs remain raw and unrepaired.

The prospective freeze was [timestamped before execution](https://github.com/Ken0u/badminton-match-analyzer/issues/179#issuecomment-6330193993). Private context binds complete window memberships, recursive consumers/runtime, original inputs and application-preservation seals. Terminal outputs were [externally timestamped before interpretation](https://github.com/Ken0u/badminton-match-analyzer/issues/179#issuecomment-6330501523).

| Evidence | SHA-256 / revision |
| --- | --- |
| Native consumer commit | `ddb6025f5dcdb9ff53524bb560d43202b2e39368` |
| Protocol | `3df7ae9ddd7e94b57b48ad82420ab3b008d3fbb90614bb94e69c1e7700914ebe` |
| Prospective context | `ee87921d645d245548ea3f778c052892faa84f8a538f4fcb782d7068b6407014` |
| Raw terminal inventory | `b40bd382d11f0abe02802146248ec15f44cdade340f824d1f7e8642e58ef1e91` |
| Original-host terminal verification | `93167208e587a89eff0ce51a4bbc3851fca7f4b1ebaccabb4f1c641c8db68c0c` |
| Fixed private interpretation | `60bb3f2b9b88ccf82ba41b86bd36462d8001917fedd06066bb76086a5cbe30cd` |
| Existing checkpoint | `df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a` |

All original source, assessment, consumer, checkpoint and scoped application truth/prediction seals were reverified after capture and interpretation. Raw media, images, labels, process commands and per-case predictions remain ignored. The final report commit changes documentation only; native consumer bytes remain those prospectively frozen.

These measurements identify development failure modes for a separately scoped follow-up. They provide no training, tuning, promotion, redistribution or independent-test eligibility. Persistent shuttle trajectories, contacts, identities and correct complete-match annotations remain unestablished.
