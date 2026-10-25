# Optional audio contact source correspondence

Task [#284](https://github.com/Ken0u/badminton-match-analyzer/issues/284)
investigates the optional audio consumer on baseline
`ee9d6ca4dadf8da7b85c96cee085ebf06f67fdd9`. The frozen specification is
`1a72d9b4e567409ba6d8828a53bc86bac70c8b60de623ee6e5863a9bca5352d4`.

The consumer previously selected player poses by time without checking that
their source frame IDs and times corresponded to the shuttle context. Generated
inputs reproduced unsupported additions and corroboration. This repair checks
pairwise correspondence before optional audio evidence is used. It does not
establish native media alignment, AV synchronization or annotation accuracy.

## Frozen generated comparison

The retained local probe SHA-256 is
`af532f6d8ebc46d36046ebd15efa6ba664afab6b1fb3c6a91e1e85516fffd206`.
It constructs 30 source rows at 40 ms intervals, a missing shuttle observation
at frame 12, a moving confident wrist for track 7 and an onset at 0.49 s.
The actual disposable Store/API jobs use 25 generated rows, a fake source and
the real visual proposal/background job code; only acoustic extraction is
stubbed. No original scientific media, labels, predictions or models are used.
All 14 direct cases and 11 API cases remain in the comparison.

| Case | Baseline added proposals | Repaired added proposals | Actual API comparison |
| --- | --- | --- | --- |
| Aligned rows | 1 | 1 | 1 to 1 |
| Pose frame IDs shifted by 100, unchanged times | 1 | 0 | 1 to 0 |
| Pose times shifted by 5 ms, unchanged IDs | 1 | 0 | 1 to 0 |
| Identical duplicate pose row | 1 | 0 | 1 to 0 |
| Duplicate frame with conflicting time | 1 | 0 | 1 to 0 |
| Distinct pose frames sharing a timestamp | 1 | 0 | 1 to 0 |
| Missing pose frame IDs | 1 | 0 | Direct probe only |
| Missing pose times | `KeyError` | 0 | Direct probe only |
| Every second pose row, three usable wrist samples | 1 | 1 | 1 to 1 |
| Omitted center pose row | 1 | 1 | 1 to 1 |
| Every fourth pose row, insufficient support | 0 | 0 | 0 to 0 |
| Variable times with a 7.5 s origin | 1 | 1 | Direct probe only |
| Explicit player replay | 0 | 0 | 0 to 0 |
| Shuttle source-frame gap | 0 | 0 | 0 to 0 |

For each malformed case that previously supplied optional evidence, the direct
comparison also verifies suppression of corroboration without changing the
original visual result. All 11 API runs complete before and after the repair;
source-run bytes and annotation content remain unchanged. These are generated
integration results, not real acoustic decoding or live YouTube measurements.

## Behavior and limits

A relevant pose row must have an integer, nonnegative source frame ID and a
finite numeric source time matching the shuttle row within 1 ns of arithmetic
roundoff. Relative tolerance is zero. This tolerance does not compensate for
clock offsets. Relevance uses either frame ID or time within the validated
nine-row shuttle context and the existing +/-120 ms wrist interval, so moving
a conflicting timestamp outside the window cannot conceal the row. Duplicate
relevant frame IDs are ambiguous even when
their values agree. Unknown or nonfinite pose clocks conservatively disable
support because their location outside the context cannot be established.

Missing pose samples remain missing; no dense sampling or nominal FPS is
required. Existing wrist confidence, movement and minimum sample requirements
still apply. The consumer does not retime, interpolate or rewrite inputs. If
no optional evidence is accepted, the entire copied visual result, including
order and nested evidence, is preserved. Valid corroboration still changes only
the existing audio-support evidence; conflicting hitter hints and repeated
sounds retain their existing behavior.

The [original audio report](AUDIO_CONTACT_REPORT.md) remains applicable. Audio
is default-off and uncertain; intervals retain inclusive source-frame bounds.
Existing cut, replay, selection-context and raw-shuttle guards remain in force.
Core visual proposals, acoustic extraction, API/schema, thresholds and models
are unchanged. Missing pose time may still fail earlier in core visual processing
through the API; the guarded consumer is not a global artifact validator.

Matching two perception documents cannot certify that either agrees with native
media or acoustic timing. This task supplies no scientific accuracy denominator,
new independently adjudicated reference, or model promotion. Complete scientific
references remain 0/2 and all four research eligibility flags remain false.
Full automatic annotations throughout unseen singles and doubles remain unproven.

## Verification

The new regression suite first produced 19 failures and 35 passes on baseline,
then all 54 direct/API audio tests passed after the initial consumer repair.
That revision passed 577 broader audio/contact/scene/clock tests and a full
Python 3.10 suite: 4,284 passed, four optional skips, 441.00 seconds. Source hashes
were unchanged and both monitored wrapper/worker lifetimes were independently
absent, with no observation errors.

An additional generated 60 fps control exposed valid sparse corroboration lost
by the initial guard: wrist samples within the existing +/-120 ms interval fell
outside the nine-row gap window. Baseline corroboration was one; the initial
guard produced zero. This result is retained. The corrected guard validates the
source context of the entire wrist interval too, preserving the original
proposal bounds. The same control again receives one corroboration. Expanded
context with mismatched frame IDs, a cut, player replay or excluded shuttle
selection context receives none. This does not create a new high-frame-rate
interval where the original gap window cannot bracket the uncertainty bounds.

All 59 final direct/API audio tests pass. The suite includes
malformed/unknown clocks and IDs, preserved visual order, sparse/partial poses,
VFR/nonzero origins and arithmetic roundoff. The generated API regressions use
actual Store jobs and verify original source and perception bytes, plus both
stored annotation revision documents and saved timestamps, including a generated
nonempty corrected event at revision one.

The final Python 3.10 suite passed 4,289 tests with four optional skips in
436.81 seconds. Before/after source hashes match; both monitored wrapper/worker
lifetimes were independently absent and observation errors were empty. Ruff,
formatting, dependency consistency, repository validation, UTF-8/LF, tracked
JSON, report local links and diff checks pass. Exact PR/main checks, controller
integration and complete candidate delivery remain pending at this revision;
the owning issue records exact revisions and subsequent receipts.
