# Pose-continuation failure reporting

Issue [#409](https://github.com/Ken0u/badminton-match-analyzer/issues/409) repairs
failure reporting after the consumed, incomplete
[#405 operation](https://github.com/Ken0u/badminton-match-analyzer/issues/405).
The original scientific source remains
`728ada95e8b568827603d9621b5b7520a641246d`, with its original inputs, outputs,
prospective commitment, execution claim and clocks preserved.

## Observed failure

The live RAM safety reserve stopped #405 before another clip started, after
12 complete clips / 4,079 native frames / 7,107 new decode visits / 4,079 pose
observations and 134 feature rows, including 21 unavailable rows. There were
zero classifier fits or validation comparisons. The ordinary failure writer
then refused its JSON serialization RAM reserve, replacing the original
exception and leaving `failure.json` absent. The preallocated `terminal.json`
and complete stderr survived. The underlying system RAM fluctuation remains
unexplained; unrelated applications and processes were preserved.

The controller accepted the explicitly authorized terminal release; #405 is
closed as incomplete. This neither completes its scientific comparison nor
permits replay. There are still 386 unprocessed clips; a future scientific
operation needs its own specification, grant and complete accounting.

## Repaired contract

The runner rethrows the same primary exception, retaining its cause and
traceback. Accounting is collected separately from journal close and diagnostic
publication, so a secondary close or write failure cannot replace that error.
Partial-stage lower/upper counts and a started fit's consumed allowance retain
their original meaning. Unavailable accounting stays unavailable with an
explicit reporting diagnostic; it never becomes zero.

The existing fixed-size terminal reservation records failure and accounting
before optional ordinary failure publication. Secondary reporting stages and
exception types are recorded in that reserved slot when possible, with bounded
stderr diagnostics as a fallback. An inaccessible or changed slot is not
replaced or enlarged. Ordinary failure JSON still passes through the unchanged
RAM/disk admission; it receives no publication retry or unreserved allocation.
Catastrophic diagnostic failure also leaves the original exception authoritative.

Messages use at most 1,024 characters from a single plain string exception
argument, with explicit truncation. Other argument forms receive a fixed
omission message, avoiding arbitrary exception formatting in this reporter.
Secondary diagnostics contain bounded stage/type identifiers rather than
unbounded exception text. The terminal writer retains its exact byte limit,
including JSON escaping, and original flush/fsync behavior. Scoped artifact
writers restore on exit. Used outputs remain immutable and refused for reuse;
absence of a failure JSON never means success.

## Verification

Ten generated public-run controls on the delivered source produced **eight
expected failures and two passes**: each secondary RAM, disk, I/O or serialization
failure masked the original exception, both before fitting and during a fake-fit
callback. The repaired source passes all ten, retaining exception identity,
explicit cause, real disposable Store failure, exact zero/one consumed-fit
accounting, no completion, scoped-writer restoration and refusal to reuse output.

The focused continuation suite passes **144 tests**, including additional partial
decode/observation accounting, journal-close failure, oversized escaped messages,
unwritable or changed terminal slots, custom diagnostic formatting, and existing
generated public CLI freeze/run/verification success controls. These fixtures use
generated metadata/pixels and fake callbacks; no original video, scientific
weights, private labels or held-out predictions were opened for this repair.

Required full-suite, tooling, clean-package and exact controller CI/delivery
results are recorded on the owning issue and PR after verification. The
scientific protocol, cohorts, algorithms, limits, deadlines, application truth
and model defaults are unchanged. No scientific restart, improved model or
full-match accuracy follows from these software checks. Complete accepted rally
references remain 0/2.

## Main-verification fixture repair in #411

All twelve PR verification jobs passed before the controller merged #410 at
`a66b83ec33036b5396a4448fe4095c70bb9f24ac`. Its
[original main run](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/42439172067)
failed two existing dispatch-recovery tests, pausing integration and opening
[#411](https://github.com/Ken0u/badminton-match-analyzer/issues/411).
Python 3.10 observed a zombie child while reading its working directory in the
directory-completion refusal case. macOS reported command/root identity mismatch
before the overflow test reached its intended log guard. The latter log does
not expose which field differed; its exact historical cause remains unknown.
Original logs and both failure XML artifacts are preserved. No historical CI
retry or scientific operation follows from this code repair.

The generated short-child tests now use an explicit readiness/release handshake.
The child enters its final Python command and writes its actual PID, then waits
for publication of its real process identity before executing the test body.
The production observer still reads PID, creation time, command and working
directory through native psutil and enforces its original command/root match.
The fixture independently checks those actual fields before releasing the child.
Both ordinary scheduling and a deliberate observation delay exercise missing/
directory completion and overflow refusal without accepting another exception
as success. Successful verification and nonzero child exit remain covered.

On Windows the virtual-environment executable may launch another interpreter
with a distinct PID. These standard-library-only generated children use the
underlying interpreter directly, binding readiness to the launched lifetime.
The test helper has bounded readiness/release waits and releases its own children
on assertion failure. It drains startup-failure pipes when production readers
were not established; it never signals a process or changes production limits.
The existing unobservable-identity test remains separate and unchanged.

All **66 dispatch-recovery tests pass** locally after the fixture repair. Full
regression/tooling results and fresh exact PR/main/public-delivery evidence are
recorded on the repair PR. Only the test module and this report change;
production supervision, identity/log/completion checks, scientific source,
protocols, dependencies, workflow, timeouts and retry policy remain unchanged.

The first full local repair check also exposed an independent fixture dependency
on host RAM: nine scaling-cache cases failed, eight with the initial RAM guard
and one before its expected second decode. Their generated frames and object
stubs are tiny; physical RAM pressure should not determine whether those
pixel/range/clock assertions run. These controls now use a scoped, deterministic
memory probe. Dedicated low-memory, half-free-memory cap and exact reserve/byte
boundary controls retain their explicit probes and assertions. Production
reserves and admission logic are unchanged; unrelated processes remain intact.
The original failed run and its XML are retained, and revised full-suite and
cross-platform results are recorded on the repair PR before submission.
