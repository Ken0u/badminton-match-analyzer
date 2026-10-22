# Windows browser fixture process ownership

Issue [#181](https://github.com/Ken0u/badminton-match-analyzer/issues/181),
verified on MSI on October 22, 2026 (UTC), against baseline
`766806c54c8d1e71c40ddc007c92478c0aa31a1d`.

The generated browser fixture now authenticates the actual server process when
a Windows virtual-environment Python executable launches a child interpreter.
The previous harness required the receipt PID to equal the spawned PID and
could terminate only the wrapper. A stopped wrapper did not establish that the
server had stopped.

## Ownership and cleanup

The harness records the original executable PID, creation time, working directory,
executable and exact command. It accepts either that interpreter or verified
expected-launcher descendants, checking each parent link, creation order,
interpreter and full launcher arguments, including the generated root and nonce.
The authenticated listener receipt must match an independently inspected owned
lifetime, command, working directory, root and nonce. Receipt URLs must use HTTP
on an explicit loopback port. POSIX virtual-environment executable symlinks retain
the exact spawned command while allowing the known base executable.

Cleanup discovers expected descendants even after a partial startup, stops them
before the wrapper, and independently establishes each original lifetime terminal.
Every signal rechecks PID, creation time, working directory, command and executable
inside the psutil signal helper. Unexpected processes and changed lifetimes fail
closed. There is no recursive process-tree termination. Cleanup is idempotent,
serializes concurrent callers, and retains attempts and errors; a failed evidence
write can be retried. A timeout or missing wrapper never proves listener exit.

## Verification

The existing environment was reused: Python 3.10.5 at the original project
`.venv/Scripts/python.exe`, Node 24.22.0, FFmpeg 8.1 and cached Playwright Chromium
156.0.8078.4. No installation, download or base-interpreter launch workaround was
used. Credentials were removed from test environments. The browser launcher pins
the task repository and generated data root before app imports.

| Check | Result |
| --- | --- |
| Injected ownership and cleanup cases | 27 passed |
| Opt-in actual generated startup/failed-startup test | Passed; 28 total process tests |
| Final production browser matrix | All 18 groups passed |
| Complete Python regression | 2,024 passed, four optional skips |
| Ruff check and format | Passed; 182 Python files formatted |
| Environment dependency and Git whitespace checks | Passed |

The injected cases cover direct and redirector interpreters, POSIX executable
symlinks, unrelated descendants, changed commands/directories/executables, bad
receipt PID/creation time/root/nonce, PID reuse, early exit, partial startup,
cleanup timeout, concurrent/idempotent cleanup and evidence-write failure.
The opt-in test uses the real generated app twice: normal startup and an
intentionally mismatched authenticated response. Both verify complete cleanup.

Across the eight retained local fixture attempts, all 16 original wrapper/listener
lifetimes were independently rechecked terminal. This includes both browser runs
and three deliberate startup failures. Original process receipts, generated
launchers, logs, source manifests, screenshots and cleanup attempts are retained
under this task worktree's ignored `.cache/evidence/`. They are local artifacts,
not files supplied by a clone.

The final browser run preserves source PTS/orientation, early Play before metadata,
unsupported-media recovery, selection/error handling and annotation invariants.
Its measured seek/timeline/playback-start/RAF p95 values were 70.6/50.7/90.3/18.2 ms,
within the unchanged frozen ceilings. These measurements do not establish a
relative performance improvement.

To reproduce process checks with the existing tools and a generated-only data
environment, run `node --test tests/frontend-fixture-process.test.mjs`. Set
`FRONTEND_FIXTURE_LIVE=1` and `FRONTEND_PYTHON` to the project venv interpreter to
include actual app startup and cleanup. Reuse the existing FFmpeg and
`PLAYWRIGHT_BROWSERS_PATH`, clear authentication/API credential variables, and run
`node tests/frontend-delivery.mjs` for the production browser matrix.

## Retained failures and limits

The first Python regression invocation imported the original checkout through its
editable install, causing 15 collection errors. Its logs remain preserved. Pinning
the task backend import path for Python tests produced the passing full suite.
The browser runs used the original venv executable directly, with no `PYTHONPATH`
override.

The first browser run passed 13 groups, then its generated analysis job failed with
Windows `PermissionError` / `WinError 5` while replacing `manifest.tmp` with
`manifest.json`. Both fixture lifetimes were nevertheless cleaned up and verified.
The final serial browser run passed all 18 groups. At that checkpoint the earlier
failure remained unresolved and was preserved in
[#186](https://github.com/Ken0u/badminton-match-analyzer/issues/186). Its later
writer repair and Windows test correction were delivered separately through
[#190](https://github.com/Ken0u/badminton-match-analyzer/issues/190). No production
writer or error handling was changed for this harness repair.

Before submission, cumulative local output was below 10 MiB plus a 16 MiB reserve,
within the 256 MiB / two-hour task limits. Exact-head CI, controller integration,
merged-main checks and public delivery are recorded on the owning issue and PR.

These generated process and software checks do not improve or certify badminton
annotation accuracy. Actual media, annotations, datasets, weights, predictions,
research processes and deprecated `PROGRESS.md` remain untouched.

## Subsequent shutdown-observation repair (#192)

Issue [#192](https://github.com/Ken0u/badminton-match-analyzer/issues/192)
investigates two later hosted Linux cleanup failures against baseline
`4246ec524fbece6361898e562698f30410de5a66`. Main CI
[39719248778, attempt 1](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39719248778)
and documentation PR CI
[39722230314](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39722230314)
passed their browser assertions before reporting a process identity mismatch.
Each original receipt records one SIGTERM without the new structured signal
outcomes. Their original process terminal states remain unknown. The
original logs, artifacts and failed checks are preserved; this task does not
retry either historical run. A separately authorized retry of the former run
already passed and remains separate evidence.

Before tracked edits, the task froze a generated-record shutdown diagnostic and
the three granted source files. Freeze SHA256 is
`7c5c810bfbacf53256a32a2d3c9692104157e0b3c347c888074c6f7df37def63`;
the preserved baseline result SHA256 is
`97435ebe08d6698d578e469bc866fd20e02e71fe1a64d514256d54a636ddf318`.
The baseline fails when a simulated process retains its PID/creation time but
loses mutable command/executable metadata before reaping. Yielding would allow
its disappearance, but the original synchronous check fails first. This
generated example establishes an observation gap, not either historical cause.
The prospective record is linked from the
[owning issue checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/192#issuecomment-6352236982).

The repair separates permission to observe shutdown from permission to signal.
Initial ownership, descendant discovery and every actual signal still require
the complete expected identity. Structured snapshots retain process status,
available fields, per-field errors and observation timestamps. A teardown
observation may continue only for the original PID/creation time and compatible
remaining metadata; it never authorizes another signal. Changed nonempty
metadata, inaccessible fields and changed lifetimes remain failures. A zombie
status alone does not establish exit: cleanup must independently observe the
original lifetime absent. Successful signals yield to Node before bounded
shutdown polling, allowing child exit/reaping callbacks to run.

Signal receipts record only confirmed signals. A process already absent at the
signal boundary does not invent a signal, and denied/changed identities retain
the failed observation. `ZombieProcess` is handled before its `NoSuchProcess`
parent exception. Since psutil can also raise `NoSuchProcess` for PID reuse,
that signal exception requires a fresh PID inspection before reporting absence.
A generated Python module double exercises these actual exception handlers
without signalling any OS process. Each lifetime retains at most 256 initial
observations plus the latest observation and an explicit omitted count; clipped
fields are marked. Receipt bounds do not change the full identity used to authorize a
signal. Existing deadlines, signal escalation limits and ownership checks are
unchanged. No recursive termination is introduced.

The final local process suite passes 47 tests, including normal and intentionally
failed generated app startup; its POSIX-only child/reaping case is explicitly
skipped on Windows. That standalone case is available on POSIX, but current CI
does not invoke this test module. Hosted browser CI exercises the actual Linux
app lifecycle through the same repaired harness. Native macOS/Windows CI retains
its existing generated-media and frontend checks.

The full local Python suite passes 2,048 tests with four optional skips. Ruff
check/format (183 files), dependency consistency, Prettier, granted-file UTF-8/LF
and local links, and Git whitespace checks pass. The one Python warning is the
environment's Starlette/httpx deprecation; no dependency is installed or changed.

The final-source Windows production matrix passes all 18 groups. Its
seek/timeline/playback-start/RAF p95 values are 65.2/31.7/73.0/16.8 ms, within the
unchanged ceilings; no comparative performance gain is established. All eight
retained local app fixture attempts have complete cleanup receipts. Independent
read-only checks find all 16 original wrapper/listener lifetimes absent or their
PIDs occupied by a different creation time; no replacement receives a signal.

An earlier matrix also passed all 18 groups before the final signal-exception
correction; it is preserved separately rather than used as final-source proof.
The first local live suite passed, then its wrapper failed while printing Unicode
under a Windows legacy console encoding. The original result/logs remain intact;
new helper lineages use UTF-8 output. Validation and delivery for this subsequent
repair are recorded on #192. These generated-only software checks do not certify
badminton annotation accuracy.
