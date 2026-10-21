# Exact-frame recovery during native playback failures

## Trigger and repair

Selecting a video begins a browser media load. Previously, a manual source-frame
seek during that load changed the selected frame and source clock but skipped
the exact-image request because playback was still marked as switching. If the
browser then rejected the media, its error handler cleared the switching flag
without requesting the pending image. The viewer remained blank until another
seek. A failed Play attempt could also hide an already loaded exact image.

[Issue #158](https://github.com/Ken0u/badminton-match-analyzer/issues/158) follows
the actual production browser failure in
[PR #157's first CI attempt](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39522977490).
The playback source was unchanged by that shuttle diagnostic; its passing CI
retry did not repair this bug. The production frontend came from
[PR #148](https://github.com/Ken0u/badminton-match-analyzer/pull/148), task #98.

Paused exact-frame requests now proceed independently of browser media loading.
The media-error handler also restores the current exact frame when paused.
Selection still uses the native frame index and source PTS. Existing request
sequence, video identity, selected-frame, paused-state and disposed-component
guards remain in place. Native playback failures still offer playback preparation;
genuinely unavailable source images still report an error and permit retry.

Only `Playback.tsx` changes application behavior. The pinned Node 24 build
regenerates the tracked `static/app.js` and `static/build-manifest.json` so
installed applications receive it. `index.html`, `style.css` and
`THIRD_PARTY_NOTICES.txt` retain their original bytes. No dependency, backend,
model, annotation schema or publishing policy changes are involved.

## Deterministic regression

The production FastAPI/browser test generates a four-frame VFR MKV with source
timestamps `[0, 0.04, 0.08, 0.68]`. It holds only that video's real native media
request, seeks frame 3 before metadata or an error can arrive, then releases an
HTTP 415 response. Chromium produces its own unsupported-media error; the test
does not dispatch a synthetic success or error event. Server-decoded source
images remain real generated-media responses.

On unchanged granted base `be7e98e1c2a1badec189c5575cf899c01bb98f5e`, with
all playback source and tracked static bytes verified equal to Git, the test
fails at the existing 15-second image timeout: frame 3, clock `0:00.68`, native
ready state 0, MediaError 4, image `src=null` and hidden. The preserved baseline
receipt SHA256 is
`13a3bfa3e1c1f5ac874c0c5cb2a116a803240358742a59af660ddb3a8b7448bc`.

The repaired production build verifies:

- Frame 3 displays with the correct video ID, frame identity and source time
  after seeking before the error; a subsequent frame-2 seek retains time 0.08.
- Failed Play restores the paused exact image. Unsaved event notes remain dirty
  and server annotations remain unchanged until an explicit Save.
- Delayed old-frame and old-video requests cannot replace the current image or
  clock. The test uses never-yet-displayed frames and bounded request waits.
- A real generated HTTP 404 keeps the exact image hidden and reports it as
  unavailable. Removing that fault permits a same-frame retry. A fresh document
  prevents Chromium's decoded-image cache from bypassing the fault injection.
- Saved annotations survive error recovery, source switching and the existing
  identity-mapped proxy preparation, playback and final-frame checks.

The separate library matrix exposed an existing test race: its first catalog
row can still carry the temporary upload filename while import is running.
The test now captures the accepted upload job and waits for that exact job's
successful completion before freezing expected metadata. It still checks upload
progress, source orientation, the original name and real UI selection. No test
timeout or production library code is changed.

## Verification and limits

Local verification uses Node 24.22.0, locked frontend dependencies, cached
headless Chromium and the existing Python 3.10 project environment. Checks include
the frontend contract and types, 89 frontend unit tests, three staging tests,
production build and staged provenance, all 18 default browser blocks, eight
library groups and 13 clip-export groups. The full backend suite passes
**1,492 tests with four existing optional GPU skips**. Ruff, formatting,
dependency consistency, changed-text UTF-8/LF and `git diff --check` pass.

Run from an isolated worktree with the declared review environment, pinned Node,
locked dependencies and the matching Playwright browser installed:

```text
npm ci --ignore-scripts
npm run frontend:contract
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
npm run frontend:stage:check
npm run test:delivery --workspace @badminton/frontend
node tests/frontend-delivery.mjs
node tests/frontend-delivery.mjs --library
node tests/frontend-delivery.mjs --exports
python -m pytest -q
python -m ruff check backend tests scripts
python -m ruff format --check backend tests scripts
python -m pip check
git diff --check
```

For external interpreters, pin `FRONTEND_PYTHON`,
`FRONTEND_CONTRACT_PYTHON`, and the candidate backend import path. Fixture
launchers pin disposable root/data directories before backend imports and verify
owned process lifetimes before cleanup. GitHub credentials remain cleared during
candidate execution. Native inference and the external YouTube downloader are
explicit fixture stubs; generated source media are real.

Detailed successful and failed browser evidence, generated sources, process
receipts and environment diagnostics remain ignored locally. Preparatory launcher
and image-cache test failures are retained; an interrupted development test has
unknown exit codes and is not counted as a successful run. Full application
accuracy, unseen-match generalization and support for every browser codec remain
unestablished. This repair improves source-frame review, not automatic badminton
annotation accuracy. Existing research data, model outputs and original local
changes remain preserved; `PROGRESS.md` remains deprecated and untouched.
