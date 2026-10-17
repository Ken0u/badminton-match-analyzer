# Threaded decoder shutdown fix

Prepared October 17, 2026. A native decoder deadlock could leave analysis running
after its last source frame, retaining the shared processing claim. The media
lifecycle now restores FFmpeg's native log callback before opening/closing app
containers, and player inference initializes Torchvision before opening threaded
decoders. Source timing, models, and annotations are unchanged.

## Observed failure and cause

An actual CUDA comparison processed doubles [278, 342) and [800, 850), then
stayed live at progress 1 without writing its result. Two native stack snapshots
showed the main thread waiting in `avcodec_free_context` while a decoder worker
waited for Python's GIL inside `av.logging`. This was a confirmed native deadlock,
not a slow GPU or an expired observation handle. The task-owned process was
stopped after checking its command, directory, creation time, and stack; stale
job recovery then released its processing claim.

Installed Torchvision 0.23's video module
[installs a Python FFmpeg log callback on import](https://github.com/pytorch/vision/blob/v0.23.0/torchvision/io/video.py).
That can replace PyAV's initial no-log callback after app startup. The
[PyAV 16.1 implementation](https://github.com/PyAV-Org/PyAV/blob/v16.1.0/av/logging.pyx)
documents native callback restoration for threaded workflows; its Python callback
acquires the GIL. Simply configuring logging once at startup is insufficient.

## Change and verification

All five application media-open call sites now use one managed context: video
ingestion, exact-frame access, timestamp-aligned processing, audio extraction,
and upload/container validation. It restores the native callback before open
and again before PyAV's context exit, including consumer exceptions. Torchvision
initialization finishes before player tracking opens any source scan/decoder,
so its lazy logging setup cannot run inside the first active decoder. Threaded
decoding and source-frame/PTS behavior remain available.

Native diagnostics follow FFmpeg's stderr verbosity. PyAV's Python log capture
is bypassed; exceptions still propagate, although their captured native details
can be less rich. Corrupt-media errors remain actionable in the API/browser.

Regression checks verify native diagnostics after a third-party re-hook,
preserved consumer exceptions, and 16 generated-media seek/early-close cycles in
a subprocess with a bounded timeout. The subprocess captures native Windows
DLL stderr reliably. The existing opt-in recognition test also now counts its
actual shot targets instead of every saved event; newly added serves/endings
are not family-classification targets.

The same 114-frame CUDA comparison now finishes and closes both decoders. The
[machine report](decoder-shutdown-verification.json) records source hashes,
windows, model checkpoint, timing, memory, and raw-perception run provenance.
The standard suite passes 340 tests with two optional GPU checks skipped; both
actual-checkpoint CUDA tests pass separately. Fresh generated-media browser QA
passes uploads, invalid inputs, source-frame images, camera scans, annotation
history/exports, and duplicate imports.

## Input evidence for subsequent rally work

Before the comparison, the frozen full-court views were processed with the
existing YOLO11n/TrackNet models and source-reviewed approximate court ROIs:

| View | Source frames | Player elapsed | Shuttle elapsed | Visible shuttle outputs | Visual contact proposals |
| --- | --- | --- | --- | --- | --- |
| Singles [255, 639) | 384 | 14.014 s | 29.277 s | 344 | 8 |
| Doubles [278, 866) | 588 | 17.356 s | 45.297 s | 440 | 12 |

All requested source frames were returned; no raw gaps were filled. These are
model outputs and runtime, not accuracy. The boundary manifest was frozen
before this inference, and the real annotation documents remain unchanged.

The [official YOLO11s pose variant](https://docs.ultralytics.com/models/yolo11/)
was compared on 114 deliberately difficult doubles frames. It produced exactly
four court-filtered boxes on 94 frames, versus 56 for the current nano model.
Those output-count rates are not detection accuracy: the cases were selected
from known failures and have no independent exhaustive box/pose truth. Inspected
overlays show an additional source-visible far player in service preparation.
The larger model still misses some people, and its research results do not
validate identities, poses, stroke labels, or rallies. The app's default model
and packaged manifest remain unchanged.

Rally-boundary proposals still need development and independently adjudicated
complete live rallies. Missing detections, camera edits, last hits, and interval
navigation locations must not become certified endings or exact timing truth.
Full-match automation and the original complete-correctness objective remain
unfinished.
