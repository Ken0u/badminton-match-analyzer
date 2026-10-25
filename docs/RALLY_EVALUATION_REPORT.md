# Saved serve and rally-end evaluation

Issue [#256](https://github.com/Ken0u/badminton-match-analyzer/issues/256)
adds evaluation of saved experimental boundary proposals to the API, CLI and
review editor. This is evaluation software verified with generated fixtures;
it supplies no new independent badminton references or accuracy result.

## Review declarations

Review windows carry three independent declarations: `contacts_complete`,
`serves_complete` and `rally_ends_complete`. All default to false. Existing
annotations retain undeclared boundary coverage, including windows previously
marked contact-complete. The editor exposes separate controls and preserves
them through saving, reloading, revision history and JSON export. Declaring
completeness means missed events have also been considered; accepting a proposal
does not establish exhaustive coverage.

Each boundary kind uses only explicitly complete live windows fully covered by
the saved run. Conflicting scene review excludes a window. Reviewed and corrected
events supply references; predicted annotations do not. Skipped windows, reasons
and excluded reference/proposal IDs remain in the report. Eligible empty windows
can count false positives, missing proposals count misses, and absent eligible
coverage produces unavailable metrics.

## Two different temporal comparisons

Representative timing uses maximum-cardinality, minimum-total-time-error
one-to-one matching at an explicit source-time tolerance (default 0.12 seconds).
It reports precision, recall, F1, matches, unmatched IDs and timing errors.
If any relevant reviewed reference has uncertain inclusive bounds, its entire
review window is excluded from this point comparison with an explicit reason.
Other exact windows remain eligible. A proposal's representative frame remains
a navigation location when its interval is uncertain; the score does not turn it
into a measured physical boundary.

Inclusive interval compatibility uses separate maximum-cardinality one-to-one
overlap matching. It preserves interval widths, paired bounds and unmatched IDs.
This is possible temporal support, without an accuracy or F1 interpretation.
An overlap cannot establish an exact service contact or rally-ending time.
Serve references use contact uncertainty; ending references use terminal
uncertainty. Neither clip edges nor a last stroke establish a boundary.

Both comparisons stay within uninterrupted reviewed ranges. They cannot match
across review gaps, camera boundaries or source timestamp discontinuities.
Intervals crossing those limits remain excluded instead of being shortened.

## Source and report ownership

The evaluator requires matching video identity/hash, a valid native timestamp
sequence and current camera, scene and court context. Candidate ordinals,
inclusive ranges, representative times and optional evidence/time bounds are
validated against the original source clock. It rejects malformed, nonfinite,
stale or mismatched inputs and does not mutate inputs or invoke inference.

`POST /api/videos/{video_id}/evaluate` accepts optional `rallies_run_id`;
`badminton evaluate VIDEO_ID --rallies-run RUN_ID` supports the same saved-run
comparison. Either can evaluate rallies alone. Existing contact, shuttle and
recognition inputs remain supported. Only registered completed same-video
rally jobs can supply artifacts. Reports bind source hash, annotation revision
and run identity and expose `rallies.kinds.serve` and `rallies.kinds.rally_end`.

The editor includes its current rally run when measurement is requested. It
displays separate timing and interval-support results, excluded coverage and
uncertainty explanations. The download contains the same report. Changed rally
inputs invalidate displayed results and downloads; cancellation, late responses,
source/revision mismatches and change-away/change-back races retain existing
ownership guards. Stable polls preserve valid results. No automatic evaluation
request or retry is added.

## Verification and limits

Generated tests cover singles/doubles, native variable-rate timing, independent
coverage, empty/negative/uncertain cases, malformed identity/bounds/context,
cuts/gaps, duplicate IDs and matching counterexamples. API/CLI checks cover
saved coverage/history/export, completed-job validation, source mutation,
tolerance, run lineage and mixed evaluation requests. Frontend and browser
checks exercise persistence, report display/download and stale-response guards.
Local verification passes **3,226 Python tests**, with four optional skips,
including **100 pure boundary evaluator tests** and **25 API/CLI tests**.
All **180 frontend tests** and **17 generated editor browser groups** pass.
Type/contract/build/stage, Ruff lint/format, frontend formatting, dependency,
repository UTF-8/LF/JSON/local-link and whitespace checks pass. An intermediate
formatting failure was corrected; the failed receipt is preserved. Browser
cleanup is complete, and recorded original fixture lifetimes are independently
absent. Existing pinned dependencies and the cached browser were reused.

Exact PR/main CI and public delivery receipts belong on the owning issue after
controller integration. Local software checks alone do not establish successful
integration or publication.

No private scientific frames or labels were read or transferred, no model was
run or promoted, and no new dependency was added. Existing scientific complete
references remain **0/2**, with all four research eligibility flags false.
The [evidence join report](RALLY_EVIDENCE_JOIN_REPORT.md) retains the unresolved
source/clock/rights and independent-reference requirements. Complete serve/end,
player identity, shuttle, contact and family/side accuracy across unseen singles
and doubles matches remains unestablished. Next measure against independently
adjudicated, source-aligned complete live coverage before model selection or
promotion.
