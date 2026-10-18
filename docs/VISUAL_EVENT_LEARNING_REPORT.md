# Direct-video temporal event learning

The experimental learner takes video frames and predicts contacts, shot family,
forehand/backhand, and near/far court end. It requires no supplied contact times,
court calibration, player coordinates or shuttle trajectories. Implementation
and generated-data checks are complete. Real-source feature extraction and the
camera-equivalence audit are running; real-data training and held-out results
remain pending. No new weights are installed in the app.

## Source separation and supervision

The pinned archive and index are documented in the
[AI CUP source report](AICUP_CONTACT_SUPERVISION_REPORT.md). Packaged
`aicup_capture_groups_v1.json` assigns all 969 clips to ten conservative capture
contexts. Source review covered 20 first-scoreboard sheets, five secondary sheets
and four camera-representative sheets. Correspondence leaves 43 exact match names
unresolved. All 175 self-recorded hall clips remain together because three original
recordings have not been fully separated. Capture contexts can contain multiple
matches; they are not independently adjudicated original-match IDs.

Whole Bangkok, Kuala Lumpur, Birmingham, Osaka, Tokyo and both Jakarta contexts
form training. All Odense clips form validation; all Paris and self-recorded hall
clips form test. The 800 labelled-source clips yield 424/176/200 learning
train/validation/test clips with 4684/1707/1454 references. The 169 public unlabelled
`val` clips supply no supervision, normalization or gradients. No ShuttleSet,
S2Doubles or FineBadminton records enter this experiment. Cross-corpus original
source independence remains unresolved; the older gated holdout stays frozen.

Each raw contact ordinal H is supervised as the inclusive decoded interval
[max(0,H-1),H] while the universal zero/one base remains unresolved. All 19 H0
references remain censored/unadjudicated and in evaluation denominators. Missing
pre-video observations are never invented. Winner flags, last strokes and clip
edges supply no rally-end targets. Near/far is a court end, not permanent player
identity. Six requested families, `other` and `serve` are retained; half smash is
absent. These are published weak references, not independent semantic truth.

Source support before context filtering follows. Backhand smash has **zero test
support**: this experiment cannot validate that requested class. Counts alone do
not establish adequate coverage or accurate labels.

| Family | Side | Train | Validation | Test |
| --- | --- | ---: | ---: | ---: |
| clear | forehand |410|91|138|
| clear | backhand |39|22|13|
| lift | forehand |384|159|152|
| lift | backhand |458|150|88|
| net | forehand |785|280|207|
| net | backhand |696|311|182|
| drop | forehand |352|100|125|
| drop | backhand |43|20|13|
| smash | forehand |603|210|164|
| smash | backhand |6|6|0|
| drive | forehand |136|39|41|
| drive | backhand |55|30|11|
| other | forehand |157|55|45|
| other | backhand |136|58|75|
| serve | forehand |134|6|19|
| serve | backhand |290|170|181|

## Inputs, learning and evaluation

