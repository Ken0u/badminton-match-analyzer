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

The prospectively sealed original-host assembly remains pending. No actual
joined ledger or new source-reading result is claimed at this preparation
checkpoint. Exact PR/main CI, normal controller integration and independent
complete public delivery also remain pending. Images, labels, descriptions,
per-contact intervals and joined occurrence data remain private. Only
reproducible code, this protocol and aggregate results are published.
