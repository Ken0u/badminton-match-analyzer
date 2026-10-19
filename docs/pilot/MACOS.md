# Mac locked-review pilot

Actual Mac workstation smoke check on October 19, 2026, for
[task #81](https://github.com/Ken0u/badminton-match-analyzer/issues/81).
This establishes reproducible software behavior, not automatic badminton accuracy.

## Ownership and source

The dispatcher granted implementation epoch 1 to authenticated collaborator
`dootz1` on a Mac ARM64 host. The grant uses branch
`codex/issue-81-document-a-reproducible-mac-locked-revie`, reserves only this
file and no physical resources, and freezes specification hash
`28f4f0de09bfb342d1798fbdecd2de872ab3731cbd1b7d7408b19eba07f31b57`.
The tested source baseline is `1ea6166017cbc425d42693ef9de9dd19e623a104`.
Final PR head/base, independent review, main verification and candidate receipts
belong on the issue; they are not claimed complete by this local report.

## Actual environment

| Component | Observed value |
| --- | --- |
| OS | macOS 15.1, build 24B83 |
| Architecture | arm64 |
| Python | 3.12.13 |
| Node | 24.22.0, disposable local runtime |
| npm | 10.9.2 |
| uv | 0.9.4 |
| FFmpeg / FFprobe | 7.1.1 |
| Git | 2.39.5 (Apple Git-154) |
| Profile | review: dev, youtube, download; no tracking/CUDA extras |

The committed `uv.lock` SHA256 is
`fe4deca37e729cfe4bdf26c125e2d184659ecd1982ea9d8bf12e177e382de54d`.
The committed `package-lock.json` SHA256 is
`5b4cc79bf781af72ff766d953f105fa29fc3b948e2a1d8539fd721310e70c1f0`.

## Reproduction

After registration and a committed grant, create a fresh linked worktree at the
granted baseline on the granted branch. Make uv 0.9.4, Node 24/npm and the codec
tools available on PATH. From that worktree:

```sh
python scripts/bootstrap.py --profile review --python 3.12 --install
export BADMINTON_ROOT="$PWD"
export BADMINTON_DATA_DIR="$PWD/.cache/pilot-state"
export BADMINTON_GPU_TESTS=0
.venv/bin/python scripts/agent_queue.py doctor
.venv/bin/python -m pytest -q --basetemp .cache/pytest-mac-pilot --junitxml .cache/pilot-tests.xml
.venv/bin/python -m ruff check backend tests scripts
.venv/bin/python -m ruff format --check backend tests scripts
uv pip check --python .venv/bin/python
.venv/bin/python scripts/verify_repository.py
npm exec --no -- prettier --check 'backend/badminton/static/*' 'tests/*.mjs' 'scripts/*.mjs'
git diff --check
```

Bootstrap created a new Python environment and installed the locked profile plus
`npm ci` dependencies in disposable task storage. Existing application environments,
annotations, datasets, model weights and research processes were not migrated,
restarted or upgraded. No datasets or model weights were downloaded.

## Results and limitations

- Full generated-data suite: **902 passed, 11 skipped**, one upstream FastAPI/
  Starlette TestClient deprecation warning. Skips cover optional ML/GPU cases;
  this profile does not establish inference behavior or annotation accuracy.
- Ruff lint and format: pass. Dependency compatibility (`uv pip check`): pass
  for 47 installed distributions. Repository UTF-8/LF, JSON and local links:
  pass. Prettier and diff checks: pass.
- GitHub authentication resolves to `dootz1`; the doctor reads pilot mode,
  14 tasks and an unpaused queue. Registration and claim receipts are durable.
- The doctor's `ok` is false: it probes FFmpeg/FFprobe with `--version`, while
  these installed tools accept `-version` and both return success with 7.1.1.
  Generated-media tests pass. This diagnostic limitation requires a separate
  scoped follow-up; this documentation-only task does not modify the helper.
- The optional Codex CLI authentication probe fails; implementation uses this
  existing desktop session. The review profile needs no external model weights;
  the doctor reports them unavailable and the licensed packaged side asset present.
- Local evidence cannot establish Windows behavior, private GHCR delivery or
  the full two-host pilot. Those require their own task and workflow receipts.
  Keep pilot mode until both hosts have successful controller integration,
  merged-main checks and private candidate evidence.
