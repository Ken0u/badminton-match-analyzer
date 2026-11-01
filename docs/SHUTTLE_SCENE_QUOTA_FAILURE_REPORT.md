# Scene assessor quota dispatch repair

Owning software-only task: [#363](https://github.com/Ken0u/badminton-match-analyzer/issues/363).
The [preserved assessment](SHUTTLE_SCENE_FRESH_ASSESSMENT_REPORT.md) remains
incomplete. No scientific images, assessor sessions, account/provider changes,
paid credits, training or model promotion are authorized by this repair.

## Trigger and corrected behavior

After the CLI returned a structured usage-limit error, the runner recorded a
failed reading and dispatched the next original or adjudication batch. In the
expired attempt this produced 83 failed original sessions and 33 failed
adjudications. All 116 failures remain charged and immutable.

A generated before-control using the unchanged production `execute()` confirms
two quota failures produce two dispatches without setting the stop fence. Six
new regression cases fail against that source because no fatal error is raised.
An initial test invocation lacked its temporary parent directory and ran no
test bodies; its separate failed receipt is retained.

The repaired runner recognizes `You've hit your usage limit.` with either an
ASCII apostrophe or the Unicode right apostrophe observed in all 116 original
failed traces. Recognition applies only to structured CLI `error.message` or
`turn.failed.error.message` events. It records the charged failed attempt and terminal process receipt,
sets the common launch fence and propagates the first fatal cause. Both original
lanes and later adjudication dispatch respect that fence. An already launched
peer retains its result and is observed under the existing bounded cleanup and
process identity checks. There is no automatic wait, retry or replacement.

This classifier supplies a stop condition only. Assessor prose and unknown
event types cannot claim quota, and quota events cannot supply accepted labels.
The original strict tool/event validator, source/truth hashes, grant/deadline,
image/output bounds and process signal checks remain in effect. Ordinary
nonquota per-session errors retain explicit failed/missing evidence. A different
provider error or changed error wording is not classified by this narrow repair.

## Preservation and verification

The original checkout, v1/v2/v3 protocols, image packet and all private readings
remain unchanged. Offline reproduction uses the original frozen consumer and
completed original Store receipt; it never invokes an expired CLI command or
creates a missing scientific terminal record. All 13,499 occurrences remain,
including the original conflicts, unknowns and unavailable cells. The original
and partial-adjudication aggregates match exactly; no adjudication succeeded.

New generated tests cover both original lanes, adjudication, simultaneous quota
failures, preservation of an already launched successful peer, first-cause
propagation, charged reservations, nonquota failures and assessor-text/unknown
event rejection. Both apostrophe forms are checked in both event fields and all
three lanes. The final private-trace audit caught an ASCII-only first candidate
that passed its synthetic tests but missed the actual Unicode error prefix;
six new observed-form regressions fail on that candidate. The corrected audit
requires the production classifier to recognize every preserved failed trace.
A real generated Python subprocess exercises terminal nonzero
exit, pipe collection and process absence through the production collector.
No actual CLI or scientific source images are used by these tests.

The first focused repair run exposed a changed exception type in the existing
unobservable-process guard. The guard's original subsequent observation error
was restored, while quota failures retain their first cause. Initial failures
and corrected runs are kept separately. Required final software checks and exact
PR/controller/main/public delivery evidence belong on the owning issue.

Images, raw readings, detailed process/Store records and local audit receipts
remain ignored. Public delivery contains code, public protocol and aggregate
findings. Same-model scene agreement is not expert truth, shuttle accuracy,
exact contacts, persistent player identity, rally boundaries or shot labels.
All four research eligibility flags stay false; complete independent rally
references remain **0/2** and model improvement is not established.
