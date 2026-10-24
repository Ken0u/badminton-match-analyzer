# Joined native and temporal rally evidence

Prepared October 24, 2026 for [issue #250](https://github.com/Ken0u/badminton-match-analyzer/issues/250).

The [protocol](../data/manifests/rally_evidence_join_v1.json) joins the
[native occurrence census](RALLY_REFERENCE_DIAGNOSTICS_REPORT.md) with the
[completed sparse temporal pilot](RALLY_TEMPORAL_CONTEXT_REPORT.md), retaining
each original observation. This is metadata preparation for a separately
authorized contiguous source review. It supplies no new image reading or
resolved contact, identity, scene or boundary truth. The historical result stays
**0/2 complete references**, **0/2 fully supported observed-contact label slots**
and four false eligibility flags. Automatic full-match accuracy remains unproven.

## Prospective review rules

Every native ordinal has its source/clock identity, PTS/time base, orientation,
availability and original image identity. Native observations retain their
document, row, canonical seal and original document/receipt byte hashes. Sparse
scene/play/actor observations appear only at their sampled ordinals. All three
native lanes and all three coarse lanes remain separate; matching lane names or
actor strings do not link sessions or people. Native actor definitions remain
local to their original documents. No scene label is filled across an unsampled
frame, no `none_observed` becomes verified absence, and no `stopped_play` becomes
a precise ending.

The private ledger retains repeated event mentions, conflicting variants,
inclusive intervals, overlapping distinct-contact keys and every unknown.
Diagnostic agreement, conflict, unknown and unavailable counts describe support,
not accuracy. Private review questions cite the exact source/clock/frame range
and original occurrences. They do not apply majority voting, contact merging,
timestamp averaging or an actor remap.

The public rubric requires fresh independent contiguous native evidence for
whole-window scene context, physical contact correspondence across overlapping
chunks, locally supported actors, an observed serve/opening and an observable
terminal event. Hidden evidence stays unknown or interval-valued. Any future
source/image assessment requires a separate frozen task and specifically
authorized payload/destination. This protocol contains no assessment dispatcher
or image allowance and renews none of the earlier scientific clocks.

## Original-host execution contract

[The command](../scripts/join_rally_evidence.py) provides `freeze`, `run` and
read-only `audit` phases. A clone needs the original private artifacts; generated
fixtures cannot replace them. Use the original project virtual environment and
an isolated clean committed consumer after generated and full verification.

```text
python scripts/join_rally_evidence.py freeze --root ORIGINAL_ROOT --output ORIGINAL_ROOT/.cache/rally250-joined-v1 --grant CURRENT_COMMITTED_GRANT
python scripts/join_rally_evidence.py run --root ORIGINAL_ROOT --output ORIGINAL_ROOT/.cache/rally250-joined-v1 --timestamp PROSPECTIVE_ISSUE_SEAL
python scripts/join_rally_evidence.py audit --root ORIGINAL_ROOT --output ORIGINAL_ROOT/.cache/rally250-joined-v1 --timestamp PROSPECTIVE_ISSUE_SEAL
```

The prospective owning-issue seal binds context, consumer revision and protocol.
The fresh metadata interval is four hours from the genuine original-host grant;
lease renewal cannot extend it. Credentials are removed from the execution
environment. The real shared Store admits the assembly. A clean subprocess
replays frozen historical provenance before scientific JSON is parsed. Original
execution identities, process creation times/cwd/commands, Store completion,
artifacts, immutable intervals and bounded logs are rechecked. Historical writing
preparation, assessment, aggregation and sealing helpers are never invoked.

Outputs are exclusive and private. An attempt/failure is preserved and blocks
an implicit repeat; timeout does not permit a process signal or restart. The
audit requires terminal original lifetimes, matching Store/artifact evidence,
unchanged sealed inputs and exact reconstruction of the joined ledger from
the original occurrences. Limits are 1 GiB new outputs and 8 GiB cumulative
scientific outputs, at most three diagnosed repair rounds, zero new scientific
sessions and zero outbound image bytes. There is no source download, image
viewing/decoding/rendering, model inference, training or holdout access.

## Verification and actual result

Generated verification passes **160 focused and 3,101 full Python tests**,
with four optional skips, plus Ruff, formatting, dependency consistency,
repository JSON/local links, UTF-8/LF and diff checks. Recorded final test
lifetimes are independently absent. The earlier passing full run and generated
fixture failures are preserved. Final checks cover lease renewal without a
scientific-clock extension, process identity/lineage, artifact corruption,
exclusive failed-attempt fencing, exact denominators and retained uncertainty.

The tested clean consumer `001ddea7734c189049363fa33bedc88c7544705a` was
committed before the [prospective owning-issue seal](https://github.com/Ken0u/badminton-match-analyzer/issues/250#issuecomment-6390720840).
The single original-host assembly completed under the real shared Store in
about 175 seconds. A separate post-exit audit reconstructed the exact ledger,
verified unchanged sealed inputs and matching Store/terminal/artifact evidence,
and found all 12 recorded outer/worker lifetimes absent. The historical gate
verified 1,014 native plus six coarse unique execution identities and all 256
targeted references before scientific JSON was opened. Original clocks,
failures, exclusions and acceptance consumers remain unchanged.

| Source | Native frames | Sparse samples | Unsampled native frames | Native frame occurrences, each lane | Native event occurrences, A / B / adjudication |
| --- | ---: | ---: | ---: | ---: | ---: |
| Singles | 991 | 34 | 957 | 1,333 | 43 / 40 / 47 |
| Doubles | 541 | 19 | 522 | 707 | 6 / 9 / 8 |

The ledger retains **6,120 native frame occurrences**, **153 native event
occurrences**, **159 coarse frame occurrences** and all original document-local
actor definitions. These are occurrences, not counts of distinct physical
contacts or people. All 1,532 native frames remain, including the 1,479 frames
without coarse sampling. No native image or selected sample was unavailable.
The private index contains 1,894 prospective review questions; those questions
are neither resolved annotations nor independent evidence.

| Source | Scene occurrence-pair agreement | Conflict | Unknown | Unavailable pair support |
| --- | ---: | ---: | ---: | ---: |
| Singles | 0 | 14 | 373 | 11,610 |
| Doubles | 93 | 99 | 6 | 6,165 |

Each native occurrence is compared with each coarse lane only at the exact
ordinal. Repeated native observations and the nine lane combinations can count
an ordinal more than once. Unavailable pair support here means a required
observation is absent, principally because coarse context was not sampled at
that ordinal; it does not mean a missing native image. These support counts are
not frame accuracy, expert agreement or resolved scene truth. The original
single-lane overlaps, unsupported contact actors and opening/terminal failures
remain intact. Nothing is voted, averaged, linked or promoted.

Actual new scientific sessions and image payload are **both zero**. The private
ledger is 55,629,024 bytes. Aggregate SHA256 is
`f76b689df32d35d0d79c45cb13a7676c2398529d6ca988b797a0dbd5afe5fdc9`;
ledger SHA256 is
`cdf01c00d00134825d8dd095708dfabe1ca9aa562e34ab40b4257bfca179b40d`.
Only hashes and aggregate counts are published; images, labels, descriptions,
per-contact intervals, occurrence references and review questions stay private.

Exact PR/main CI, normal controller integration and independent complete public
delivery remain pending at this report checkpoint; the owning issue carries
their eventual evidence. **Complete references remain 0/2** and all four
eligibility flags stay false. This task does not complete #62, #66, #67 or #71,
authorize another image pass, training or promotion, or demonstrate full-match
badminton annotation accuracy. `PROGRESS.md` and existing environments, data,
models, application annotations and predictions remain preserved.
