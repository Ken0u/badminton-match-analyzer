# Scene runner fatal-lane and terminal-observation repair

Software-only follow-up [#353](https://github.com/Ken0u/badminton-match-analyzer/issues/353),
October 30, 2026. Frozen specification:
`95ab2fe7d560230a7a04d40a4aded21b3759b7d4c33af515beccc45cb4897554`.

The runner now fences subsequent original-session launches after an unexpected
lane exception, observes already launched work through its existing collector,
and propagates the first fatal exception after both lane futures settle. Its
final fence check, invocation record and process creation share the same lock
as fatal-lane fencing. A reservation made before fencing stays charged and
retains its failed result; it is never replaced. A partial run cannot seal
original streams or enter adjudication.

After parent exit and output EOF, the collector can repeat absence checks of
the same frozen recorded process lifetimes. Reobservation uses the existing
three-second cleanup allowance, bounded by the original runtime deadline and
any already established cleanup deadline. It cannot reset that allowance.
Observation history retains transient failures. Persistent live, inaccessible
or otherwise unproved lifetimes still produce terminal errors and fence future
dispatch. Reobservation sends no signals, accepts no substitute lifetime and
does not restart an assessor. Existing PID, creation-time, directory, command,
signal, pipe, output and scientific validation requirements remain in force.

## Original failure and preserved scientific result

The [#349 continuation](SHUTTLE_SCENE_CONTINUATION_REPORT.md) is incomplete.
Operator archival of closed generated-test fixtures raced the active runner's
retained-output directory scan. A pending `lstat` encountered a removed fixture
and raised `FileNotFoundError`. Byte verification before archival did not make
concurrent pruning safe. The original executor waited for futures without
propagating a stop fence, allowing the other lane to launch later sessions.
The remaining lane was stopped by withdrawing its ownership observer and
allowing the existing freshness guard to fail closed. No scientific retry or
replacement was made. Preserve the original failure and all private evidence;
this software repair does not make pruning active evidence safe.

The separate generated subprocess check intermittently reported
`terminal_ValueError` after clean parent exit and EOF. Its original failed and
unchanged-source passing receipts are preserved. A deterministic injected
transient unproved observation reproduces the one-check mechanism; it does not
prove the operating-system cause of the intermittent failure was identical.

The original seven attempts charged 30,446,222 image bytes: six accepted
readings and one failure, with 143 original slots unattempted and no
adjudication. All 13,499 frame occurrences remain in the denominator:
324 independent-agent agreements, 40 unknown, one conflict and 13,134
unavailable. Eligibility remains false and complete independent rally
references remain 0/2. Original media, all 870 sheets, consumers and opaque
application-truth hashes were reverified unchanged at the #349 terminal seal;
that source evidence is preserved, not reopened by this task.

## Generated verification and limits

Generated baseline controls exercise the actual original dispatcher and
collector without scientific images, CLI sessions or a Store. One lane fails
while the other is active; the baseline launches two later fake batches. A
real short generated subprocess independently verified absent is subjected to
one injected transient proof failure; the baseline checks it only once and
rejects it. The original executable source hash is
`68281e563152251a7101f94d08a94ea294d18945541dcbfe6d8e6a58a639348c`.

Regression coverage includes either lane failing first, errors before
reservation and after retained failed-attempt evidence, preservation of an
already active lane's result, refusal after configuration but before process
creation, transient and persistent terminal observations, a real live recorded
descendant after EOF, and a deterministic fixed cleanup deadline. Existing
inherited-pipe, changed-identity, signal refusal, access-denial, output-cap and
elapsed-bound controls remain intact. All 158 focused checks pass. Required
full-suite, lint, formatting, dependency, repository and whitespace results,
exact revisions and delivery receipts are checkpointed on the owning issue.

Private baseline receipts are under `.cache/scene353-before-v1/`. The first
new-regression invocation failed before running tests because its temporary
parent directory was missing; that log is retained. After creating a fresh
parent directory, all 11 initial new regressions failed against the unchanged
baseline. The final terminal controls also account for Windows virtualenv
launcher descendants by checking membership in the frozen lifetime set.
These local artifacts and test subprocesses are not supplied by a clone.

Only the runner, generated tests and this report change. Its CLI remains bound
to the expired #349 scientific scope and protocol. The #353 grant permits zero
scientific sessions, zero image payload and no source reading, inference,
training, model installation or application-truth edits. A future assessment
needs its own authorization and fresh matching grant; neither old clock is
reclaimed. These repairs establish software failure behavior, not labels,
model improvement or full-match annotation accuracy.
