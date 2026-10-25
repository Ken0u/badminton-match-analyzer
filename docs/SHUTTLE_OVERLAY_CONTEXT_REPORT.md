# Shuttle trails across source context boundaries

[Issue #266](https://github.com/Ken0u/badminton-match-analyzer/issues/266)
repairs misleading flight lines in the review editor. On source
`39bdbc6b5f38c3d9d3d0756e9617177de3ee14b3`, two visible observations on
consecutive frames were joined even when a camera cut, source-clock gap or
reviewed scene boundary separated them. Earlier trail segments could also
remain overlaid on a new camera view.

## Reproduction and behavior

A recording canvas executed the exact previous `Playback.draw()` body with
generated controller state. Frame 1 at native pixel `(10, 10)` and frame 2 at
`(90, 90)` produced `moveTo(10, 10); lineTo(90, 90)` in the continuous control
and in all four boundary cases: automatic cut, reviewed cut, timestamp gap and
reviewed scene start. No match footage, scientific labels or inference was
used. The original playback source SHA-256 was
`7b34baf9c26900674c7f6900fb5ed8821abf992d4b97b1c7c70bd2ab35100278`.
The local reproduction script and receipt are retained under
`.cache/goal-01a17154/`; these ignored artifacts are unavailable in a clone.

The editor now builds the recent path from observations within the current
camera, scene and time segment. It discards all history before the latest
applicable boundary, including when no observation exists on the boundary
itself. Missing, invisible and invalid coordinates break a segment. A visible
current observation still gets its native pixel marker; manual normalized
labels keep their separate marker and overlay controls retain their behavior.
No coordinates are interpolated or replaced with zero.

Camera and timestamp boundary handling is shared with court display. Current
reviewed cut additions/removals apply, while physical timestamp gaps cannot be
removed by a camera correction. Source-clock gaps use the existing frontend
threshold, greater than `max(0.1, 2.5 / fps) + 1e-8` seconds. This is boundary
detection on the timestamp table, not a replacement of native frame identity
with constant-frame-rate timing. Scene starts and exclusive ends also reset
the trail. Only the displayed 13-frame history needs an additional clock scan.

Legacy runs without boundary metadata retain continuous trails unless the
source timestamps or current annotations provide a boundary. Ordinary VFR
spacing below the existing gap threshold stays continuous. Original run
objects, saved predictions, annotations, models and processing defaults remain
unchanged. This display repair does not improve detector accuracy or certify
that camera/scene annotations are correct.

## Verification

- Twenty new generated cases cover automatic/raw/reviewed/preceding cuts,
  additions/removals, known and native-clock gaps, scene starts/ends, absent
  boundary observations, ordinary VFR and legacy continuity, invalid/missing
  positions, history length, source/run edges and unchanged inputs. All 200
  frontend tests pass, including the existing calibration and ownership tests.
- The generated editor browser matrix passes all 18 groups. Its new recording
  canvas case exercises the actual editor with continuous, camera-cut and
  scene-boundary responses. At frame 10, continuous footage retains earlier
  points and a line to `(300, 200)`; each new context draws only
  `moveTo(300, 200)`. Every case preserves the manual marker. Saved annotation
  JSON and original prediction-file hashes are unchanged.
- Type checks, backend OpenAPI contract parity, production build, staged asset
  parity, Ruff lint/format, dependency consistency, repository text/JSON/local
  links and whitespace checks pass. The first type check found an unused import;
  it was removed. An initial contract command lacked the explicit existing
  interpreter setting; selecting it allowed the unchanged contract to pass.
  Those failed attempts remain in the execution evidence.
- The initial full Python run finished with 3,826 passed, four skipped and eight
  failures in generated native-stub cases. Their deeply nested pending artifact
  filenames exceeded Windows path limits. No inference or real model ran.
  Extended-length paths also conflicted with SQLite URI parsing; a shorter
  system temporary directory lacked Git-ignored ancestry, while shorter folder
  names within this checkout were still insufficient. These attempts and an
  initial local-runner import-path collection error remain preserved.
  A disposable local runner uses short, uniquely numbered pytest temporary
  folders inside a fresh system-temp Git repository with a real ignore rule.
  It retains the actual Git checks and all assertions, restores the working
  directory import behavior of `python -m pytest`, and changes no tracked test
  or application code. All 102 cases in the two affected modules pass there.
  The complete unchanged suite then passes: **3,834 passed, four skipped**, in
  409.25 seconds, with one existing Starlette/httpx deprecation warning.

Browser receipts are retained under
`.cache/w266/.cache/evidence/frontend-editor-iVWEIF/`. They include the frozen
protocol/source hashes, generated case results, performance measurements and
fixture/static-server cleanup observations. Python logs are preserved in
`.cache/w266/.cache/pytest266*.log`; the local runner is
`.cache/goal-01a17154/short_tmp_pytest.py`. Those ignored files are local evidence,
not clone dependencies. Full Python checks and hosted integration/delivery are
recorded on the owning issue as they complete.

Software verification here concerns overlay continuity. Full-match automatic
annotation accuracy, exhaustive independently adjudicated contacts and
persistent identity remain separate release requirements. No new scientific
reference, data/model eligibility or deployment claim follows from this repair.

## Default production browser coverage (#271)

Inspection of actual artifacts from #266's exact-head CI run `40165715562`
found 18 production/parity, eight library and 13 export groups. All passed, but
the production suite did not execute `shuttle-context-overlay`. Its 20 helper
unit cases and the successful local direct-editor canvas case are separate
evidence. A hash of the direct-editor script in the CI receipt did not establish
that its canvas case ran. The original #266 reproduction, failed attempts and
local receipts remain preserved; #271 addresses this distinct coverage gap.

The direct editor and staged production suite now share
`tests/shuttle-overlay-context.mjs`. It records the actual editor canvas's shuttle
path and checks continuous observations, a camera cut and a reviewed scene start.
The continuous control must contain earlier observations and a line to
`(300, 200)`; each boundary variant must contain only the current `moveTo`.
Every variant preserves the normalized manual marker, hides/restores the
predicted path through the overlay control, and retains saved annotation JSON
and original prediction hashes. Route overrides affect disposable generated
responses only. No production implementation or scientific input changes.

The additional `production shuttle-context-overlay` group runs after all
existing parity/performance groups. The 17 frozen parity blocks, source-clock
semantics, performance protocol, ceilings and measurements remain unchanged.
The default inventory becomes **19 groups = 17 parity + two production groups**;
library and export inventories remain eight and 13. Evidence binds the shared
helper's source hash in both consumers and all production delivery modes.

The first local direct-editor run passes all 18 groups, and the first production
run passes all 19, including the new canvas case. The library run passes all eight.
Initial export verification exposes a preexisting Windows venv assumption:
the admission receipt names the actual Python worker while `spawn().pid` names
its launcher. The assertion fails before cooperative cleanup is registered.
The worker subsequently fails its unchanged 45-second gate. Both exact worker
and launcher lifetimes are independently absent, the Store job is failed and
the application fixture cleanup is complete. Original receipts/logs and
`.cache/goal-01a17154/failed-export271-terminal.json` are preserved; no worker is
restarted. The controller rejected a bounded scope request to reuse the existing
ownership verifier because it changes task semantics. No admission-harness repair
was applied. A local environment-only comparison instead launches the existing
venv's base worker with CPython's `__PYVENV_LAUNCHER__` set to that venv interpreter.
Its executable identity, prefix, base prefix, full import path and package file
locations exactly match normal venv startup. This removes only the launcher
process, permitting the unchanged PID-equality and real shared admission checks.
Both startup observations are preserved as `venv271-normal.json` and
`venv271-direct.json` in the same ignored evidence folder. The default CI runs on
POSIX; this local workaround does not repair Windows launcher portability.

An initial local read-only audit assumed absent process observations were status
objects. The existing fixture schema represents independently observed absence
as `null`; inspecting that schema corrected the audit without changing any
fixture, identity check or software assertion. The completed editor audit verifies
all three canvas receipts, helper/source hashes and terminal cleanup. An initial
repository-check command used a nonexistent filename; the actual
`scripts/verify_repository.py` passes. These command/audit failures remain in local
evidence and are distinct from test failures. Full verification and exact hosted
CI/delivery checkpoints are recorded on the owning issue as they complete.

Final local verification passes all 18 direct-editor groups and all **40 default
delivery groups (19 production, eight library, 13 export)**. Final delivery runs
use the equivalent direct venv-worker startup above; the original failed export
attempt is retained separately. Actual receipts include all three canvas modes,
manual markers, overlay toggles and unchanged saved annotations/predictions.
The independent read-only audit checks every expected group, every consumed
helper/source hash and complete fixture cleanup with final absent observations.
The direct editor's static listener is closed. The generated admission worker
cooperatively exits with code zero, and an independent local process check finds
its PID absent. Structural inspection of JavaScript syntax trees confirms all
39 original production/parity/library/export action bodies are unchanged; the
production-specific case is appended. The fixture and performance-protocol bytes
also match #266's merged source. Initial audit inventory assumptions and their
corrections are preserved in execution evidence.

All 3,953 Python tests pass (four optional skips, 453.47 seconds, one existing
deprecation warning), using the previously documented short-temporary-path
runner. Its launcher and worker lifetimes are independently absent after exit.
All 200 frontend tests, three staged-delivery tests, type/contract/build/stage,
Ruff lint/format, dependency, repository and whitespace checks pass. The existing
process-ownership suite passes 71 cases with two platform/opt-in skips. No new
native inference, model, scientific source or application-truth access occurs.

Local final browser evidence is under `.cache/w271/.cache/evidence/`:
`frontend-editor-hpnXHy`, `frontend-delivery-38fW5A`,
`frontend-delivery-library-qxnrDp` and `frontend-delivery-exports-HBn03T`.
Independent audits, frozen test hashes, Python logs and process/Store receipts
are under `.cache/goal-01a17154/`, including `editor271-audit.json`,
`browser271-final-audit.json`, `tested-source-hashes271-final.json` and
`python271-verification.json`. These ignored artifacts remain local and are
unavailable in a clone. The unfixed Windows admission-launcher behavior is tracked
separately in [#273](https://github.com/Ken0u/badminton-match-analyzer/issues/273).
Exact PR/main checks, actual hosted new-case receipts and candidate delivery
remain required; their checkpoints belong on #271. These generated software
checks do not establish full-match annotation accuracy.
