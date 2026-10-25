# Optional audio source stability

Issue [#290](https://github.com/Ken0u/badminton-match-analyzer/issues/290)
investigates source validation in the optional acoustic extractor on baseline
`4cb27902f80d4b51e728bd55faf977667523cdf9`. It follows the source-time consumer
repairs in [#287](https://github.com/Ken0u/badminton-match-analyzer/issues/287).
Generated inputs reproduce a software integrity failure; they establish neither
native audio/video synchronization nor badminton annotation accuracy.

## Reproduction

The extractor validated imported source bytes before opening media. It returned
available cues, missing audio or a handled decoder fallback without checking
whether the source still matched the import after decoding and media teardown.
The missing-stream branch returned from inside the media context.

A frozen 39-case generated addition covers 24 direct and 15 actual contacts
API/Store cases. On unchanged production code, the combined two-file run yields
**26 failures and 66 passes**: 16 persistent-mutation direct cases, one injected
final-validation read failure and nine API mutation cases fail the required
rejection behavior. Stable controls, unexpected I/O exception preservation and
existing tests pass. The API mutation cases incorrectly complete their jobs.
The initial attempt instead yields one pass and 91 setup errors because the
chosen temporary directory's parent did not exist. That run is retained and is
not counted as a reproduction. The corrected run uses fresh short, ignored
temporary paths and initializes torchvision before media decoding.

Generated PCM, missing streams, ValueError and FFmpegError fallbacks are tested
against persistent edits during decoding and close, same-length edits with
restored modification time, and removal. A missing stream has no decode stage;
its corresponding mutation occurs during teardown. The final-read injection
uses the existing file-digest mechanism's FileChangedError, retaining its
conversion to SourceChangedError and its cause.

## Correction and preservation

The public extractor now obtains the existing extraction result, revalidates
the source through the existing resolve_source function and returns only after
that check succeeds. The existing decoder body remains in a private helper.
All normal-return branches therefore pass the same final check, including the
early missing-stream return and handled corrupt/unsupported audio. The check
runs outside the decoder's broad ValueError fallback. SourceChangedError is a
ValueError subtype and must propagate rather than become optional unavailable
audio. Removal retains the existing unavailable-source error.

Unexpected seek, decode and close I/O errors still propagate as the identical
initiating exception; no finally check replaces them with a later source error.
Stable unsupported/corrupt input retains its existing unavailable status and
empty peaks. No decoder retries, source copies, locks or new hash/cache behavior
are added. Native FFmpeg logging restoration in av_runtime is unchanged.

The actual API tests keep the real extractor, source validator, media wrapper,
visual proposal code, Store and background job. Only generated container/frame
behavior is controlled to place mutations deterministically. They retain a
nonempty visual proposal, original perception and prediction bytes, and both
saved annotation revision documents/timestamps, including a corrected event.
Changed-source jobs fail without publishing a contacts artifact; stable and
visual-only controls preserve the original proposal. The deliberate source
edits affect disposable fixtures only.

Two additional generated native checks decode an actual WAV and inspect an
actual silent MP4, then change each file after its native container closes.
Both reject the change. Existing real PCM tests preserve source PTS, video-origin
rebasing and onset behavior. Timestamp gaps, missing PTS, nonfinite samples,
optional/default-off support, consumer thresholds and visual behavior remain.
No API, schema, storage, consumer, model, dependency or source-validator change
is included.

## Verification and limits

The initial correction passes **166 audio direct/API/consumer tests**. After the
two native close controls are added, **216 focused audio, cache, import-stability
and media-runtime tests pass**. The first full run retains **4,440 passes,
eight failures and four optional skips in 477.94 seconds**. Every failure is a
generated artifact creation at a 262-266-character Windows path whose parent
exists. Executable/test hashes remain unchanged, both exact interpreter
lifetimes are independently absent, and no observation errors occurred. The
complete original run is retained. A fresh run uses a shorter temporary root
and preserves the disjoint upstream rally-boundary change merged meanwhile.
Full-suite and required static verification,
source stability, process-lifetime evidence and exact PR/main/controller/candidate
delivery are recorded on the owning issue as each finishes. Original failed
logs and generated artifacts remain ignored workstation evidence, unavailable
from a clone.

This is a final observable source check, not transactional snapshot isolation.
It cannot detect transient writes restored to the original bytes before that
check, changes hidden from filesystem metadata, or writes after the check.
Stable corrupt-audio fallback is not successful audio interpretation. Controlled
API frames and generated native media do not measure YouTube compatibility,
acoustic-event correctness, sound propagation or native AV synchronization.
No original scientific media/audio, labels, predictions, holdouts or models are
opened or changed. Complete scientific references remain **0/2** and all four
eligibility flags false; full automatic match annotation accuracy is unproven.
