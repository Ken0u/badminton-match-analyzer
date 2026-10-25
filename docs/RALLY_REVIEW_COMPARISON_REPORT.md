# Prospective native review comparison

[Issue #282](https://github.com/Ken0u/badminton-match-analyzer/issues/282) supplies
the comparison consumer missing between the [prospective review planner](RALLY_REVIEW_PLAN_REPORT.md)
and the [single-stream structural contract](RALLY_REVIEW_CONTRACT_REPORT.md).
It uses generated JSON only and preserves the historical evidence joins.
It neither opens scientific source evidence nor authorizes another assessment.

The pure `rally_review_comparison.compare_streams` consumer requires original
plan bytes and explicit A/B document-byte lists. It validates every stream with
the unchanged structural validator, binding the same source, native clock,
selected source, original plan bytes and document chains. Optional source
adjudication remains a separate stream and never replaces the original readings.

Every expected native frame survives empty prefixes, unavailable plans and
disagreement. Camera-change, scene and contact fields each have one comparison
status per frame: missing, overlap conflict, unknown, known agreement or known
disagreement, in that precedence. Their status counts sum to the full native
denominator. Separate diagnostic flags retain simultaneous missing, conflicting
and unknown conditions; those flag counts are explicitly non-additive.

All overlap occurrences retain their original document/hash pointers. A lane
with different values across occurrences, including a known/unknown mixture,
is conflicting. No majority or favorable occurrence is selected. Known A/B
agreement requires a single consistent known value in both streams. Agreement
compares supplied labels; it proves neither correctness nor assessor independence.
Not-observed and unknown do not establish physical absence.

Original actor, event, camera-view, boundary and correspondence variants remain
document-local with qualified original-byte pointers. Equal strings, overlapping
intervals, a last stroke or stopped play establish no identity, event count or
exact boundary. Family/side uncertainty and censoring remain intact. Discrepant
frame/field records provide prospective source-review questions, not resolutions.
Execution provenance and assessor independence remain unavailable from these
documents. No contact, family or identity score is computed.

## Offline consumer

```text
python scripts/compare_rally_review.py --plan PLAN.json --independent-a A.json --independent-b B.json --output PRIVATE_RESULT.json
```

Each document manifest uses the existing
`{"schema_version":1,"documents":["relative-document.json"]}` format.
Add `--source-adjudication ADJUDICATION.json` for a separate adjudication stream,
and `--source SOURCE_ID` for a plan bundle. The complete supplied raw bundle
remains bound even though comparison covers only the explicitly selected source.

The CLI reuses the existing bounded ordinary-JSON reader unchanged. Individual
plan/manifest/document limits remain 16 MiB / 1 MiB / 2 MiB. Across streams it
permits at most 4,096 documents and 128 MiB of combined JSON inputs, with a
128 MiB output cap. Validation and comparison finish before an exclusive output
is opened. Unsafe, symlink/reparse, duplicate, malformed or observably changing
inputs and existing outputs are rejected. Captured bytes supply both parsing
and hashes. Filesystem checks cannot establish hidden changes to source history.

Detailed judgments, local identities, original hashes and all variants stay in
the explicitly named private result. Stdout contains aggregate counts and fixed
limitations only. No referenced image is opened; there is no Store, network,
credential, assessor or model access. Real scientific use requires its own
granted and, where applicable, explicitly authorized source-review protocol.

## Verification and limits

Generated pure and actual CLI-subprocess tests exercise complete/prefix/empty
and unavailable inputs, source offsets/clocks/orientations and bundle selection,
known/unknown/disagreeing and overlap-conflicting readings, optional adjudication,
qualified equal-ID variants, raw-byte chains, invalid inputs, file/read limits,
private stdout and preservation of inputs/existing outputs. Subprocess tests
record the actual original launcher/worker lifetimes before releasing startup.
Final verification passes **1,000 focused / 4,346 full Python tests**, with four
optional full-suite skips. Ruff lint/format, dependencies, repository
UTF-8/LF/JSON/local links and whitespace checks pass. Executable/test bytes stayed
unchanged throughout the final focused/full runs; all recorded launcher, worker
and descendant lifetimes are independently terminal. Exact PR/main/controller
and independently verified full public delivery belong on the owning issue.

Six concrete generated scenarios retain all nine frames per field, including
eight scene disagreements and one known/unknown overlap conflict. Six equal-ID
actor/event variants remain separately qualified; separate adjudication leaves
the original A/B questions and counts unchanged. Empty prefixes and unavailable
plans retain the full native denominator.

Two initial lint-only findings were preserved and corrected before testing.
The original focused run also passed 1,000 tests. The interrupted first full run
has no pytest completion or exit receipt and remains incomplete; all 184 recorded
original test lifetimes were terminal, the checker command absent and source
unchanged before rerunning. The earlier passing full run retained 4,310 tests.
Final checks include the delivered nonoverlapping #281 import-stability and
#284 audio-alignment changes. All six owned file bytes were preserved across
the earlier rebase and subsequent merge of main; published history is retained.

Actual new scientific inputs, labels, predictions, assessor sessions and image
bytes are zero. Existing #250/#262/#270 protocols and historical records remain
unchanged. Complete references remain **0/2**, all four eligibility flags false,
and #62/#66/#67/#71 unfinished. Structural coverage and consistent supplied labels
do not establish correct automatic full-match badminton annotation.
