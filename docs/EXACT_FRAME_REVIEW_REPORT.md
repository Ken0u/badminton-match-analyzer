# Exact native-frame review images

October 25, 2026. Owning task: [#303](https://github.com/Ken0u/badminton-match-analyzer/issues/303).

The exact-frame JPEG endpoint previously used the timestamp-seeking ingestion
helper. That helper accepts the first decoded frame at or after the requested
time. If the decoder omits the requested native frame, review could display its
neighbor with HTTP 200. The endpoint also checked source bytes only before
decoding and did not enforce the imported display contract.

A disposable four-frame lossless VFR diagnostic reproduced the substitution:
requested frame 1 had gray value 80, but dropping it returned frame 2 with gray
value 130. Shifted PTS and a source changed during normal media close also
returned successful JPEGs. The untouched control returned the expected frame.
This used generated media only and preserved registered metadata, timestamps
and annotations. It establishes a software failure, not badminton accuracy.

## Endpoint contract

`GET /api/videos/{id}/frame?index=N` now fully consumes the canonical native
reader for the half-open range `[N, N+1)`. The reader checks native timestamp
identity, requested coverage, imported rotation and dimensions, and registered
source bytes. It closes the media normally and revalidates the source before
the endpoint converts the frame or encodes its JPEG. Taking only the iterator's
first yield would skip that final validation; complete consumption is required.

An inconsistent or changed source returns HTTP 409 with an actionable message;
an unavailable source returns 404. Existing invalid-index handling remains 422.
Unrelated decoder and close exceptions retain their original precedence.
Successful JPEG quality, content type and private one-hour cache policy remain
unchanged. Keyframe preroll, nonzero source origin, variable frame times and
cardinal rotation retain their original semantics. The reader stops at the
requested native frame. The standalone ingestion `read_frame` helper retains
its existing compatibility; the application endpoint uses the stricter reader.

This builds on the [native range integrity repair](https://github.com/Ken0u/badminton-match-analyzer/issues/173)
and [post-close source validation](VIDEO_SOURCE_STABILITY_REPORT.md).
The [unsupported-playback recovery](EXACT_FRAME_RECOVERY_REPORT.md) addressed a
separate frontend loading race.

## Generated verification

The new endpoint suite contains 26 generated-media cases. Against the original
endpoint, 14 fail and 12 controls pass. After the repair, all 216 focused checks
pass, including the new suite, native frame and scene readers, imports, rotation,
media lifecycle, file caches, playback and court-context consumers. One local
baseline launcher first failed before tests because its temporary parent did
not exist; the corrected launcher creates a fresh directory. Both attempts
remain preserved. No implementation repair failure is hidden by that setup fix.

The cases cover missing middle/final frames, empty output, shifted/missing PTS,
source writes during decode and normal close, same-size writes/replacements with
restored modification times, removal, stale rotation/dimensions, all four
cardinal rotations, nonzero source origin, VFR pixels, error precedence and
invalid bounds. Original source metadata, timestamps, annotations and a
generated prior-prediction artifact remain unchanged. Lifecycle receipts record
terminal launcher, worker and observed descendant lifetimes; source hashes are
stable across each completed verification run. Final full checks, exact CI and
public delivery receipts belong on the owning issue.

The final full Python suite passes 4,631 tests with four optional skips. Ruff,
formatting, dependency consistency, repository text/JSON/local links and
whitespace checks also pass. Final executable and test bytes remain stable;
all observed process lifetimes are terminal. Exact PR/main CI and public
delivery are separate requirements recorded on the owning issue.

## Limits

Native identity is checked against imported timestamps with the canonical
reader's existing tolerances; this is not independent content authentication
of every decoded pixel. Cache-aware source checks rely on observable filesystem
identity/change metadata, falling back to fresh reads when reliable change
metadata is unavailable. Hidden or fully restored transient writes and writes
after the final check are outside the guarantee. This supplies no decoder
snapshot isolation. Existing client/browser caches can reuse a previous valid
JPEG without making another endpoint request.

No scientific frames, source labels, model inference/training, image transfers
or held-out scoring were involved. There is no model/default change or accuracy
claim. Complete scientific rally references remain 0/2; all four eligibility
flags remain false. Correct automatic full-match annotations remain unproven.
