# First raw-video contact and doubles stroke learners

October 18, 2026. Both experiments completed their frozen held-out evaluation.
Neither model is installed in the application. These results do not satisfy the
full-match correctness requirement.

## Inputs and selection

Corrected native processing covers all 203 requested source rallies: 46,280
frames, with 67 training, 67 validation and 69 test clips. Match 1 supplies
training, match 2 validation and match 3 testing. The last match is mixed doubles;
all three are from the same venue. The
[doubles source audit](S2_DOUBLES_REPORT.md) and
[camera-context correction](EARLY_CAMERA_CUT_REPORT.md) describe the source and
input limitations. Unsupported views remain unknown.

All 203 native report chains and both feature caches were verified against their
source requests and hashes after completion. Source reference counts are
624/672/558; unavailable observations remain in the evaluation denominators.
The family/side cache has 608/662/548 available rows respectively.

The contact learner uses observed seven-offset arm/pose/shuttle windows, with
126 values per arm. A shared 126-64-32-1 MLP pools over arms and trains against
possible-contact intervals with multiple-instance supervision. It selects epoch
170 and peak threshold 0.95 using validation only. Its seed is 20261017.

The stroke learner uses two observed arm windows and their masks, totaling 254
values, followed by a 128-64 shared trunk and family/side heads. Published video
foot projections associate a repeated, uniquely matching hitter track for weak
supervision. Source feet and mechanics labels never enter feature values.
Missing or competing associations abstain. Epoch 80 is selected on validation;
normalization and class weights use training only. Its seed is 20261018.

Both models, thresholds and selection receipts were frozen before test
predictions. All weights load with `weights_only=True`. Exact recipes, model
hashes, class results and evidence hashes are recorded in the
[aggregate evaluation](../data/manifests/r2_learning_evaluation.json).
The local frozen training scripts and caches are research artifacts, not a
portable training CLI or a bundled product model.

## Results and decision

| Metric | Validation | Held-out match |
| --- | ---: | ---: |
| Contact precision against weak intervals | 0.805 | 0.738 |
| Contact recall against weak intervals | 0.811 | 0.851 |
| Contact F1 against weak intervals | 0.808 | 0.790 |
| Conditional stroke-family macro F1 | 0.556 | 0.498 |
| Conditional stroke-side balanced recall | 0.907 | 0.876 |
| Conditional family/side tuple accuracy | 0.579 | 0.500 |

The test contact result is 475 one-to-one interval matches from 644 peaks and
558 weak references. Weak source clock intervals are not verified racket-contact
times, and unmatched peaks are not independently adjudicated false positives.
These numbers are not exact contact accuracy.

Stroke metrics are conditional on the weak source contact clock and hitter
association. They do not include automatic contact detection or verified hitter
identification. The closed heads answer 548 of 558 source rows. Test family
results expose substantial failures: drop has only 1 correct result out of 18
references, net 54/143 and drive 71/127. Clear has 3/12 and insufficient validation
evidence to enable a threshold. These classes cannot be presented as working
automatic six-family recognition.

Validation thresholds enable lift, drop, smash and serve, and disable clear,
net, drive and other. On the test match, family answers cover only 192/558 rows;
155/192 are correct against weak labels. That aggregate precision hides poor
transfer: accepted drop precision is 1/6 and lift precision is 53/74. Forehand
precision is 236/277, below the validation-side target of 0.9. Validation
thresholds therefore provide no general precision guarantee.

The decision is to keep both learners experimental and preserve the existing
default. No thresholds were adjusted after seeing these test results. Match 3
is now an observed test result; future development guided by it needs another
source holdout before claiming unseen performance.

## Source controls

Separate source-assisted first-pass intervals were frozen before learning for
the held-out opening rally. The training example's source review followed
knowledge of the old baseline output and is explicitly development evidence.
Both reviews remain human-pending and nonexhaustive, with family and side
unknown. Comparisons use strict navigation-frame inclusion in the frozen
intervals, with no tolerance expansion or shifted labels.

| Source excerpt | Learned peaks | Heuristic v3 proposals | Source intervals covered: learned / heuristic |
| --- | ---: | ---: | --- |
| Held-out opening mixed-doubles rally | 10 | 2 | 6/9 / 0/9 |
| First training rally, overlapping source | 15 | 6 | 6/13 / 6/13 |
| Original singles first court view | 15 | 12 | Not adjudicated |
| Original doubles first court view | 36 | 20 | Not adjudicated |

More peaks do not establish more correct contacts. The held-out learner still
misses three frozen intervals; the training example does not improve strict
interval coverage. These partial controls cannot provide full precision/F1.
The heuristic comparison uses the immutable experiment's version 3, distinct
from the [floor-bounce correction](WRIST_REACH_REPORT.md) in version 4.

The first control comparison correctly rejected old original-video player
artifacts lacking the required source hash. Fresh CUDA small-pose runs on the
same source windows now record source hash and calibration validity; the
provenance guard was retained. All four controls then completed using the same
frozen learned weights and features. Original/research saved annotations and
old artifacts remain unchanged.

## Next work

1. Improve the observed flight and hitter representation using training and
   validation data. Retain missing-data, camera, scene and complete-context guards.
   Address net/drive and drop/smash confusion and the sparse clear supervision.
2. Independently review and freeze contacts, hitter identities and mechanics on
   additional source matches before opening new test predictions. Include singles,
   mixed doubles and difficult views; preserve unresolved labels.
3. Turn a supported recipe into reproducible training/evaluation tooling and
   compare against the existing proposal pipeline before product integration.
4. Continue resumable whole-match processing, court/scene handling, player
   identity and rally-ending work. This experiment does not resolve those gaps.

Local evidence: `.cache/contact-learning-v2-final-verification.json`,
`.cache/contact-learning-model-v2/{selection,heldout-weak-test,development-comparison}.json`,
`.cache/yolo-stroke-model-v2/{selection,heldout-weak-test}.json`, and
`.cache/refreshed-original-controls/completed.json`.
