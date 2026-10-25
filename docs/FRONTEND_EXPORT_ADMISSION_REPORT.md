# Generated export admission ownership

The export browser fixture now authenticates a direct interpreter or the expected
child of a Windows virtual-environment launcher. It registers cleanup immediately
after spawning, before any startup await. Process ownership and every fallback
signal still use the unchanged `fixtureOwnership` and `fixtureProcessProbe` from
`tests/frontend-fixtures.mjs`.

## Reproduced failure and repair

The unchanged source at `d73911463a1ad15ca9be21d5dbfa255df3f3790f` failed on this
Windows workstation using its existing Python 3.10 venv. Node spawned launcher
PID 57596; the real Store admission worker reported PID 7804. The old equality
assertion failed before assigning cleanup responsibility. The worker subsequently
failed its unchanged 45-second gate with `Owned admission gate expired; do not
restart`. Both PIDs were independently absent and the application fixture cleanup
was complete. The launcher's creation time was not captured before its exit; this
baseline does not establish that missing historical identity. The original #271
failure and its direct-worker environment workaround remain preserved separately.

`tests/frontend-admission.mjs` supplies the bounded test helper. A fresh nonce,
exact root/cwd/argv, expected virtual/base executables, parent lineage and creation
times bind the worker receipt to the independently verified spawned tree. A PID
or receipt alone grants no ownership. Missing, malformed, stale or conflicting
receipts fail startup. Generated receipts are published atomically.

Startup retains its 20-second bound. Cleanup writes the cooperative release first,
waits a bounded interval, then asks the existing owner to verify every recorded
lifetime terminal, using its strict fallback only if necessary. Each actual
signal retains fresh full identity verification inside Python. Repeated and
concurrent stops share one result. Unknown or changed lifetimes retain incomplete
evidence; a timeout never proves exit. Cleanup failure is attached to the original
startup error. Export teardown also attempts browser and application cleanup when
admission cleanup fails, preserving both the initiating error and cleanup errors.

The generated worker still uses the real disposable Store's `run_local_job`, the
original 45-second gate/error and explicit export denial followed by retry. It
pins root/data before backend imports. Its terminal receipt records the actual
Store job; successful accepted admission requires completed status and matching
job ID, worker PID/creation, kind and video. Deliberately rejected startup, failed
worker, unavailable Store evidence and unknown lifetime remain distinct. No
scientific or main application Store is used.

## Verification and reproducibility

Injected tests exercise direct/launcher-descendant ownership, wrong
nonce/root/cwd/creation/argv/executable/parent/PID/job ID, missing/malformed and
late receipts, early exit, spawn error, pre-acceptance failure, cooperative and
strict fallback cleanup, changed lifetimes, preserved errors and repeated or
concurrent stops. These deterministic records are separate from actual OS proof.

Opt-in actual tests use the existing normal Windows Python 3.10 venv with
`__PYVENV_LAUNCHER__` unset. They verify real Store admission and failure before
receipt acceptance, cooperative exit, completed Store jobs and independent
absence of launcher/worker lifetimes. A separate direct base-interpreter test
uses a generated standard-library process and an explicitly marked Store double;
it tests OS ownership only and claims no Store behavior. An actual missing
executable case checks spawn-error handling without inventing a process lifetime.

Run from the isolated worktree with the existing project runtime and declared
dependencies:

```powershell
node --test tests/frontend-admission.test.mjs
$env:FRONTEND_ADMISSION_PROCESS_TEST = '1'
node --test tests/frontend-admission.test.mjs
node --test tests/frontend-fixture-process.test.mjs
node tests/frontend-delivery.mjs
node tests/frontend-delivery.mjs --library
node tests/frontend-delivery.mjs --exports
node tests/frontend-editor.mjs
```

The unchanged default CI browser entry point exercises the real generated Store
denial/retry and helper cleanup. The standalone admission test file is run locally;
this change does not add a workflow invocation for it. Every delivery mode binds
the new helper in its evidence hashes. The 19 production, eight library and 13
export action groups, direct editor coverage, frozen parity and performance
protocol remain intact.

Final executable-source checks on this workstation:

| Check | Result |
| --- | --- |
| Admission regressions, including opt-in real processes | 23 passed |
| Unchanged ownership regressions | 71 passed, two explicit platform/opt-in skips |
| Production / library / export browser groups | 19 / 8 / 13 passed |
| Direct editor browser groups | 18 passed |
| Frontend tests, types, API contract and build | 200 tests passed; other checks passed |
| Staged production assets | Five files verified |
| Full Python suite | 4,145 passed, four optional skips, one existing warning; 440.57 seconds |
| Required static/dependency/repository checks | Ruff/format, pip, Prettier and repository verification passed |

Independent source inspection confirms all 40 existing production/parity/library/
export action bodies are unchanged, along with the complete shared fixture,
editor, parity and shuttle-helper files. Browser receipts confirm all three
delivery modes, data invariants and complete cleanup. A read-only process/Store
audit verifies 22 cleanup receipts and 38 original lifetimes absent, including
the preserved failed test attempts. Actual completed Store records match their
saved receipts through read-only SQLite access. New output, including copied
declared Node dependencies, generated media and test temporaries, measured about
155 MB plus a 16 MiB reserve at this checkpoint, below the 512 MiB cap.

The historical standalone `node tests/frontend-parity.mjs` entry point was also
attempted. It failed its unchanged initial `#onboarding` visibility assertion
against the current default React app, and its generated fixture cleaned up.
This legacy failure remains preserved; it is not counted as passing. The current
supported production delivery entry point passes all 17 frozen parity groups
and both production-specific groups. No parity assertion, entry point or app
runtime was edited to hide the standalone failure.

Local evidence is ignored and not supplied by a clone. Baseline log and terminal
audit are `.cache/goal-01a17154/baseline273-export.log` and
`baseline273-process.json`; raw baseline output is under
`.cache/w273/.cache/evidence/frontend-delivery-exports-gI4qIB`. The first actual
test run omitted fixture seeding and failed before admission launch; its direct
process and fixture cleanup evidence are retained. Seeding was corrected and the
subsequent actual runs passed, culminating in all 23 final cases. The first direct
editor attempt also lacked the fresh worktree's generated frontend build and
failed before fixture launch; building the unchanged frontend allowed all 18
editor groups to pass. The full Python command exited zero, with both captured
launcher/worker lifetimes independently absent and no observation errors. Its log
is `pytest273-final.log`, with receipt `python273-final-verification.json`.
The standalone parity failure is retained under
`frontend-baseline-iqmFiU`, with log `browser273-parity-final.log`. Exact PR/main
and complete public candidate delivery are recorded on the owning
issue as they complete.

These are software/process checks. They do not establish badminton annotation
accuracy, scientific source eligibility, full-match identities or model fitness.
No runtime, model, dependency, workflow, admission policy or shared signal
implementation changed. No video inference, training, model promotion or
deployment occurred.
