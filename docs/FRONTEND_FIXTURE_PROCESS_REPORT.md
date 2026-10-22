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
The final serial browser run passed all 18 groups. The earlier failure remains
unresolved and preserved in
[#186](https://github.com/Ken0u/badminton-match-analyzer/issues/186); its cause is
not established. No production writer or error handling was changed for this
harness repair.

Before submission, cumulative local output was below 10 MiB plus a 16 MiB reserve,
within the 256 MiB / two-hour task limits. Exact-head CI, controller integration,
merged-main checks and public delivery are recorded on the owning issue and PR.

These generated process and software checks do not improve or certify badminton
annotation accuracy. Actual media, annotations, datasets, weights, predictions,
research processes and deprecated `PROGRESS.md` remain untouched.
