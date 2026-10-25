# Source identity through video import

Issue [#281](https://github.com/Ken0u/badminton-match-analyzer/issues/281)
investigates and repairs publication of inconsistent import artifacts when a
source changes between hashing and decoding. This is an import-integrity repair;
complete automatic badminton annotation accuracy remains unproven.

## Reproduced baseline

The unchanged baseline was `e48cbd9beb806b6fa95f85fe42df02d499277c06`.
Its `backend/badminton/ingest.py` SHA-256 was
`e0440753db7cdbb80cac1102e1defac7138dff969c73553281cc50d9fd935d66`.
The importer hashed the file, closed that read, decoded the pathname, then
published artifacts and registered the original digest without checking it again.

Three controlled cases used genuine, tiny generated H.264/MP4 files and disposable
Stores. Original media had three 32-by-32 frames at 25 fps; replacement media had
six 48-by-48 frames at 20 fps. No research media, labels, original predictions or
held-out inputs were accessed. These are injected reproducible races, not observed
customer incidents.

| Controlled change | Baseline result | Downstream validation |
| --- | --- | --- |
| Replace immediately before decoder opens | Successful import of six replacement frames under the original digest | `SourceChangedError` |
| Replace during first decoded progress callback | Successful import of three originally decoded frames while the pathname holds replacement bytes | `SourceChangedError` |
| Replace before decoder opens during an existing import | Successful reimport overwrites prior timestamps, metadata, poster and contact sheet under the old ID | `SourceChangedError` |

All three returned and registered SHA-256
`35ef2b6845abc88a7af87c28da9e4ece0e448239662c829a8e49b9baadec022d`
while the actual source was
`d787f7129353576d4e36ddcea6ccd403f044f31a0e49e9d4e0cb3eb6b61c5055`.
The original three-frame clock was `[0, 0.04, 0.08]` with duration 0.12 s;
replacement output was `[0, 0.05, 0.10, 0.15, 0.20, 0.25]` with duration 0.30 s.

Before the repair, the initial regression suite recorded **8 failures and
3 passing controls**. Each failure was an expected source-change rejection that
did not occur. Both baseline reproduction interpreter lifetimes were independently
observed absent after exit 0, with no process observation errors.

Local ignored evidence is retained under `.cache/goal-01a17154/` and
`.cache/w281/.cache/evidence/import281-baseline/`. The baseline reproduction log
SHA-256 is `35503e34e3de9801bdf381b5ff5725b9f2bd0f84e6277b5539482b89bacdf76a`.
These paths are workstation evidence, not artifacts supplied by a clone.

## Repair and regression coverage

The importer uses the existing stable `file_digest` reader for its initial hash
and checks that digest again after normal decoder/context shutdown, before any
poster, sheet, timestamp, metadata or Store publication. A changed digest raises
`SourceChangedError`; the existing reader's `FileChangedError` is translated to
the same source-validation exception. Other initiating I/O and decoding failures
retain their original exception. No cleanup/finalizer validation masks a decode
failure. An empty content-ID directory can remain after a failed new import.

The existing file-cache implementation and native FFmpeg logging restoration are
unchanged. The decoder still traverses the whole source and retains native
PTS/origin, VFR handling, last-frame duration, display rotation, dimensions and
sampling. No model, dependency, API schema, storage or default changed.

The final focused import suite passes **41 tests**: 13 source-stability tests and
28 API tests. Coverage includes:

- Valid same-length source replacements before decoder open and during decoded
  progress, both with ordinary and restored mtime; no new artifacts/registration.
- Changes during an actual initial digest read, including restored mtime.
- Failed reimports preserving all earlier artifact bytes, saved manual events,
  annotation revisions, upload provenance, review-start metadata and synthetic
  original prediction files. The existing downstream validator still rejects the
  changed caller-controlled source. Production code never restores that source.
- Stable source and identical duplicate imports with exact generated native
  clocks/dimensions/duration, mode-conflict rejection, and a metadata-only mtime
  update with unchanged bytes.
- Original initial/final read `PermissionError` and initiating decoder-error
  identity, without publication replacing prior valid data.
- Actual local/upload/YouTube-consumer API background jobs entering failed state
  on controlled changed input, no registration/artifacts, and existing owned
  upload/download cleanup. The YouTube downloader is stubbed with generated media;
  this establishes shared consumer behavior, not live external-service access.
- An actual local reimport job preserving previously uploaded provenance,
  reviewed annotations/revisions and every earlier artifact byte.

Existing successful upload, local duplicate and stubbed YouTube provenance tests
remain in that denominator. Rejected/failed cases are retained, not removed from
counts.

## Verification and delivery

Verification uses the existing Python 3.10 project environment, pinned root/data,
generated disposable media and fresh temporary directories. Torchvision is
initialized before threaded PyAV decoding. Focused media and full-suite results,
source/process receipts and exact delivery checkpoints are recorded on the owning
issue before submission and integration. Required Ruff, format, dependency and
diff checks pass for the repair; integration is still subject to exact PR CI,
controller merge, merged-main verification and complete candidate delivery.

The broader generated-media regression selection passes **178 tests** across
`test_import_source_stability`, `test_import_api`, `test_media_import`,
`test_orientation`, `test_playback`, `test_file_cache`, `test_video`,
`test_video_frames` and `test_av_runtime`.

## Limits

These are validation points around decoding, not an immutable source snapshot or
an atomic filesystem transaction. A persistent byte change detected at either
read is rejected before publication. A source can still change after the final
check; downstream `resolve_source` checks remain necessary. A transient change
restored to the original bytes before final validation, or a writer hiding changes
from filesystem observations, is not universally excluded. Failure while writing
otherwise validated artifacts is a separate publication concern.

The unchanged cache reader checks file identity and observable version metadata;
unsupported metadata disables reuse and causes repeated byte reads. Restored
mtime tests ran on this Windows filesystem. They do not establish every network,
coarse-clock or adversarial filesystem behavior or a full-match performance
benchmark. A second digest may require another whole-file read when safe reuse is
unavailable. Metadata-only changes between the digest reads are accepted when
bytes remain identical.

Generated media/software checks prove none of the required player, shuttle,
contact, serve, boundary or stroke/side annotation accuracy. Complete independent
scientific references remain **0/2**, and training, independent-test, deployment
and redistribution eligibility remain false. No inference, training, model
promotion, deployment, scientific assessment or original-source access occurred.
