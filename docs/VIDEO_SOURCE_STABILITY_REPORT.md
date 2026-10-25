# Native video source stability

Issue [#293](https://github.com/Ken0u/badminton-match-analyzer/issues/293),
October 25, 2026. This is a generated-media integrity repair, not a badminton
accuracy measurement. Complete scientific references remain **0/2** and all four
eligibility flags remain false.

## Reproduced failure and repaired behavior

The native frame reader validated the registered source before opening it,
then yielded exact frame identities, imported PTS and oriented pixels. It did
not check the source again after completing the requested range and closing
its decoder. Buffered frames could therefore finish successfully after the
underlying source bytes changed, allowing a camera scan to publish an artifact
bound to the earlier digest.

Four tiny generated actual-PyAV examples cover singles/rotation 0 and
doubles/rotation 90, with changes during decoding and after normal media
teardown. All four originally returned frames 0 through 3 and their exact
imported timestamps without an error, despite different final source hashes.
The preserved original receipt is separate from the repaired replay: all four
now raise `SourceChangedError` after decoder closure. These generated mode
labels exercise software metadata; they do not depict badminton matches.

`iter_frames` now calls the existing cache-aware `resolve_source` after successful
full iteration and normal exit from the existing `open_media` context. The
original FFmpeg logging restoration and container ownership remain intact.
A changed digest is rejected under the existing source-change error contract;
a removed source remains unavailable. No validation is installed in a generator
finalizer, so original decoding/teardown/consumer errors retain their precedence
and intentionally partial early close keeps its existing behavior.

## Verification

- **190 focused tests pass**, including generated native-video,
  camera-scan/API, orientation, source/cache/import, playback and native FFmpeg
  lifecycle checks. **4,482 full Python tests pass**, with four unchanged
  optional skips. Required Ruff lint/format, dependency consistency, repository
  UTF-8/LF/JSON/local links and whitespace checks pass.
- Real generated VFR subranges preserve native timestamps, preroll, orientation
  and exact requested identity. Existing completeness, missing/duplicate/backward
  frame, missing/foreign PTS, orientation and no-read-past-end checks remain.
  New cases reject in-place/same-size/restored-mtime edits and replacement,
  including removal after media close. An identical-byte replacement remains
  the same registered content. Existing four-rotation pixel comparisons pass.
- Actual generated camera scans reject changes both during decode and after
  close, before writing a new output or overwriting a preserved prior output.
  Actual disposable API jobs become failed and expose no completed run artifact.
  Original metadata, native timestamp bytes, registered video and saved
  annotations remain unchanged. No detector models are loaded.
- Dedicated generated controls preserve original decoder, teardown and injected
  consumer errors, as well as intentional partial close after the source changes.
  Check receipts bind unchanged executable/test bytes throughout verification
  and independently observed terminal launcher/worker/descendant lifetimes.

The owning issue retains exact source revisions, grants, receipt hashes,
process/test evidence, exact PR/main CI and public delivery checkpoints. The
first plan listed PR #283 as a dependency instead of its owning issue #281;
the controller returned idle and no implementation grant was issued. That
planning-only correction preceded this task's committed epoch-1 grant. Original
specification and idle receipt are preserved; no gate was bypassed.

## Limits and preserved state

This check validates observable source content around a **fully consumed**
range, not an immutable decoder snapshot. Streaming consumers can observe
provisional frames before exhaustion; they must finish successfully before
publishing results. A consumer that deliberately closes a partial iterator is
not certified by the new completion check. No API/schema, frames, native clock,
orientation, detection/model/default behavior or existing artifact changes.

Filesystem cache reuse retains the existing observable-change guarantees and
fallbacks. Hidden metadata/content manipulation, a transient source change that
is fully restored before the final check, and changes after that check remain
outside the guarantee. Failure rejection does not resolve scientific source
rights, independent annotation truth or complete automatic match accuracy.

No original scientific images, labels, predictions, private review plans or
held-out data are accessed. No research inference/training, image dispatch, source
acquisition, service/fee, model promotion, deployment, dependency, authentication,
workflow or policy changes. Existing environments/data/research, the disjoint
[#290 audio repair](AUDIO_SOURCE_STABILITY_REPORT.md), all 45 public manifests,
original predictions/annotations and deprecated `PROGRESS.md` stay preserved.
