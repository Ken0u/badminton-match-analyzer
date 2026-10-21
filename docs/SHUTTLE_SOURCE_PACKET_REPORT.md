# Native source-only shuttle review packets

Owning task: [issue 160](https://github.com/Ken0u/badminton-match-analyzer/issues/160),
under [localization milestone 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).
Status: the first attempt failed metadata validation before transferring video
bytes. Native census and extraction remain pending. This report records fixed
intended denominators and boundaries, not completed coverage or improved accuracy.

The [source declaration](../data/manifests/shuttle_review_sources_v1.json) selects
two official BWF TV broadcasts through normal public access. The
[fixed packet protocol](../data/manifests/shuttle_review_packet_protocol_v1.json)
must be committed before any acquisition. No source substitution, alternate
format, truncation, account, cookie or access-control bypass is permitted.

| Canonical public source | Declared category | Metadata duration | Selected format | Metadata bytes |
| --- | --- | ---: | --- | ---: |
| [go2uajSiBnE](https://www.youtube.com/watch?v=go2uajSiBnE) | Singles | 4,320 s | 137 | 1,135,039,222 |
| [H1setLK1tig](https://www.youtube.com/watch?v=H1setLK1tig) | Doubles | 3,950 s | 137 | 1,137,172,263 |

Anonymous metadata preflight reported both sources on official channel
`UChh-akEbUM8_6ghGVnJd6cQ`, selecting video-only AVC at 1920x1080 and 30 fps.
These are metadata assertions, not verified native timing or pixel coverage.
The selected stream has no audio and is not an original all-stream archive.
The 483-second `kEQBaobDUFY` highlights candidate was rejected. The longer
selected broadcasts' semantic full-match completeness remains unverified.

## Fixed sampling and unknown labels

Fully decode both complete selected streams before sampling. The native census
retains every decoded ordinal, original PTS and time base, origin, orientation
and geometry, with explicit unavailable, corrupt or nonmonotonic support. Do not
replace missing timing with nominal frame-rate arithmetic or repair frames.
Before extraction, verify the frozen consumer, declaration, protocol, raw-source
and complete native-clock hashes.

For each source with `N >= 64` native frames, select exactly 64 centers using
`floor(j * (N - 1) / 63)` for `j = 0..63`, including both endpoints. Each center
requests offsets `[-2, -1, 0, 1, 2]`, clamped to valid native ordinals. Retain
**128 case rows and 640 requested context memberships** across both sources,
including duplicate clamped endpoint memberships. Only image storage may be
deduplicated. Export oriented native PNGs with source-frame identities and hashes.
Models, detections, heatmaps, calibration, interpolation, scores and inferred
scene, difficulty or visibility labels play no role in selection or inputs.

A separate editable review template starts every visibility, difficulty and
scene label as unknown and every coordinate as null. Unknown is neither absence
nor a negative label. Manual review, source metadata, packet provenance and future
predictions remain separate. Nothing is registered into application truth; no
existing labels, predictions, model weights or application defaults are changed.

All four flags remain false in the declaration, protocol and resulting evidence:
`training_allowed`, `independent_test_allowed`, `model_deployment_allowed` and
`dataset_redistribution_allowed`. Public availability and a recent title/upload
date establish neither permission nor original-match independence. Original-match
identity, cross-corpus overlap, upstream checkpoint membership, camera context,
category support and media rights remain unresolved. Any overlap audit uses only
permitted public source descriptors; consumed holdout63 inputs, predictions,
protocols, private membership and artifacts are excluded.

A pre-acquisition exact-ID search checked only the tracked public
`shuttle_supervision_sources_v1.json` declaration and the supervision, corpus
diagnostic and visibility aggregate reports. Neither new canonical YouTube ID
appears in those four descriptors. This narrow string audit cannot rule out a
different encode, alternate URL, original-match overlap or upstream membership;
it does not establish source independence or change any eligibility flag.

## Execution and reproduction

The entry point is [prepare_shuttle_sources.py](../scripts/prepare_shuttle_sources.py).
Use the existing project environment and an isolated, frozen task checkout after
obtaining a genuine resource grant. Supply the original application root so the
launcher pins its real `data/processed` Store and `models/weights` before importing
configuration, while loading the executing checkout's own backend. An isolated
research Store cannot admit this work. GitHub, Project and OpenAI token variables
are removed before candidate imports. The actual worker must initialize
torchvision before threaded PyAV and preserve native FFmpeg logging restoration.

Example PowerShell command, with the two explicit paths replaced for the host:

```powershell
$appRoot = 'C:\path\to\original\badminton-match-analyzer'
$checkout = 'C:\path\to\frozen\task-checkout'
& "$appRoot\.venv\Scripts\python.exe" "$checkout\scripts\prepare_shuttle_sources.py" `
  --root "$appRoot" --output "$appRoot\.cache\shuttle-source-packets-new-lineage"
```

On POSIX use the original application's `.venv/bin/python` with the same flags.
Raw media, PNGs, native clocks, editable templates, signed download details and
private runtime receipts stay in the ignored lineage; a clone does not supply
them. Console output is limited to a completion status or redacted exception type.
Publish only code, public declarations and aggregate evidence in this report.

The protocol bounds downloads to 2 GiB per source and 3 GiB combined, total new
output to 6 GiB, native frames to 300,000 per source and cumulative data-worker
wall time to 7,200 seconds within the four-hour task. Failed attempts count toward
the wall-time budget. Outputs publish exclusively; retain original files and
all failed or pending evidence instead of replacing or silently resuming them.
Record the actual PID, creation time, working directory, command and matching
shared Store job before long work, with durable external observation and terminal
evidence. A timeout or missing observation handle does not establish process exit
or authorize restart. Frozen executed consumers cannot change while work is live.

## Evidence pending actual execution

The first admitted worker exited with code 1 after 4.625 seconds observed wall
time. Its matching Store job is failed; the original worker and observer
lifetimes have exited. Returned singles metadata still matches the selected
canonical ID, channel, format 137, size and geometry. The code incorrectly
rejected `was_live`, an ended livestream archive. The repair accepts `not_live`
and `was_live` while rejecting live, upcoming and unfinished streams. No media
bytes or packet rows were produced by that attempt; its metadata, frozen context,
admission and terminal receipts remain intact.

A retry must use a new output lineage with `--prior-exit` and its SHA-256 through
`--prior-exit-sha256`. The observer's sibling `.started.json` must identify the
same worker and original output. The runner verifies the external exit, worker
terminal, exited process lifetime, failed/interrupted shared Store job and
unchanged source declaration/protocol before carrying prior wall, download and
output costs into the new budget. A timeout alone cannot authorize this path.

| Evidence | Current status |
| --- | --- |
| Pre-acquisition committed consumer/declaration/protocol hashes | Pending |
| Actual downloaded source SHA-256, returned metadata and runtime provenance | Pending |
| Complete native clock seals and retained unavailable/corrupt cases | Pending |
| Actual 128-case / 640-membership packet and unknown-template seals | Pending |
| Real shared Store admission, process lifetimes and terminal outcome | Pending |
| Generated-media regressions and required project checks | Pending |
| Fresh independent exact-head review, CI and controller integration | Pending |
| Merged-main and complete public candidate verification | Pending |

Replace pending entries only with actual preserved evidence. Complete selected
stream, clock or packet coverage does not establish reviewed match completeness,
visibility/occlusion-category support, independent labels, localization quality or
full badminton annotation accuracy. No inference, training, threshold tuning or
model promotion is part of this task. Parent 65 and the full application goal
remain open. Independent source-only labeling and a separately frozen improvement
experiment require subsequent bounded work.
