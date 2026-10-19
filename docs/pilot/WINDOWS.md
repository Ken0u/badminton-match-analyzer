# Windows locked-review pilot

Actual Windows workstation smoke check on October 19, 2026, for
[task #80](https://github.com/Ken0u/badminton-match-analyzer/issues/80).
This establishes reproducible software behavior, not automatic badminton accuracy.

## Ownership and source

The dispatcher granted implementation epoch 1 to authenticated collaborator
`Ken0u` on the actual Windows AMD64 host. The grant reserves only this file,
no physical resources, and branch
`codex/issue-80-document-a-reproducible-windows-locked-r`. The specification hash is
`7ffd88dc6c3f100b78da755bd605ca51863e5147bf6e5c12924e62ef3f81efab`;
the tested source baseline is `9aa0f437fd5cacd948161ae09149ac2855f01c31`.
The owner requested a manual merge after independent review and passing checks.
Final head/base, review, merge, main verification and candidate receipts belong
on the issue; this local report does not claim those later steps are complete.
Task checkpoints use the issue; the owner has deprecated `PROGRESS.md`.

## Actual environment

| Component | Observed value |
| --- | --- |
| OS | Windows 11, build 10.0.26200 |
| Architecture | AMD64 |
| Python | 3.12.14 |
| Node / npm | 24.22.0 / 11.19.1 |
| uv | 0.9.4 |
| FFmpeg / FFprobe | n8.1.3-18-g46d899d7a0, build 20261018 |
| Git | 2.46.2.windows.1 |
| Profile | review: dev, youtube, download; no tracking/CUDA extras |

The `uv.lock` SHA256 is
`fe4deca37e729cfe4bdf26c125e2d184659ecd1982ea9d8bf12e177e382de54d`.
The `package-lock.json` SHA256 is
`5b4cc79bf781af72ff766d953f105fa29fc3b948e2a1d8539fd721310e70c1f0`.
Node and the codec tools use separate portable installations verified against
their publishers' SHA256 manifests. Machine PATH is unchanged.

## Reproduction

After obtaining a committed grant, create a fresh linked worktree on its granted
branch and baseline. Make uv 0.9.4, Node 24/npm and FFmpeg/FFprobe available in
that shell. From the new worktree, use PowerShell:

```powershell
python scripts/bootstrap.py --profile review --python 3.12 --install
$env:BADMINTON_ROOT = (Get-Location).Path
$env:BADMINTON_DATA_DIR = Join-Path (Get-Location).Path '.cache/pilot-state'
$env:BADMINTON_GPU_TESTS = '0'
& .venv/Scripts/python.exe scripts/agent_queue.py doctor
& .venv/Scripts/python.exe -m pytest -q --basetemp .cache/pytest-windows-pilot --junitxml .cache/pilot-tests.xml
& .venv/Scripts/python.exe -m ruff check backend tests scripts
& .venv/Scripts/python.exe -m ruff format --check backend tests scripts
uv pip check --python .venv/Scripts/python.exe
& .venv/Scripts/python.exe scripts/verify_repository.py
npm exec --no -- prettier --check 'backend/badminton/static/*' 'tests/*.mjs' 'scripts/*.mjs'
git diff --check
```

Bootstrap created a new environment with 48 locked distributions and ran
`npm ci` in disposable task storage. Existing environments, original Windows
PR #30, annotations, datasets, model weights and research state were preserved.
No inference, research restart, application upgrade or model/data download ran.

## Results and limitations

- Full generated-data suite: **906 passed, 11 skipped**, 49.81 seconds. The
  upstream FastAPI/Starlette TestClient deprecation warning remains. Optional
  ML/GPU skips are not evidence of inference behavior or annotation accuracy.
- Focused queue, Free integration, CI policy and environment tests: **120 passed**.
- Ruff lint/format (131 files), Prettier, repository UTF-8/LF/JSON/local links,
  dependency compatibility (`uv pip check`) and diff checks pass.
- Status-only GitHub and Codex sign-in probes succeed. The doctor resolves to
  `Ken0u`, reads pilot mode and an unpaused queue. No credential values are saved
  in the report or local environment receipt.
- The doctor reports `ok: false` because it probes FFmpeg/FFprobe with
  unsupported `--version`; both actual `-version` commands succeed. Generated
  media checks pass. Follow-up #84 owns the diagnostic repair; this task does
  not change its helper or disguise its failure.
- The isolated review environment has no external model weights. These software
  checks do not independently validate contacts, rallies, shots or identities.
  Private publishing and the full two-host pilot require their own successful
  workflow/queue receipts. Keep pilot mode until both hosts meet those gates.
