# Reviewed rally export plans

The backend for [roadmap #70](https://github.com/Ken0u/badminton-match-analyzer/issues/70)
produces an inspectable JSON plan and plain reviewed rally clips. Burn-in overlays
and frontend controls remain separate increments; the media-export roadmap is
not complete.

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
