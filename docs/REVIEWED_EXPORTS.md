# Reviewed rally export plans

The backend for [roadmap #70](https://github.com/Ken0u/badminton-match-analyzer/issues/70)
produces an inspectable JSON plan, plain reviewed rally clips and annotated full
videos or rally clips. The web API can start shared export jobs and download their
verified output. Frontend controls remain a separate phased increment; the
media-export roadmap is not complete.

```sh
badminton export-rally-plan VIDEO_ID --revision 3 --output /path/to/new-plan.json
```

Use a saved revision explicitly. The existing catalog opens in SQLite read-only
mode; a missing catalog is never initialized. The output must be a new file outside the
application data directory; existing files are never overwritten. The command
performs a CPU decode of the original source to audit native PTS, frame count,
orientation and endpoint. It does not run inference, acquire models or start jobs.

Each distinct rally ID in the saved events is retained, including ineligible
rallies and their reasons. Only a single reviewed/corrected serve and terminal
event with exact timing can supply boundaries. Missing, predicted, uncertain or
overlapping boundaries are not silently treated as complete rallies. A serve's
contact interval and an ending's terminal interval remain separate evidence.

Ranges start at the serve frame and include the terminal frame. Their exclusive
end is the next native frame's PTS, or the decoded final sample endpoint when the
ending is the final frame. An unavailable final sample duration makes that rally
ineligible. An imported endpoint inconsistent with a positive source duration
fails with a reimport instruction, including metadata stored before the VFR fix.

The plan preserves native frame indices and PTS, source origin/time base,
orientation and source SHA-256; the imported timestamp file has a byte hash.
Metadata and the complete annotation snapshot have SHA-256 hashes over UTF-8 JSON
with sorted keys, compact separators, literal Unicode and nonfinite values
forbidden. A newer saved revision does not change a plan of an older revision.
Source bytes, timestamp bytes, metadata and the selected revision are checked
again before returning a plan to detect concurrent changes.

All original players, unknown labels, predicted/interior events, review windows,
scene ranges, camera corrections and calibration ranges remain in the separate
annotation snapshot. Planning does not relabel scenes, bridge camera cuts,
extend calibration validity or infer missing hitter identities. Consumers must
respect that context; an eligible boundary range does not certify live footage,
exhaustive contacts, correct labels, or badminton annotation accuracy.

## Plain rally clips

```sh
badminton export-rally-videos /path/to/plan.json --output /path/to/new-clips
```

The renderer regenerates the complete plan from its original saved revision and
compares its canonical content before encoding and before publishing success.
Changed source bytes, timelines, metadata, revision content or plan range fields
invalidate the export. A newer saved revision does not invalidate an unchanged
older revision. The existing catalog opens read-only; no inference or model
acquisition is involved.

Choose a new output directory outside application data storage. Existing output
is never overwritten. Filenames use ordinal numbers rather than rally IDs, so
annotation strings cannot select output paths. Clips are staged and validated
before the completed manifest is written; failed or cancelled exports remove
incomplete output. Source media, saved annotations and predictions remain intact.

H.264 MP4 clips retain exactly the eligible native frames and their relative
presentation times, including variable-rate gaps and the actual final sample
duration. Rotation is applied to pixels; odd display dimensions are padded to an
even encoded size for browser compatibility. No frames are interpolated or
duplicated. Source audio is trimmed to the same half-open interval and its
relative offset is retained, including delayed audio and nonzero source origins.
The manifest distinguishes absent source audio from audio outside a rally range.
AAC encoder priming can precede the audible start; receipts record the expected
source sample interval separately from the encoded stream interval. Bounded
source/decoded waveform probes check the actual sample alignment.

The manifest retains every rally, including ineligible reasons, the original
annotation snapshot and scene/camera/calibration context. Per-clip receipts record
source-frame mapping, display/encoded dimensions, output hashes, audio timing and
validation results. Each clip references the original context through its annotation revision/hash
and the shared manifest annotation snapshot. The plan, source, timestamp and
annotation hashes identify the input evidence; decoded frames/pixels/PTS, packet durations and container duration
are checked before success. Consumers should retain the manifest with its clips.

Generated source-clock, orientation, uncertainty, audio, overlap, unavailable-input,
revision and CLI checks require no private samples or model weights. Browser
playback evidence concerns media compatibility, not badminton annotation
accuracy. These clips have no annotation burn-in; original predicted/unknown
labels remain evidence in the manifest. Running applications are not upgraded.

## Annotated full videos and rally clips

```sh
badminton export-annotated-videos /path/to/plan.json --scope full --output /path/to/new-full-video
badminton export-annotated-videos /path/to/plan.json --scope rallies --output /path/to/new-rally-clips
```

Choose the scope explicitly. `full` retains every original native video frame,
including footage outside eligible rally boundaries; it requires a verified
final sample endpoint. `rallies` uses only the eligible reviewed ranges and still
retains all ineligible rallies and their reasons in the manifest. Both modes
regenerate and compare the complete audited plan before rendering and before
completion. Outputs use new directories outside application data and preserve
previous exports, sources, annotations and original predictions.

Burn-in comes from the selected immutable annotation snapshot. Reviewed or
corrected exact serve, shot and rally-end events appear at their native source
frames. Contact and terminal uncertainty intervals remain visibly uncertain
across the inclusive interval; an ordinal inside that interval is not presented
as an exact contact. Shot family, forehand/backhand and hitter information retain
unknowns. Predicted events remain in provenance and are excluded from reviewed
truth burn-in; the event report records included/excluded evidence and reasons.

Saved visible shuttle points appear only at their exact native source frames.
The panel background is composed before saved court edges, with exact shuttle
markers drawn after text so upper-frame positions remain visible.
Missing, invisible or unobserved positions do not become interpolated tracks.
Reviewed scene labels and camera corrections remain visible context. Court
geometry applies only within its saved range and expires at camera cuts; no
player positions, track boxes or identities are invented when positional evidence
is unavailable. A replay label is preserved rather than silently removing frames.

The manifest binds a versioned overlay policy/configuration to its source,
annotation revision and rendered output hashes. It retains the original complete
snapshot and all rally/event denominators. Frame receipts preserve native frame
identity and relative timestamps; validation checks source pixels outside the
documented overlay regions as well as the expected rendered pixels, packet and
container endpoints and relative audio timing. H.264/AAC remain lossy codecs;
encoder padding is disclosed separately from audible source sample timing.

These exports visualize saved reviewed evidence. They do not establish complete
contacts, persistent identities, correct stroke labels or automatic badminton
annotation accuracy. Frontend export controls remain a separate phased UI task;
these commands do not switch or upgrade a running application.

## Web API export jobs

The existing application authentication and same-origin write checks also apply
to these routes. An export uses an explicit **saved** revision; unsaved browser
drafts are not exported. Starting a job does not automatically save annotations.

```http
POST /api/videos/VIDEO_ID/media-exports
Content-Type: application/json

{"revision": 3, "mode": "annotated-full"}
```

Choose `plain-rallies`, `annotated-rallies` or `annotated-full`. Revision is a
nonnegative integer; unknown fields and filesystem paths are rejected. A missing
video or revision returns 404. The response is 202 with the durable job `id`,
`kind: "media-export"`, and normal queued/running job fields. The request reads
the catalog and admits the job before any source decode, audit or encoding.
The existing Store admission is shared with analysis, tracking, imports and CLI
jobs: a live admitted job causes 409 rather than a competing export worker.

```http
GET /api/videos/VIDEO_ID/media-exports/JOB_ID
GET /api/videos/VIDEO_ID/media-exports/JOB_ID/files/manifest.json
GET /api/videos/VIDEO_ID/media-exports/JOB_ID/files/rally-000001.mp4
```

Status returns `job` and `available`. Queued, running, failed and interrupted jobs
have `available: false`. A completed verified export also returns its complete
`manifest` and `files` descriptors containing `filename`, `sha256`, `size_bytes`
and `media_type`. Download names come from that list; full videos use
`full-000001.mp4`. Downloads use safe attachment filenames and JSON or MP4 content
types. Keep the manifest with the media: it retains the original saved snapshot,
source clocks, hashes, native frame mappings, all rally/event denominators and
ineligible reasons. Empty eligible-rally sets still complete with a manifest;
annotated full-video mode still renders every native frame.

Downloads require a completed export job belonging to that video and a listed
file. Another video's job, another job kind or an arbitrary filename returns
404. Active, failed or interrupted exports cannot be downloaded. The service
checks the completion manifest and every output hash before reporting availability
or opening a download; missing, changed or unsafe output returns 409 with an
instruction to start a new export. Before HTTP success, each download copies the
requested, already opened descriptor into a server-owned private temporary file
and verifies that stored copy's complete length and SHA-256 against the completed
native receipt. It never reopens the export pathname. Replacing a pathname or
rewriting, truncating or growing the original inode after verification cannot
change the returned bytes; changes observed while building the copy fail with
409 unless the complete stored representation still matches the receipt.

Copying uses chunks of at most 1 MiB and refuses bytes beyond the recorded size;
response streaming uses 64 KiB chunks. A full match is not buffered in response
memory. Each concurrent download needs temporary disk space up to its recorded
size in the server's system temporary area, outside the job export directory.
Creation, write, flush, seek or verification-read failures reject the request
before HTTP success and close the temporary file. The response owns that file
until completion, disconnect or cancellation, including failure before the first
body read. No download snapshot changes the source, completion receipt or prior
exports, or adds files to their export directory.

Storage is server configured through `create_app(..., export_root=Path(...))` or
`BADMINTON_EXPORT_DIR`. The default is an `exports` directory next to the resolved
application data directory. It must be outside application data, and configured
paths and their ancestors must not be symlinks or Windows reparse points,
including directory junctions. Reparse metadata is checked on Python 3.10 and
3.12; it does not rely on the newer `Path.is_junction()` method. Clients cannot choose a directory.
Each job owns a new directory named with its generated job ID. Existing exports
are never overwritten; only the requested job's verified files are downloadable.

Source audits and native renderers run in the existing web worker with the
requested historical revision. A newer saved revision does not switch that
snapshot. Missing/stale sources, changed timeline/revision content, unavailable
FFmpeg or encoding failures leave a durable failed job and clean incomplete
output where the worker can perform cleanup. They do not change source media,
predictions, saved annotations or prior exports. Use the failure message to fix
the input and start a new job; exports do not resume inference or acquire models.

On application restart, existing Store recovery marks a verified dead worker's
active job interrupted. It does not restart encoding or expose partial output.
A hard process exit may leave incomplete files: retain them until the original
worker is verified stopped, then an operator may remove that job's directory.
No automatic retention deletion is performed. Completed exports remain on disk
until an operator removes them. Their downloads depend on retaining both the
export files and the original job catalog. Existing full-match analysis pause
controls remain unchanged; there is no new media-export pause endpoint.

This API prepares later React controls under the approved frontend phases; it
does not migrate the editor, change the default UI or upgrade running instances.
Its verification concerns source-preserving exports of saved evidence, not
automatic badminton annotation accuracy.