The frozen encoder uses official generic ImageNet
[MobileNetV3-small weights](https://docs.pytorch.org/vision/0.23/models/generated/torchvision.models.mobilenet_v3_small.html),
enum `IMAGENET1K_V1`, 10,306,551 bytes, SHA
`047dcff4addef86ea5bc2eff13c9614dc11f47ab1160d0a71a25e7db994f4e1f`.
Full oriented RGB frames are letterboxed 512x288, normalized, and pooled 2x2 to
2304 dimensions. This transfer preprocessing differs from the published ImageNet
classification transform; no ImageNet accuracy or author SwingNet reproduction
is claimed. Training augmentation flips actual image pixels before the encoder;
family, biomechanical side and court-end labels remain unchanged.

Source hashes, native PTS, display orientation, complete decode and finite
features are checked. Float16 arrays have hashes and last-written receipts; the
full completion registry and consistent encoder runtime are checked before
learning. The shared incremental scanner preserves the app's
[AdaptiveDetector recipe](https://www.scenedetect.com/docs/0.7/api/detectors.html).
Cuts and source-time gaps isolate contexts; they do not certify live play, court
visibility, replay status or rally boundaries.

Context has 31 bins over plus/minus 0.5 seconds, 25 ms maximum nearest-observation
error, 100 ms maximum source steps, and at least three distinct observations per
flank. Unavailable observations remain zero with explicit masks. The 128-channel
temporal network uses dilations 1/2/4/8 and retains masks at every hidden layer.
A 30 Hz fast path uses actual-frame halos and matches masked-window inference;
VFR inference uses source PTS and explicit windows.

Positive bags keep both plausible ordinals. The highest-scoring valid contact
receives semantic losses. Up to two negatives per supported contact are sampled
without replacement, at least 200 ms from every reference interval. Only original
and mirrored learning-train features determine normalization. The packaged
learning manifest pins seed, optimizer, losses, 100 epochs and validation schedule.

Selection maximizes validation **spotted family+side+court-end tuple F1**, then
contact F1, then earlier epoch. Matching is one-to-one, maximum-cardinality and
minimum interval-distance within 2/30 seconds. This measures weak interval agreement,
not adjudicated exact-contact accuracy. All references, including missing-context
cases, stay in denominators. Metrics disclose all 16 family/side combinations and
counts; unsupported recalls are undefined. Conditional classification is separate.

Test prediction requires completed training and unchanged protocol, normalization,
selected weights, threshold and implementation. Test results never select a model.
No real badminton event-head training or test prediction has run yet. Generated
fixture results establish software behavior only.

## Commands and job ownership

Install the optional `learning` extra with an appropriate PyTorch build. Use the
same root/data configuration as the app so CLI commands share its admission lock.
For the default repository layout, PowerShell commands are:

```powershell
$env:BADMINTON_ROOT = (Get-Location).Path
$env:BADMINTON_DATA_DIR = Join-Path $env:BADMINTON_ROOT "data/processed"
.venv/Scripts/python.exe -m badminton.cli prepare-visual-features .cache/visual-hit-source-audit-v1/part1.zip --index data/datasets/aicup2023/v1 --weights .cache/visual-event-learning-v1/mobilenet_v3_small-047dcff4.pth --output .cache/visual-event-learning-v1/features
.venv/Scripts/python.exe -m badminton.cli train-visual-events --index data/datasets/aicup2023/v1 --features .cache/visual-event-learning-v1/features --output .cache/visual-event-learning-v1/run
.venv/Scripts/python.exe -m badminton.cli evaluate-visual-events --index data/datasets/aicup2023/v1 --features .cache/visual-event-learning-v1/features --run .cache/visual-event-learning-v1/run --output .cache/visual-event-learning-v1/test.json
```

Feature extraction resumes compatible completed caches. Existing training/test
outputs are preserved. No command installs app weights or edits annotations.

The copied research launcher initially resolved its default data root under
`.cache`, missing the main lock. Fresh PID/creation, command and Store inspection
caught this. The existing worker was adopted into the explicit main Store without
re-inference. Its actual GPU PID owns the main lock; a monitor synchronizes
progress and status. Main annotations were snapshotted from the real Store at
adoption. The empty isolated Store snapshot does not prove preservation of real
annotations. Future frozen launchers must pin root/data before importing config.

## Verification and open work

The final implementation run passed **707 tests with four optional GPU skips**.
Ruff check/format covers 107 files and dependency consistency passes. The built
0.24.0 wheel matches all 70 package files, exposes the three CLI commands, imports
without loading Torch, and refuses an actual competing job in the main Store.
The [machine receipt](visual-event-learning-verification.json) records hashes and
scope. Main annotations match the real adoption snapshot. A runtime check found the old
UI process absent with port8000 closed; the verified64-file0.22.0 release was
restored with explicit root/data settings. Health is OK and its startup preserved
the active research job. The research model was not promoted. Two Torch checks use generated CPU fixtures:
exact fast/window agreement across cuts and chunk edges, and train/freeze/test
behavior including refusal of changed weights/thresholds. They do not measure
badminton accuracy.

Real extraction, scanner equivalence on all 800 sources, full training, validation
selection and held-out evaluation remain pending. Default app inference is
unchanged. Doubles learning, persistent identities, shuttle localization,
independently reviewed full matches, serve/end accuracy, unseen full-video
evaluation and missing-class coverage remain necessary for the user's full goal.
