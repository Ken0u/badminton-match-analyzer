# Shuttle-selection history in rally proposal evidence

[Issue #294](https://github.com/Ken0u/badminton-match-analyzer/issues/294)
extends the [direct proposal context repair](RALLY_PROPOSAL_EVIDENCE_REPORT.md)
to declared component-selection history. A selected shuttle observation can
depend transitively on earlier observations, beyond the immediate pose-lag and
speed windows. The earlier proposal producer discarded those declared bounds
when reducing a shuttle observation to a point.

## Reproduced behavior

Four generated cases on baseline `5e7ce0e36cf5d5caf394f5421fa2181b0b0b932c`
use the actual component selector, without loading models or decoding scientific
media. After three ordinary observations, each largest component is unreachable
and one smaller component follows the unchanged generated flight. Repeated
selection propagates the first observation into the declared transitive history.
Every selected coordinate equals its original control coordinate.

Both singles and doubles produce these results:

| Proposal | Inclusive timing | Old half-open evidence | Corrected evidence | Partial-review interval matches before/after | Full-evidence matches after |
| --- | --- | --- | --- | --- | --- |
| Serve | [21,28] | [4,32) | [0,32) | 1 / 0 | 1 |
| Ending | [37,40] | [6,71) | [0,71) | 1 / 0 | 1 |

The partial-review denominators remain one reference and 28 or 65 reviewed
frames per case. The existing evaluator excludes the newly declared unsupported
candidate rather than changing references, clipping timing, or manufacturing
another contact. Full declared evidence permits interval compatibility again;
this remains a software timing comparison, never physical boundary truth.

## Repair semantics

Derived rows retain the declared causal half-open shuttle-selection span.
Shuttle speed also retains the preceding point's selection span. Candidate
evidence is the conservative union of these dependencies and the existing
pose/motion, quiet, launch, incoming, fitting, settling and follow-up dependencies.
The producer's transitive start is preserved directly, without truncating it
to the immediate selection-history list or to boundary timing uncertainty.

Legacy observations with neither selection-bound field retain their previous
per-frame meaning. Explicit per-frame bounds produce identical output. Declared
bounds must be paired integer frames, contain the current observation, end at
its exclusive successor, and remain inside one eligible continuous input segment.
Malformed, incomplete, future, excluded or out-of-context history cannot supply
proposal evidence. Missing input rows, camera boundaries, excluded scenes and
source-time gaps break segments. A candidate depending on invalid history
abstains; bounds are never silently clipped across those barriers.

All other valid proposal fields remain identical: IDs, counts/order, kinds,
representatives, uncertainty frames/times, track hints, numerical evidence,
thresholds and defaults. Historical saved artifacts are not rewritten.
The evaluator, API, annotation schema and source clock semantics are unchanged.
This describes declared component-selection dependencies, not all internal
neural-network receptive fields or complete upstream model provenance.

## Cached development controls

The original Windows host verified the same two development contexts, four
perception artifacts, native timestamp arrays, source metadata, catalog and
opaque annotation-document seals frozen for #288 before claiming this task.
Baseline/current replay uses only the inference context and cached observations;
no annotation events, scientific labels, source images or model weights are read.

Both cached candidate documents remain identical in every non-context field,
and these controls retain identical evidence bounds too:

| Input | Proposal | Baseline and corrected evidence |
| --- | --- | --- |
| Singles first view | Ending at navigation frame 610 | [587,637) |
| Doubles first view | Serve at navigation frame 331 | [307,335) |

Original catalog, metadata, annotation-document bytes, timestamps and perception
inputs remain unchanged. The private receipt binds exact code, input and recorded
checkpoint hashes. This is cached development logic replay; it does not establish
fresh inference behavior, source localization or independent accuracy.

## Verification and limits

Generated tests cover both modes/kinds, actual recursive selector history,
preceding-speed history, constant/variable/high-rate/native offset clocks,
legacy controls, malformed fields, future bounds, partial run overlap, missing
rows, cuts, excluded scenes and timestamp gaps. Saved Store/API job and evaluation
tests exercise both modes without stubbing the evaluator or storage. Partial
coverage withholds both matches; complete evidence restores them while original
input artifacts, source metadata, timestamp bytes, saved proposal bytes and
annotation revisions remain preserved.

Final local results: **422 focused / 4,574 full Python tests pass**, with
four optional full-suite skips. Required lint, formatting, dependency, repository
and whitespace checks pass; executable/test bytes remain stable and 969
independently observed process lifetimes are terminal.

The first focused harness listed a nonexistent test module and exited before
running tests. Its output and terminal process observations remain preserved;
the corrected harness uses existing test modules. The first full harness stopped
on five dictionary-style lint findings in new tests; these were corrected before
the passing full run. Final required checks,
source/process stability, exact PR/main CI, controller integration and independent
public-delivery evidence are recorded on the owning issue. Green software checks
do not establish badminton annotation accuracy.

No scientific image assessment, new inference/training, source acquisition,
held-out scoring, model/default promotion or deployment occurs. The complete-rally
scientific result remains **0/2**, all four eligibility flags remain false, and
#62/#66/#67/#71 remain incomplete. Correct full-match automatic annotation is
still unproven.
