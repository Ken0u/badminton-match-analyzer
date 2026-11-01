# Retained-output scan accounting

Owning software task: [#361](https://github.com/Ken0u/badminton-match-analyzer/issues/361).
The [original scene assessment](SHUTTLE_SCENE_FRESH_ASSESSMENT_REPORT.md) remains
incomplete. This change launches no scientific sessions or image transfers.

## Trigger and change

Every durable assessor output checks the retained-output allowance. The old
traversal queried the same entry repeatedly through `lstat`, `is_symlink` and
`is_dir`, plus repeated checks at each retained root. An earlier metadata-only
operational profile measured 117,766 queries and 15.258 seconds for one scan on
this workstation; its 164,159,370-byte total describes that earlier snapshot.
It is motivation, not a scientific result or current production measurement.

The scanner now classifies each entry from one fresh non-following `lstat`
result. It uses the mode for symbolic links/directories and the Windows reparse
attribute for junctions and other reparse points. Root links still fail;
interior links charge their own metadata without traversing targets. Files
remain charged per occurrence, including hard links. Ordinary directory metadata
is not charged. Every call enumerates both task-prefix cache roots and matching
worktrees again; growing files and new roots enter the next total.

Missing or unreadable entries and enumeration errors propagate, preventing a
partial total from authorizing a write. No cached sizes, skipped failures,
deleted fixtures, changed prefixes, output ceilings, write headroom or durable
write semantics are introduced. Traversal is not an atomic filesystem snapshot;
this change does not claim protection from arbitrary concurrent tree replacement.

## Generated verification

A generated tree with 1,201 files and 63 directories has an independently
computed total of **24,009 bytes**. Five scans of each source reproduce it:

| Source | Metadata calls per scan | Median elapsed seconds |
| --- | ---: | ---: |
| Baseline `0528ec6` | 3,800 | 0.173 |
| Candidate | 1,264 | 0.067 |

This is a 66.7% reduction in metadata calls on that generated tree. Timing is
machine-specific, includes measurement overhead and is not a production speed
guarantee. A separate 22-entry regression fails on the baseline's 68 queries
and requires exactly 22 fresh, non-following metadata queries after the change;
it does not assert wall-clock timing.

Generated controls independently verify totals across roots/worktrees, file
growth, newly added roots, hard-link occurrences, symbolic-link/reparse markers,
root-link rejection, interior target exclusion, disappearance, metadata denial
and directory enumeration denial. Two existing link controls now inject the
link marker at `lstat` metadata instead of intercepting `is_symlink`; their
original root-rejection and interior-no-traversal assertions remain. The first
metadata-call probe patched `os.stat`, which Python 3.10's pathlib accessor had
already captured, and counted zero calls. It was corrected to observe
`Path.stat`; the real baseline then records 68 queries. An adapted fixture's
temporary variable shadowing error is preserved separately from final results.

All 193 focused runner tests pass, including unchanged quota/collector,
ownership, budget, source identity, blind-stream, unknown and denominator
controls. Required full Python/frontend/browser/repository checks, terminal
process receipts, exact PR/main verification and public candidate delivery are
recorded on the owning issue. Private generated trees and failure receipts remain
under ignored `.cache/budget361-*` paths.

## Scientific boundary

The CLI remains bound to expired scientific task #359 and its unchanged
protocol, source hashes and eligibility. This code-only task cannot make any
assessment session eligible. Original videos, galleries, readings, frozen
consumers, Store records, deadlines and failed-attempt evidence are preserved.
No real application Store, private semantic labels, inference, training or
promotion is used. Any future image assessment needs its own authorized scope,
committed grant, prospective freeze and runtime. Independent complete-rally
references remain **0/2**; model improvement and full-match correctness remain
unestablished.

## Merged-main test repair

[PR #366](https://github.com/Ken0u/badminton-match-analyzer/pull/366) passed all
12 exact-head verification jobs. Its merged source `f0a86da` failed the Python
3.10 job in [main run 41286355281](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/41286355281):
an existing terminal-observation control expected at least two observations
within a 0.2-second allowance but recorded one. Python 3.12 and both native jobs
passed. Main failure paused normal work; no retry or successful candidate
delivery is inferred. [Repair #367](https://github.com/Ken0u/badminton-match-analyzer/issues/367)
uses a fresh controller grant and retains the failed run and source separately.

A generated before-control proves actual process absence, injects a 0.25-second
delay in the first observation and reproduces the assertion failure. The
unchanged collector correctly preserves the unresolved terminal result and
fences further dispatch when its original allowance expires. This demonstrates
a scheduling-sensitive fixture; it does not establish the exact cause of delay
on the failed GitHub runner. Initial diagnostic scaffolding incorrectly counted
all Windows launcher/console lifetimes as one parent proof; the corrected control
counts the original parent separately and preserves every observed lifetime.

The repaired test supplies an isolated monotonic clock to its imported runner.
Collection still runs a real short subprocess and sleeps normally, including
terminal polling; terminal sleeps also advance the fixture clock deterministically.
OS probe duration no longer decides whether the simulated transient condition
fits into this particular clock control. The shared time module is not patched.
Every existing assertion remains: at least two observations of the original
process, membership in the frozen lifetime list, complete output/EOF, zero exit,
no bounded stop, transient success, persistent failure/fence and the original
real elapsed bound. Added zero-delay/0.25-second-delay cases cover all three error
types and both outcomes. A new assertion bounds the sum of terminal sleeps to
0.2 seconds, with only a 1e-12 numerical tolerance for floating-point addition;
its initial strict comparison failed at 0.20000000000000007 and is preserved.
Other real wall-clock, live-descendant, identity, signal and deadline controls
remain unchanged. Production runner bytes, protocol and all budgets are identical
to `f0a86da`; this repair changes only the fixture and this report.

An initial fixture used virtual-only terminal sleeps. A zero-delay Windows case
then exhausted its simulated allowance before a console lifetime settled. Keeping
terminal sleeps real preserves OS scheduling opportunities while the separate
fixture clock excludes probe delay. That failed attempt is retained as evidence.

Required final checks, exact repair PR/main source evidence and both the repair
and parent delivery outcomes belong on #367/#361. No historical CI retry,
scientific dispatch, image transfer, training or model promotion is authorized
by this repair. The earlier scientific limitations above still apply.

## Follow-up fixture phase isolation

[PR #368](https://github.com/Ken0u/badminton-match-analyzer/pull/368) passed all
12 PR jobs, but merged source `9397806` failed three Python 3.12 collector tests
in [main run 41289435469](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/41289435469).
The owner's single bounded failed-job retry passed, followed by verified public
delivery and controller recovery of #367/#361. Original failures remain evidence;
the retry did not establish that their timing dependencies were repaired.
[Incident #369](https://github.com/Ken0u/badminton-match-analyzer/issues/369) and
[follow-up #370](https://github.com/Ken0u/badminton-match-analyzer/issues/370)
track the diagnosis and fixture change separately.

Generated controls reproduce two possible failure paths, without establishing
the historical CI host's exact delays. Delaying only start-receipt setup by
1.1 seconds yields complete 262,144-byte input, correct output and exit zero,
but an unintended bounded stop under the original one-second fixture allowance.
Deferring stdout EOF for five real polling sleeps consumes 0.25 seconds of the
old fixture clock: all 12 delayed-EOF combinations fail its positive-terminal-
sleep assertion. The zero-EOF-delay combinations pass in that reproduction.
Earlier synthetic metadata controls expose the same clock interaction without
claiming actual process absence.

The positive file-input fixture now gives only its imported runner a clock that
starts after generated start-receipt setup and then follows real elapsed time.
Both zero-delay and 1.1-second setup-delay controls retain complete output,
hash/size, EOF, exit, absence and no-unintended-stop assertions. The helper's
original four-second real collection cap remains. This fixture does not test
production setup-deadline enforcement; the real deadline and failure controls
remain separate and unchanged.

The terminal fixture's private clock now charges only terminal polling sleeps.
Collection and controlled EOF delays still sleep in real time but cannot consume
the simulated terminal allowance. Zero/five deferred EOF polls cross zero/0.25-
second first-probe delays, transient/persistent outcomes and all three original
exception types. All 24 combinations retain the original two-second real cap,
fixed lifetimes, repeated observations, output/EOF, fence and failure assertions.
Every injected absence error follows an independent actual OS absence check;
the positive file-input control also checks all recorded lifetimes independently.
Assertion diagnostics include the complete receipt, phase clock and injected
delays. The unchanged synthetic fixed-cleanup control still consumes the original
three-second production allowance, with no deadline reset or extra grace.

Real live-descendant, inherited-pipe, unread-input, output-overflow, collection-I/O,
identity-mismatch and signal-refusal controls keep their real clocks. Production
runner bytes remain SHA256
`cb41c0695f8e67b092dab0904e254641b59f42241a31c1dbb15b96313d27924e`;
no workflow, scientific protocol, budget, source, Store, prediction or model
changes. Required final checks and exact PR/main/public delivery evidence belong
on #370; #369 remains open until delivered verification. No scientific session,
image transfer, inference or training occurs, and the scientific limitations
above remain unchanged.
