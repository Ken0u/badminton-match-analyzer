# Doubles labels and an actual public-video probe

October 17, 2026. This increment prepares doubles supervision, fixes a source-label
interpretation bug, and exposes a substantial contact-detection failure on a new
camera. It does not provide a trained doubles recognition model or full-match
accuracy. The [machine-readable audit](s2-doubles-verification.json) retains
source hashes, counts, model/run provenance and the actual outputs.

## Verified source labels

The official [S2 Doubles repository](https://github.com/HuangYuHsien/S2DoublesDataset)
is pinned at `c9168210e13f4869cbc8ebf47f9bc671b056cbab`. Eleven metadata/annotation
files were downloaded and verified against their Git blob hashes. TrackNet
prediction files are deliberately excluded from the label import. Sources stay
outside Git; the packaged manifest pins their provenance and conventions.

There are **1,907 shot rows, six sets, three matches and 207 rally windows**.
The documented source requirement is 30 fps. All 1,907 coarse timestamps agree
arithmetically with that rate, which does not certify source-video alignment.
Match 1 is training/development, 2 validation and 3 held out, frozen by whole match
before fitting a doubles model. Three matches from one tournament are a small
resource, especially for unseen venues, handedness and rare strokes.

The deterministic importer preserves every raw row and unknown field. It keeps
source shot ranges separate from exact contact times: frame origin and endpoint
inclusion are undocumented. RallySeg windows include preparation/post-point
context and do not become exact serves/endings. Source projected hitting/landing
points do not become observed shuttle localization truth. Explicit backhand 0/1
maps to forehand/backhand; blanks stay unknown. The combined push/kill category
remains `other`. No half-smash class is added.

**1,854 rows pass label checks**, including 203 serves and 236 `other` shots.
The 1,415 rows in the requested six families break down as follows:

| Family | Forehand | Backhand |
| --- | ---: | ---: |
| Clear | 14 | 4 |
| Lift | 87 | 178 |
| Net | 196 | 211 |
| Drop | 68 | 4 |
| Smash | 237 | 1 |
| Drive | 189 | 226 |

Quality findings include one zero-length shot interval, two rallies lacking a
terminal-stroke marker, and one rally with the source problem flag. The importer
retains affected data with issues and excludes it from label eligibility. It
also checks ordering, interval continuity, rally containment, scores, splits,
source hashes and paths. Missing segment labels remain visible in the audit.
All 1,907 rows remain **media-unverified; zero are training-ready**. A first visual
source pass is not independent adjudication. No doubles weights were trained.
No license file was present in the pinned source; this increment bundles neither
the downloaded labels nor derived model assets.

## Bug fixed: terminal serves

Nine apparent serve/phase conflicts are single-stroke serve faults. Their source
type says serve, while phase 3 marks the final stroke. They are both serves and
terminal strokes; that marker does not give an exact rally-ending timestamp.

The existing ShuttleSet normalizer incorrectly excluded this same case. Its
pinned source has 20 such rows, all single-stroke rallies; 17 had no other exclusion.
Mapping version 2 recovers those 17, raising eligible records from 21,709 to 21,726.
The other three retain their existing exclusions. Misplaced phase 3 serves in
multi-stroke sequences still fail validation. The old v1 index, cached features,
trained side head and their reported results are unchanged. Corrected labels
were written into a separate v2 directory, not mixed into old model provenance.

## Actual source footage and failure diagnosis

The accessible official [BWF TV final](https://www.youtube.com/watch?v=EpLD0HrwDJU)
matches source match1. A 13-second excerpt from source [409,422) was retrieved
without authentication/cookies: 390 decoded frames, 1280x720, 30 fps, format 136.
Original stream PTS are retained alongside the derived clip, SHA256
`b45c2a05f4455d9ad7b72b3b62a097585dbbec876039a6fcc40498c6bfcefce2`.
Multiplying PTS time by 30 gives useful parent-frame hints; it does not prove
full-stream decode ordinals or source label timing.

Before inference, the first chronological rally was selected from the source
catalog, and the court view, player names on jerseys, service sequence and
post-point walk were inspected. The first serve's contact appears later than its
published shot-start cue. The ending includes an outside-sideline shuttle, with
precise landing/fault unresolved. First-pass local review intervals [42,47] and
[300,330] remain pending human adjudication. The frozen
[source review](../data/manifests/s2_source_anchor_review.json) contains no
model-derived labels and does not declare exhaustive contact truth.

CUDA processing ran in a separate research catalog, holding shared GPU admission;
the two original app videos/annotations remain exactly unchanged.

| Stage | Frames | Elapsed | Throughput | Peak allocated VRAM |
| --- | ---: | ---: | ---: | ---: |
| Small player pose | 390 | 16.003 s | 24.37 fps | 175.6 MB |
| TrackNet shuttle | 390 | 31.567 s | 12.35 fps | 457.7 MB |

Mean court-filtered player count was 3.98; shuttle output was visible on 301 frames,
with no repaired points. These are output counts, not measured accuracy.
The contact detector produced **one candidate, local frame 210**, against 13
published shot references in the excerpt. This is a major development failure,
not a verified recall measurement. Of 384 seven-frame windows, 139 lacked complete
raw observations, 185 failed the motion gate, 43 failed abrupt-vs-smooth fitting,
16 failed continuity/jump checks, and only one passed. A quiet pose/body count
does not establish wrist accuracy, and some shuttle trajectories are noisy.

The boundary detector emitted a possible serve with navigation 51 and inclusive
bounds [44,52], ambiguous tracks 3/4, and no ending. The interval partially overlaps
the source-first serve interval, but its navigation frame is later. The existing
ending rule requires an in-court stationary point and cannot handle this observed
outside-sideline termination. No detection thresholds were relaxed to make this
selected clip pass. These concrete failures prioritize the next work: better
subframe/noise-aware contact evidence, shuttle visibility/quality, out-shot ending
support, and independently adjudicated complete-rally timing before recognition.

## Reproduce the label audit

```powershell
.\.venv\Scripts\python.exe scripts/fetch_s2doubles.py
.\.venv\Scripts\python.exe -m badminton.cli import-s2doubles data/datasets/s2doubles/source/c9168210e13f4869cbc8ebf47f9bc671b056cbab --output data/datasets/s2doubles/v1
.\.venv\Scripts\python.exe -m badminton.cli import-shuttleset data/datasets/shuttleset/source --output data/datasets/shuttleset/v2
```

Tests use generated CSVs, including terminal serves, unknown side flags,
ambiguous taxonomy, invalid intervals, source problems, reversed frames, orphans,
tampering, leakage across splits, deterministic output and raw-source preservation.
Importers refuse to replace an existing index with different source, split or
mapping provenance. This protects datasets used by earlier trained models.
Native source/probe records are separate from automated software regressions.

Verification: 400 standard tests passed with four unchanged opt-in GPU tests
skipped. Both perception stages ran on the actual new source excerpt with CUDA.
Both real label-import CLIs and fetcher cache verification passed. Python/JS
formatting, dependencies and the packaged manifest/module are checked separately.
