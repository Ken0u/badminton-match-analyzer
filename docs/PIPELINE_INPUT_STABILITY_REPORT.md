# Full-match input stability repair

Issue [#317](https://github.com/Ken0u/badminton-match-analyzer/issues/317),
October 26, 2026. Baseline: `bf669b5332f4edc38634752664a4b00a1792250b`.

## Failure and resulting behavior

A fast cached full-match resume could report successful completion after the
original source, native timestamps or inference context changed. Source and clock
validation occurred only at entry; the context check ran at most once per second.
Six generated reproductions (three mutations in each of singles and doubles)
reused all 17 stages without inference and incorrectly returned
`processing_complete: true`. Completion was also written before the final
progress callback, allowing a callback failure or cancellation to leave a false
completed plan.

Processing now checks cancellation, the original source through `resolve_source`,
exact timestamp values through `timestamps_for`, and the camera/scene/court
context signature at stage boundaries. Fresh output is checked before checkpoint
publication and registration; recovered cache registration is checked too.
Progress checks remain throttled during a stage, with immediate cancellation
checks. A final input check follows the last progress callback and precedes
successful completion publication. The error path explicitly clears completion.
Source/clock failures remain failed jobs; context changes and cooperative
cancellation remain interrupted jobs. Both expose incomplete plans through the
existing API.

Completed stage bytes and reviewed annotations are preserved. A fresh output
rejected before registration remains provisional. Stable cache resumes retain
all 17 reused stages without native calls. Manual event-label edits do not change
the inference context; recognition-setting reuse and existing camera/scene/court,
native frame/PTS coverage and overlap ownership rules remain intact.

## Verification

The added generated regression cases were run before changing the pipeline:
23 failed and the unrelated manual-label control passed. The failures cover
fast cached resumes and newly produced stage output for source/clock/context
mutations in singles and doubles, terminal callback mutation/error/cancellation,
and real admitted API jobs. Timestamp mutation is only one microsecond, ensuring
that equality follows the exact clock recipe rather than native-output tolerance.
The tests use disposable Stores and generated contracts, with no real media,
model weights or scientific inference.

The five terminal-callback tests were strengthened to record completion state
without preventing the callback's mutation or exception. All five still fail
against the original pipeline loaded in memory; no baseline files were replaced.

After the repair, all 42 pipeline unit/API tests pass, including existing stable
resume, cancellation/admission, registration recovery, recognition-setting reuse,
context and actor-overlap cases. The final full suite passes 4,968 tests with
four opt-in GPU/checkpoint tests skipped. Ruff, formatting, dependency,
repository UTF-8/LF/JSON/local-link, frontend provenance and diff checks pass on
unchanged executable bytes. Exact PR/main CI, controller integration and public
candidate verification are required separately and recorded on the owning issue.

The initial full-suite attempt used a disposable configuration root outside Git
and omitted existing portable FFmpeg tools from PATH: 4,795 passed, 168 skipped
and nine fixture failures requiring ignored outputs. Its logs are preserved.
The final run uses the granted worktree as configuration root, disposable
data/weights/exports, and the existing portable tools. No environment or
scientific inputs were replaced to repair that test setup.

## Limits

This uses the existing metadata-aware file cache and timestamp loader. It does
not provide a decoder snapshot or atomic isolation against concurrent writes,
detect every transient write restored between checks, or guard writes after the
final validation. Cache/storage/schema/policy/model defaults are unchanged.
Generated software tests establish failure handling and artifact integrity;
they do not establish badminton annotation accuracy. Complete scientific
references remain 0/2. No data acquisition, image transfer, training, held-out
prediction access or model promotion occurred.
