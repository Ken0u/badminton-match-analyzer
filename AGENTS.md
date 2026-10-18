# Repository guidance

## Scope and current state

Build a deployable badminton match analyzer for uploaded videos and public
YouTube matches, covering singles and doubles throughout each match. Required
annotations include players, shuttle, serves, rally starts/ends, and clear,
lift, net, drop, smash and drive with separate forehand/backhand labels.
Half smash is excluded.

Read `PROGRESS.md`, `PROJECT_PLAN.md` and `docs/BUG_REVIEW.md` before work.
`PROGRESS.md` is a tracked collaborator handoff: update it at meaningful
checkpoints and before handing work over. It describes a dated snapshot;
revalidate Git state, running processes and artifacts before relying on it.
Paths under `.cache/`, datasets and weights are local and are not supplied by
a clone. Do not assume another collaborator has those artifacts or processes.

The application and review tools work, but full automatic annotation accuracy
is not established. Preserve this distinction in documentation and UI claims.

## Development and verification

- Use the project virtual environment. This workstation uses Python 3.10 at
  `.venv/Scripts/python.exe`; on POSIX use `.venv/bin/python`. CI covers Python
  3.10 and 3.12. Install declared extras only as needed.
- Keep changes on a focused branch with reviewable commits and a PR. Merge
  after the required checks pass on the exact head, then verify merged main.
- Run focused tests for code edits and the required project checks before
  publishing. Commands include `python -m pytest -q`,
  `python -m ruff check backend tests scripts`,
  `python -m ruff format --check backend tests scripts`,
  `python -m pip check` and `git diff --check`.
- If the default temporary directory is inaccessible, give pytest a fresh
  directory under `.cache/` using `--basetemp`. Check docs/JSON/links for
  documentation changes; repeat expensive native inference only when needed.
- Keep tracked text files UTF-8 with LF endings. Source-byte hashes matter
  for package parity, frozen experiments and cache provenance.

## Video processing and shared jobs

- Pin `BADMINTON_ROOT` and `BADMINTON_DATA_DIR` before importing configuration
  in copied or frozen launchers. Heavy inference/training jobs must use the
  real shared Store admission through `run_local_job`; an isolated research
  Store must not permit competing GPU work.
- Before stopping or restarting work, verify the process PID, creation time,
  working directory, command, job status and durable artifacts. A timeout or
  missing observation handle alone does not establish a process exit.
- Preserve source PTS, orientation, native frame identity, camera boundaries,
  scene exclusions and calibration expiry throughout downstream features.
- Initialize torchvision before threaded PyAV decoding. Preserve the native
  FFmpeg logging restoration in `av_runtime.open_media` before opening and
  before closing media; previous violations caused decoder shutdown hangs.
- Preserve reviewed annotations and original predictions. Research commands
  must not install experimental weights or overwrite application truth.

## Learning and evaluation

- Keep complete original-source groups separate across training, validation
  and test. Audit cross-corpus overlaps and upstream pretraining separately.
- Freeze source hashes, protocols, normalization, model selection and
  thresholds before opening held-out predictions. Do not tune on the test;
  changes informed by a test result require another holdout.
- Preserve unknown/ineligible labels and unavailable input cases. Do not
  silently shrink evaluation denominators or reinterpret unknowns as negatives.
- Keep manual labels, source metadata, inferred annotations and model outputs
  distinct. Published ordinals, action intervals, winners and last strokes are
  not automatically exact contacts or rally-end times.
- Distinguish conditional classification from complete event detection and
  persistent player identity. Green software checks, finite features and
  processing coverage do not prove badminton annotation accuracy.
- Keep raw videos, annotations, datasets, weights, credentials and `.cache/`
  artifacts ignored. Commit reproducible code, public source manifests and
  aggregate reports. Respect each dataset's usage and redistribution terms;
  research data are not automatically deployable model assets.
