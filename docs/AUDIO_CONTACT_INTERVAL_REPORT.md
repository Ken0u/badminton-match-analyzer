# Optional audio interval source-time bounds

Task [#287](https://github.com/Ken0u/badminton-match-analyzer/issues/287)
uses baseline `4426b2fea1835de0b1e9755f618ce26626cb1516` and frozen specification
`cdc10171cc42297d6b582d48d080d396eb59fedc94639d35a0e16d9a7b466129`.

The default-off audio consumer previously selected new review interval endpoints
only from its nine-row shuttle gap window. At high frame rates that window is
shorter than the existing +/-120 ms review range, so valid evidence produced no
new interval. This repair selects endpoints by actual source time and validates
the entire consumed context, preserving uncertainty and visual corroboration.

## Generated before/after evidence

The retained initial probe covers 25 direct cases and 25 actual disposable
Store/API jobs. All cases remain in the denominator. A follow-up revision adds
an actual 7.5 s offset to the variable source timestamps, rather than only setting
source-origin metadata. Both original results are retained. The final unchanged
probe SHA-256 is
`c7bf6add45c3e04ea15d42fffc9adb7109ae37c7f6521dfa5475259bd619e2c5`.
Only acoustic extraction is stubbed in the API; visual proposals, background
jobs and Store are real. The media file is generated fixture bytes, not an
original match, and no scientific inputs or models are accessed.

| Generated cases | Cases per path | Baseline new intervals | Repaired new intervals |
| --- | --- | --- | --- |
| 24, 25, 30 fps | 3 | One each | One each |
| 50, 60, 120 fps | 3 | Zero each | One each |
| Sparse aligned 60 fps poses | 1 | Zero | One |
| Variable times with 7.5 s source-time origin | 1 | Zero | One |
| Two sounds at one gap | 1 | Zero | One, without duplication |
| Available selection-history context | 1 | Zero | One |
| Unavailable beginning/ending endpoint | 2 | Zero each | Zero each |
| Cut in either run; replay in either run; unknown or excluded bound | 6 | Zero each | Zero each |
| Source-frame or timestamp gap | 2 | Zero each | Zero each |
| Missing audio, no shuttle gap, static wrist | 3 | Zero each | Zero each |
| Replay or missing selection history | 2 | Zero each | Zero each |

Every disposable API job completes. Original run bytes and both saved annotation
revision documents/timestamps remain unchanged, including a generated corrected
event at revision one. These are software/source-time behaviors, not measured
contact accuracy or acoustic/YouTube performance.

## Source context and review behavior

The closest available source row on or before onset minus 120 ms and on or after
onset plus 120 ms supplies inclusive bounds. Missing endpoints remain unsupported;
the consumer never invents FPS, pads frames, interpolates, retimes or shrinks the
review interval. Navigation still uses the actual nearest source row. At 120 fps
the generated onset is nearer frame 25 than frame 24; it remains frame 25.

The new interval validates every source row between the endpoints and original
gap window, recursively including declared shuttle selection history. Missing
history, malformed history bounds, source discontinuity, cuts, excluded selection
context and explicit non-live scenes reject the addition. Player source IDs and
times remain unambiguous under the [#284 guard](AUDIO_CONTACT_ALIGNMENT_REPORT.md)
across the complete context; endpoint or history conflicts cannot escape the
check by lying outside the old nine-row window. Sparse poses remain allowed.

Candidate context metadata spans every consumed frame, with an exclusive context
end beyond the inclusive endpoint. Actual API tests apply a later explicit
unknown scene at that endpoint and verify that the existing review endpoint
marks the candidate excluded without rewriting its original stored artifact.
Recursive history metadata is retained too. No API, schema or scene-review
implementation change is needed.

Existing visual corroboration uses its original rules and does not require
new-interval endpoints. A generated tail case still corroborates an existing
visual suggestion while refusing a new interval. Duplicate sounds and conflicting
hitter behavior, acoustic/gap/pose thresholds, default-off behavior and inclusive
uncertainty remain unchanged. Without eligible optional evidence, original
visual content is preserved.

Pairwise perception consistency does not establish native-media truth, AV offset,
sound source, contact time or calibrated confidence. No new scientific reference,
held-out prediction, training, inference, deployment or model promotion occurs.
Complete references remain 0/2 and all four eligibility flags remain false.
Full automatic annotation correctness throughout unseen matches is unproven.

## Verification and retained failures

The first baseline regression run produced 15 failures and 94 passes: 14 exposed
the missing new intervals; one incorrectly expected an existing tail suggestion
to lose valid corroboration. The first repaired run retained two failures: that
test expectation and a 120 fps navigation expectation assuming frame 24 rather
than the actual nearest frame 25. Both expectations were corrected to preserve
existing behavior. An expanded run then exposed another test fixture error:
the supposed distant visual suggestion at frame zero was close to an early
onset. The fixture now selects the farthest actual source frame. All original
logs and probe outputs remain retained; these expectation failures are not
presented as additional production defects.

All 120 final direct/API audio tests pass. The first Python 3.10 full suite
passed 4,350 tests with four optional skips in 450.62 seconds. After preserving
that run and merging disjoint current main
`8aa35420fdf89e2ec33cd7370e50d926f0bc681a`, final combined verification passed
4,407 tests with four optional skips in 454.28 seconds. Both runs retain matching
before/after executable/test hashes, independently observed absence of both
original wrapper/worker lifetimes and zero observation errors. Ruff, formatting,
dependency consistency, repository validation, UTF-8/LF, tracked JSON, report
local links and whitespace checks pass. Only the four granted files differ
from refreshed main.

Exact PR/main checks, controller integration and complete candidate publication
remain pending at this revision. The owning issue records exact source revisions,
process observations and delivery receipts.
