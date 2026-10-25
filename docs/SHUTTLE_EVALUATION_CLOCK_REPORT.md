# Shuttle evaluation native clock validation

Issue [#307](https://github.com/Ken0u/badminton-match-analyzer/issues/307)
extends the existing contact/recognition clock guard to saved shuttle evaluation.
This is an artifact integrity repair; complete scientific references remain 0/2
and full automatic badminton annotation accuracy remains unproven.

## Reproduced failure

On merged source `6c84f5cb47e310e8fe19d62d8ead67e9ba395a46`, generated registered
shuttle runs claiming frame 15 with frame 5's timestamp received localization
F1 = 1 through both API and CLI. Deleting the native timestamp map also allowed
successful shuttle-only scoring. Twelve generated cases cover matching controls,
conflicting row times and missing maps in singles/doubles with constant/variable
clocks. Source, annotation and artifact JSON bytes remain unchanged.

Sixteen regression cases then failed against the unchanged granted baseline:
labelled and unlabelled rows with wrong times were accepted through both API
and CLI, across both modes and clocks. Original logs and receipts remain local;
the owning issue carries aggregate checkpoints. No scientific source images,
manual research labels, models or inference were accessed.

## Repaired behavior

The pure shuttle evaluator accepts an optional keyword-only native timestamp
sequence. Supplied clocks must cover every source frame, with finite nonnegative
numeric values, excluding booleans, in strictly increasing order. The shared
validator retains the existing contact/recognition clock contract.

Every original output row is checked before filtering to manually labelled
frames. Its strict integer frame must lie inside the declared run, and its
finite numeric `time_s` must match that native frame within the existing
20-microsecond tolerance. Missing identity, conflicting times and malformed rows
fail explicitly, including on unlabelled frames. Artifact times are never
rewritten or inferred from FPS. Missing output rows remain missing predictions;
the repair does not require exhaustive inference output.

API and CLI load the actual timestamp map for shuttle-only and combined
evaluation. Invalid/missing clocks and conflicting row metadata return an
actionable HTTP 422 or CLI exit 2. A failure does not publish a partial combined
report or overwrite an existing CLI report. Valid irregular clocks, nonzero
source origins and native timestamp gaps retain original localization,
visibility, displacement, negative-label and missing-output accounting.

Reports expose `prediction_clock_status: validated` when checked. Existing pure
calls without a clock remain supported with explicit `unavailable` status;
their existing metrics remain unchanged. Source-hash and duplicate-frame guards
remain in force. No saved annotation, prediction, source metadata, model/default,
schema, workflow or dependency changes accompany this repair.

## Verification and limits

Generated pure/API/CLI tests cover both match modes and constant/variable clocks,
all-row validation before exclusions, strict native identity and numeric types,
fixed tolerance, missing predictions, no labels, legacy calls, combined reports,
and byte-preserved inputs and existing reports. The initial focused run exposed
one new test's invalid expectation: its supposed wrong time equalled the
unlabelled frame's actual time. That fixture was corrected without changing
the validator or tolerance. The next focused run passed all 762 checks.

All 4,773 full Python tests pass, with four optional skips, alongside required
Ruff lint/format, dependency, repository and diff checks. Source bytes stayed
fixed throughout verification; all observed verification lifetimes are terminal.
Two new regex literals initially failed lint and were marked raw before this
successful full run. Exact PR/main/public delivery is recorded on the owning
issue after it finishes. The initial 16 baseline failures and corrected
new-test expectation remain preserved. Software clock validation cannot establish
independent source truth, complete rally references, shuttle accuracy, persistent
identity or full-match event recognition. No new scientific assessment, training,
model promotion or consumed-holdout access occurs here.
