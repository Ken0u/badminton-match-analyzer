# Source-aligned recognition data

The previous raw-video learners lack reliable examples for several requested
families, particularly rare backhand strokes. This increment adds verified
public label provenance and actual source-video checks before another training
experiment. It does not install a new classifier or establish automatic match
accuracy.

## Pinned publications and taxonomy

The [official FineBadminton repository](https://github.com/iLearn-Lab/MM25-FineBadminton/tree/d3fd88b61ebadd8773774b4fa95ab27da4811cc1)
links the [Finebadminton-20K release](https://huggingface.co/datasets/iLearn-Lab/Finebadminton-20K/tree/72cae601e08c83ee8ec7e19f8fd7850e9158af7d).
The importer verifies SHA256 for every one of its 70 annotation JSON files,
plus the original Chinese and translated English contact publications at the
pinned GitHub commit. The manifest records source revisions, file hashes and
the authors' full-media hashes and sizes. No media is bundled or fetched by
the importer.

The actual release contains **2,066 rallies and 20,757 stroke records**. Comparing
the bilingual publications resolves a misleading translation: raw `kill`
corresponds to Chinese `杀球` (smash), while `net kill` corresponds to `扑球`.
The latter remains `other`, as do pushes and blocks. `Net lift` maps to lift;
net and cross-court net shots map to net. No half-smash class is introduced.
These mappings come from the paired source labels, not from model predictions
or individual narrative comments.

| Normalized category | Source records |
| --- | --- |
| Serve, separate from shot families | 2,065 |
| Clear | 1,368 |
| Lift | 705 |
| Net | 2,952 |
| Drop | 1,372 |
| Smash | 3,015 |
| Drive | 1,816 |
| Other | 7,437 |
| Unknown | 27 |

Stroke side uses explicit forehand/backhand tokens. Court-end `top`/`bottom`
never becomes a mechanics label. There are 12,522 forehand, 8,190 backhand and
45 unknown side records. Source counts are not correctness measurements.

The smaller GitHub publications contain **414 contact-frame references in 40
rallies from 11 sources**. Their exact source/rally bounds, stroke order, action
interval, player and family join to the larger release without retiming. Both
language versions remain attached to each matched record. Disagreeing identity
or translated mechanics fails the join. One larger-release side omission is
retained as unknown even though its bilingual counterpart says forehand.

## Timing and quality boundaries

All 20,756 source records with action bounds describe positive-width intervals;
one record lacks those bounds. An action start, end or midpoint does not certify
the instant of racket contact. Only the separate published `hit_frame` field
enters `source_contact_frame`, and it remains unadjudicated. The final stroke
does not create a rally-ending event.

The index retains 27 empty family labels, 45 missing side labels, four action
intervals extending outside their rally, the missing action interval and the
cross-publication side discrepancy. Unusable labels are explicitly ineligible;
raw records and source bounds are preserved. Duration conventions are also
mixed: 1,006 rallies use inclusive frame counts, 1,056 use exclusive counts and
four have larger inconsistencies. Declared frame rates vary, including 25, 30
and approximately 24.63–24.79 fps. The importer never converts them into exact
application timestamps.

The [source paper](https://arxiv.org/html/2508.07554v1) describes singles footage
and annotation combining initial manual work with reviewed model assistance.
Its broad 25 fps description is insufficient to identify this release's frame
clocks. Published labels are useful supervision candidates, not independently
adjudicated truth for this application. The release overlaps 20 sources with
its own benchmark; source deduplication and match-level splits must precede
training. The current index leaves every split unassigned and every record's
`training_ready` false.

## Actual media and input checks

Two author-provided public source files were downloaded at the pinned release
revision and verified against its media hashes. Full decoding uses an isolated
store and the immutable 0.19.0 runtime, without app labels or reference geometry.

| Source | Decoded frames | Source clock | SHA256 prefix |
| --- | --- | --- | --- |
| 0001 | 126,450 | 30 fps; maximum ordinal/PTS difference below 3.4 ns | `3ff3e2e41a37ffb2` |
| 0011 | 113,751 | 25 fps; zero ordinal/PTS difference | `c91b7cff6d0b0680` |

All released rally ranges lie inside these decoded sources. Six pinned author
JPEGs from the first contact-labelled 0011 rally were compared with decoded
frames at the same ordinal and its immediate neighbors. The same ordinal has
the lowest RGB difference at all six positions; paired images were visually
inspected. This supports that sampled frame convention without changing labels.
It does not verify every rally or exact contact label.

Actual CUDA input extraction completed all five published contact-labelled
0011 rallies: 83 published contacts and 2,538 source frames including fixed
two-second margins. Small YOLO, automatic courts and TrackNet run sequentially.
All ten perception artifacts have complete frame/PTS coverage; hashes and actual
CUDA devices are checked. The five raw candidate lists are also verified by
deterministic recomputation from those inputs. No reference event, family,
side, identity or court label enters perception; app annotations stay unchanged.

Conditional training-actor selection uses only the published contact ordinal
and court end, with repeated unique observed track support and calibrated-view
guards. It yields **80 available 371-value inputs out of 83 references**. Two
references lack suitable court/observation context and one lacks a stable actor;
all three stay unavailable. Family and mechanics are separate targets, never
descriptor values. Five complete-rally feature artifacts retain the unavailable
rows rather than selecting a cleaner subset.

The 61 in-rally contact candidates have 59 one-to-one agreements with the 83
published references within 120 ms, leaving 24 unmatched references and two
unmatched proposals. At 40 ms, agreement falls to 58. This is a comparison with
unadjudicated published timing, not contact accuracy; annotation completeness
and every source frame's alignment have not been independently verified.

Local evidence is ignored: `.cache/finebadminton-source-audit`,
`.cache/finebadminton-media-v1`, `.cache/finebadminton-source-inspection-v1`,
`.cache/finebadminton-native-protocol-v1.json` and
`.cache/finebadminton-native-v2`. An initial extraction helper confused a
tracking summary with the saved frame artifact; its failed job remains intact.
The corrected helper reuses and revalidates the complete first player artifact
instead of repeating that inference.

The feature cache initially expected an API envelope around the research
producer's raw candidate list. That helper assumption was corrected without
rerunning GPU perception or modifying the original candidate bytes. Feature
and agreement evidence is `.cache/finebadminton-stroke-inputs-v2`; the complete
check is `.cache/finebadminton-increment-verification-v1.json`.

## Controlled training experiment

After source/input checks, a single frozen experiment adds all 83 references
from these five singles rallies to the existing R3 training split. Only 80
additional rows supply usable inputs. The original doubles training source and
validation source remain separate; no original test predictions are opened.
The 371-value representation, 128/64-unit shared network, seed, 300-epoch budget,
class weighting and validation selection rule are unchanged. Training has 707
rows, of which 688 are usable; validation retains all 672 weak reference rows,
including its ten unavailable inputs.

| Same weak development validation | Frozen R3 | With singles training data |
| --- | --- | --- |
| Eight-label family macro F1, including other/serve | 0.590437 | 0.580815 |
| Stroke-side balanced recall | 0.894304 | 0.893651 |
| Joint family/side agreement, conditional on source hitter/timing | 0.574405 | 0.581845 |

The selected augmented checkpoint is epoch 50. Drop and joint agreement improve,
but aggregate family performance declines and clears fall from one matched
label to zero out of only three validation examples. This does not justify
promotion. **The augmented model is not installed.** This reused weak validation
set is development evidence, not an untouched holdout or complete-event result.

The protocol, frozen training source, input receipts and selected weights remain
in ignored local artifacts: `.cache/stroke-augmentation-protocol-v1.json` and
`.cache/stroke-augmentation-model-v1`. The selected SHA256 is
`00e5587d9c9e2b02cb6e699262ba71e00fd8cacc3d14ef41ae3d2c9318a283c8`.
Neither the separate gated 75-rally test nor original R3 test predictions are
used to tune this experiment.

## Software checks

Fourteen new adapter regressions cover translation, separate action/contact
clocks, side omissions/conflicts, malformed intervals, exact joins, source hashes
and immutable output versions. The full suite passes **611 tests**, with four
optional GPU skips; lint and formatting pass. The actual CUDA checks above are
separate from those generated regressions.

The 0.20.0 wheel includes the pinned manifest; all 62 package files match source.
Its isolated installed-package CLI produces byte-identical normalized records
and manifest for all 20,757 records. Raw media, dataset contents and experimental
weights are excluded from the package.

## Reproduction and remaining model work

Place the pinned release JSON files under `SOURCE/finebadminton-20K/` and the
two pinned GitHub publications under `SOURCE/github-labels/`, preserving their
filenames from `finebadminton_manifest.json`. Then run:

```powershell
.\.venv\Scripts\python.exe -m badminton.cli import-finebadminton SOURCE --output data/datasets/finebadminton/v1
```

`records.json` retains raw source and contact-publication data; `manifest.json`
records hashes, mappings, counts and limitations. A different source/mapping
manifest requires another output directory. These files never populate app
annotations or reviewed exports.

Next, expand balanced aligned development sources and inspect the remaining
contact/input failures. Deduplicate original matches and freeze training and
validation splits before larger learners; the 70-file index is not globally
certified for training by this narrow source check. Native actor selection using
a published court end is conditional supervision, not automatic hitter attribution.
Doubles supervision and independently adjudicated full-match evaluation remain
required. This source work does not replace or bypass the separate gated
75-rally external-source test.
