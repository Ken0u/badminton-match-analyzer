# Reviewed rally export plans

The backend foundation for [roadmap #70](https://github.com/Ken0u/badminton-match-analyzer/issues/70)
produces an inspectable JSON plan. It does **not** render clips, burn in overlays,
alter the editor, or complete the media-export roadmap.

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

Generated source-clock, orientation, uncertainty, overlap, unavailable-input,
revision and CLI checks require no private samples or model weights. Actual clip
encoding, audio synchronization, burn-in overlays and frontend controls remain
separate bounded follow-ups. Running applications are not upgraded.
