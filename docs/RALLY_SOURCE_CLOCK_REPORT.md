# Rally proposal native-clock validation

Issue [#350](https://github.com/Ken0u/badminton-match-analyzer/issues/350)
repairs an input-integrity gap in rally proposal generation and API admission.
It does not change the serve/ending heuristic, train a model or establish
automatic badminton annotation accuracy.

## Reproduced failure

On baseline `738f39c9c084bb36cbab37121cfd4d3523bb7cd6`, replacing native timestamp
25 with `NaN` leaves both generated singles/doubles candidates unchanged. The
actual API also returns 202, completes a generated-media job and publishes
`source_timestamps_validated: true`. The absolute timestamp-difference check
cannot reject `NaN` because its ordered comparison is false. It also does not
validate timestamps outside sparse perception observations. Boolean values can
masquerade as a numeric timestamp, and oversized integers can escape as an
overflow error rather than an actionable validation failure.

The preserved before receipt is `.cache/rally350-before-v1/reproduction.json`
on the owning workstation. The first generated regression run has 30 failing
and 29 passing cases against unchanged production source. These disposable
fixtures contain generated H264 media and synthetic observations; no real match
labels, predictions, weights or scientific assessment are involved.

## Resulting behavior

When a native timestamp table is supplied, validation now checks the complete
table before scene/camera filtering or proposal computation: a numeric sequence
covering exactly the positive integer source frame count, finite nonnegative
nonboolean timestamps and strictly increasing order. Invalid entries outside
the current observed window remain invalid. Each perception timestamp must
also be finite, nonnegative and nonboolean, with oversized values refused
without overflow. The existing native-frame correspondence check remains.

Validation raises `ValueError`, so the existing API handler returns 422 before
admitting a new rally job. The direct generator also refuses invalid inputs
before writing an artifact. Neither path repairs the clock or changes original
perception, saved annotations or prior proposals.

Valid constant-rate, variable-rate, nonzero-origin and discontinuous source
clocks retain their behavior. Source gaps, court/camera changes and scene
exclusions keep their existing guards. Sparse perception is still sparse.
Legacy research calls without a clock remain available and their generated
artifacts continue to record `source_timestamps_validated: false`.

## Verification

Generated checks cover malformed/full/out-of-window clocks, invalid perception
timestamps, refusal before job admission/artifact writes, stable annotations
and original run bytes, valid clock/input parity and explicit legacy behavior.
The initial focused run passes all 188 tests across rally proposals, API,
evidence propagation, selection context and automatic court integration.
The complete suite passes 5,660 tests with four optional skips, including
two additional source-count/correspondence controls. The first lint check
requests raw-string notation for five test regexes. That notation-only change
has an identical test AST; final focused and static checks rerun on those bytes,
with the original full-suite and lint evidence preserved.

Independent native evidence decodes a generated source completely and compares
the repaired and original deterministic proposal output for singles and doubles.
Its model hash binds the unchanged heuristic method/recipe, not neural weights;
no learned-model inference is performed. Complete final local checks, exact
PR/controller/main verification and independently verified public package/image
delivery are recorded on the owning issue. Ignored receipts are not supplied
by a clone. This software validation does not establish correct real-match
contacts, rally boundaries, persistent identities or shot recognition.
