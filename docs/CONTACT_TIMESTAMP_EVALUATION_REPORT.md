# Contact and recognition evaluation at source timestamp gaps

[Issue #267](https://github.com/Ken0u/badminton-match-analyzer/issues/267)
keeps evaluation inside continuous native source-time context. Correctly
declared frame/time pairs can still belong to opposite sides of an input gap.

## Reproduced measurement error

On source `39bdbc6b5f38c3d9d3d0756e9617177de3ee14b3`, a generated reference
at frame 19 and proposal at frame 20 match across a 0.11-second native timestamp
step. That step exceeds the contact producer's 0.1-second maximum source step,
but lies inside the evaluator's default 0.12-second matching tolerance.
Contact F1, drive-family F1 and complete-event F1 all equal 1.0. Both declared
times correctly match the source clock; this is separate from the inconsistent
frame/time defect repaired in [#264](EVALUATION_CLOCK_REPORT.md).

The four-case pure reproduction retains a continuous 0.04-second control and
unchanged generated inputs. No real match media, scientific labels or model
outputs are read. The previous evaluator separated known camera edits and
review gaps but did not split eligible coverage at native timestamp gaps.

## Continuous comparison domains

When a validated native source clock is supplied, evaluation identifies gap
ordinals using the contact producer's existing `MAX_FRAME_STEP_S` and the
existing 1-nanosecond floating-point comparison allowance used by boundary
evaluation. These barriers join camera cuts when splitting eligible reviewed
ranges. Their native frame identity is preserved; no frame is removed or
renumbered and times are not reconstructed from FPS.

Representative-time matching, tighter-tolerance matching and inclusive
interval support share the separated domains. A before-gap reference and an
after-gap point proposal stay in their respective domains, counting as one
miss and one false proposal instead of a true positive. All eligible reviewed
frames remain represented once in coverage. Same-side matches and continuous
variable frame timing retain their existing interpretation.

An inclusive proposal interval spanning a gap is excluded as
`contact_interval_crosses_source_timestamp_gap`. A half-open evidence context
spanning a gap is excluded as `evidence_context_crosses_source_timestamp_gap`.
Each exclusion retains the proposal ID and reason. An interval ending at the
last pre-gap frame remains on the earlier side; an interval beginning at the
first post-gap frame remains on the later side. An evidence range ending at
that first post-gap ordinal is half-open and does not include the later side.
The navigation frame cannot shorten the original uncertainty or evidence.

Coverage adds `source_timestamp_gap_frames`, separate from `camera_cut_frames`.
Native gaps do not certify camera metadata, and camera review cannot remove a
source timestamp discontinuity. Existing source-hash validation still runs
before clock/prediction parsing. Invalid native clocks remain rejected.
Compatible direct calls without a clock keep `prediction_clock_status:
unavailable` and their previous comparison behavior; an empty gap list in
that case does not establish continuous source time.

Recognition consumes the contact evaluator's exact eligible reference/proposal
IDs and matches. Source-gap exclusions therefore cannot reappear as family,
side, hitter or complete-event credit, or as classification false outputs.
Eligible unmatched point proposals still count as false outputs; unanswered
references remain misses. Scene/camera/review exclusions, inclusive uncertainty,
unknown/assisted labels and existing unavailable cases retain their meanings.

## Verification and limits

Generated pure and registered API/CLI cases cover constant/variable clocks,
nonzero origin, threshold boundaries, multiple gaps, touching windows,
inclusive/half-open boundary cases, interval/evidence exclusions, camera and
source barriers together, missed/false/empty outcomes and unchanged saved inputs.
The API and CLI already obtain the registered source clock through #264; this
repair changes no route, clock ownership or inference stage.

All **756 focused and 3,953 full Python tests pass**, with four optional skips.
Ruff lint/format, dependency consistency, repository UTF-8/LF/JSON/local links
and whitespace checks pass. Final executable/test bytes remained unchanged
during verification; recorded original and worker process lifetimes were checked
after exit. The first full-check attempt stopped on a new-test lint finding;
the final run uses `pairwise` and retains the failed attempt. The core subtask's
initial new-test expectation and regex-lint failures also remain preserved.
No existing test was weakened to accept cross-gap credit.

Exact PR/main CI and independent public delivery receipts belong on the
[owning issue](https://github.com/Ken0u/badminton-match-analyzer/issues/267)
after normal controller integration. No real scientific assessment, image
transfer, training, model/default/dependency/policy change or automatic weight
installation occurs.

Scientific complete references remain **0/2**, with all four research eligibility
flags false. Correct software measurement domains do not establish accurate
automatic annotations throughout unseen badminton matches.
