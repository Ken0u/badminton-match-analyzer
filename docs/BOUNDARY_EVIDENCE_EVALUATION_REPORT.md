# Boundary evaluation respects declared evidence context

[Issue #278](https://github.com/Ken0u/badminton-match-analyzer/issues/278)
repairs a generated measurement failure in the
[saved boundary evaluator](RALLY_EVALUATION_REPORT.md). On delivered source
`032f121d41924a47a5b4bc3a35a6bb0ed2bc36b5`, a point serve or ending at frame 20
with declared evidence `[19,22)` received representative-time F1 **1.0** and
one interval match even when a camera cut, native timestamp gap or unreviewed
frame separated frame 19 from frame 20. All six original cases are preserved.
They contain generated records only, without scientific source inspection.

The evaluator already validated evidence bounds and required the proposed
boundary interval to remain inside reviewed source context. Its comparison
eligibility did not use the separate declared evidence range. A point after a
barrier could therefore conceal evidence spanning that barrier. This is distinct
from the earlier contact/recognition context repairs and does not invalidate
their original checks.

## Comparison behavior

For each boundary kind, declared half-open evidence must now fit inside one
eligible uninterrupted reviewed range. Camera cuts, native timestamp gaps,
incomplete or excluded review windows and scene exclusions retain their existing
meaning. Evidence may start or end exactly at a source barrier because its end
is exclusive. Existing malformed, partial and out-of-run bounds still fail
validation before scoring.

The same eligible proposals feed representative timing, inclusive interval
compatibility and their candidate counts. The six generated failures now retain
their reviewed coverage and reference, exclude the unsupported proposal, report
zero interval matches and count the exact unmatched reference as a miss.
Other eligible matches and false positives remain in their original denominators.
Uncertain reference intervals keep interval support without becoming exact timing
truth; an excluded proposal cannot earn that support either.

`coverage.candidate_evidence_context` records declared and unavailable candidate
IDs and explicit evidence exclusions with their original bounds and reasons.
The existing excluded-candidate IDs remain available. Missing legacy evidence
metadata remains usable under the prior boundary-interval checks and is reported
as unavailable. Neither an absent range nor a syntactically valid range proves
the complete scientific evidence used to produce a proposal.

No saved proposal, annotation, source timestamp, completeness declaration,
historical report, inference output or scientific acceptance rule is rewritten.
The application API and offline evaluation CLI consume the same pure evaluator.

## Verification and remaining limits

Generated tests cover both boundary kinds, source barriers and exact half-open
endpoints, review gaps, incomplete/excluded coverage, uncertain intervals,
legacy unavailable evidence, valid other matches, false positives, missed
references and input immutability. Actual disposable Store/API and offline CLI
cases retain generated source, clock, annotation, job and proposal bytes/state.
An unaffected second boundary kind remains correctly scored. Existing mixed
contact requests and contact/recognition regressions remain part of verification.

Final verification passes **788 focused / 4,236 full Python tests**, with four
optional full-suite skips, plus Ruff lint/format, dependencies, repository
UTF-8/LF/JSON/local links and whitespace checks. Executable/test bytes stayed
unchanged throughout both final runs; all observed launcher, worker and descendant
process lifetimes are independently terminal. The six generated before/after
cases retain identical reviewed/reference denominators, F1 0 and zero interval
matches after repair. An initial formatting-only check found three layout changes
in the added pure tests; that check and its correction remain separate from test
results. Exact PR/main checks, controller integration and independently audited
complete public delivery belong on the owning issue.

The first focused/full rounds retained two incorrect new-test expectations:
beside an uncertain reference range, a separate complete negative range correctly
retains an empty point-score report. Their other 786 focused and 4,234 full
tests passed, with four full-suite skips. Both failures and stable first-round
source/process receipts are preserved. After the full run became terminal,
only those assertions were corrected to preserve that negative coverage; the
evaluator implementation stayed byte-identical.

This task opens no private scientific input, frame, label or prediction. New
assessor sessions and image bytes are **zero**. Complete scientific references
remain **0/2** and all four research eligibility flags remain false. The other
host's export-admission repair, original environments/data/research and deprecated
`PROGRESS.md` are preserved. Correct comparison eligibility and green software
checks do not establish correct automatic annotation across a badminton match.
