# Experimental forehand/backhand baseline

October 17, 2026. The app now has a learned singles stroke-side head alongside
the family model. It proposes labels for explicit review and never saves them
automatically. Full uploaded-video accuracy, automatic rally boundaries, and
doubles recognition remain unverified.

## Training inputs and provenance

The authors' [published feature archive](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/tree/c93acfa736ed784ba7bea4ec9d360001dea9b728/stroke_classification/preparing_data)
provides normalized MMPose COCO-17 poses and shuttle observations. The 461,684,919-byte
RAR archive is pinned by SHA-256
`383ad8c17507046a45128d46c55f195fd008ce9db0f20ff23592239c31a253dc`.
It contains 100,443 NumPy files, expanding to 560,264,304 bytes. Source feature
arrays remain local and outside Git.

The preparation script checks the archive hash, validates every member path/link
before extraction, and verifies array sizes/CRCs when reading. Arrays load with
`allow_pickle=False` and must be finite with the expected shape. Exact
match/set/rally/stroke keys and source subtype names join features to the pinned
quality-filtered label index. Ambiguous/missing feature keys are excluded. No
model prediction is used as a training label.

Only shots in clear/lift/net/drop/smash/drive enter this first side baseline.
Serves, `other`, unknown/flawed labels, and quarantined matches are excluded. The
raw backhand convention and around-the-head handling follow the data report.
Published array gates require two available poses in at least 80% of frames,
nonzero shuttle input in at least 50%, and both poses at the central frame. The
arrays lack YOLO confidence values, so these are availability checks rather than
equivalent runtime confidence checks.

Of 13,947 unambiguously joined target-family clips, 1,427 fail those input gates.
The resulting **12,520 clips** retain the published original-match splits:

| Split | Matches | Clips | Forehand | Backhand |
| --- | --- | --- | --- | --- |
| Train | 30 | 10,149 | 6,502 | 3,647 |
| Validation | 5 | 1,233 | 810 | 423 |
| Test | 5 | 1,138 | 753 | 385 |

Source records excluded before the feature join total 22,501; 36 otherwise
eligible records lack an unambiguous matching feature key. The normalized label
index hash, feature archive hash, descriptor-cache hash, input gates, model hashes,
and recipe are retained in the trained artifact's metadata.

This is an alternate training input from the original publishers, not a claim
that this project's downloaded footage has been aligned. The direct-video label
index still declares zero verified training-ready video records. A short public
source seek confirmed a 25-fps decoded stream but did not establish exact contact
alignment; `data/manifests/source_alignment_pilot.json` records that open audit.

## Model and frozen selection

The pinned BST-0 backbone is frozen. Its pre-classification descriptor contains
300 values. A two-value known hitter court-end indicator is appended, followed
by an MLP with 128 hidden values and two outputs: forehand/backhand. Normalization
statistics come exclusively from training rows. This is stroke mechanics learned
from pose context; court end is a conditioning input, not a stroke-side label.

Training uses the pinned seed 2026, weighted cross entropy, AdamW at 0.001, batch
size 512, and a maximum of 40 epochs. Validation balanced accuracy, then validation
loss, selects **epoch 35**. The fixed confidence threshold is 0.8. Neither the test
labels nor the component benchmark choose training parameters or this threshold.

The packaged checkpoint is 161,449 bytes, SHA-256
`209204baf8660c03b3ed8de8f4cc6b4aec2578f412fd7f39edb7cdaffdec4842`.
[Its machine-readable training report](../backend/badminton/assets/stroke_side_v1.json)
contains the epoch history, validation/test results, majority baselines, and
per-family/per-match breakdowns. The small head is versioned with the code so a
fresh CPU/GPU installation can use it after obtaining the external base weights.
Large perception weights, source arrays, and generated training caches remain
outside Git.

## Results and limits

These measurements use supplied contacts, published MMPose inputs, and known
hitter court end. They are not measurements of the application's YOLO pipeline.

| Measurement | Validation | Frozen test |
| --- | --- | --- |
| Closed-set side balanced accuracy | 0.9517 | 0.9424 |
| Coverage at score 0.8 | 0.9270 | 0.9192 |
| Accuracy of answered side labels | 0.9720 | 0.9713 |
| Balanced recall with abstentions counted as misses | 0.9010 | 0.8790 |

Test confusion without abstention is `[[723, 30], [29, 356]]`, with rows/columns
ordered forehand/backhand. Training-majority and training-family-majority
baselines both have 0.5 test balanced accuracy. Scores are uncalibrated softmax
mass; the high accuracy of answered labels cannot replace reporting coverage.

| Test family | Forehand support | Backhand support | Closed-set balanced accuracy |
| --- | --- | --- | --- |
| Clear | 156 | 20 | 0.9718 |
| Lift | 149 | 150 | 0.9431 |
| Net | 178 | 172 | 0.9055 |
| Drop | 74 | 1 | 1.0000 |
| Smash | 115 | 1 | 0.5000 |
| Drive | 81 | 41 | 0.9569 |

The single backhand drop cannot establish reliability. The single backhand smash
is missed by this closed-set head. Left-handed/around-the-head and visibility
breakdowns also need more independently checked examples. These gaps prevent
declaring all requested family/side combinations validated.

A separate fixed-weight component benchmark applies the family classifier and
predicted court end on the same 1,138 published-feature test clips. The full
report is [published-recognition-evaluation.json](published-recognition-evaluation.json).
Family macro F1 is **0.8273**, including abstentions as misses; drive F1 is only
0.6339 and smash F1 is 0.7104. Court-end accuracy is 0.9974 on these supplied
clips, which does not establish persistent player identity recovery.

With predicted family/hitter gates, side-label coverage falls to 0.7645 and strict
balanced recall to 0.7287. Only **817/1,138 (0.7179)** supplied contacts have the
correct family, court end, and emitted side together. That conditional tuple
measurement omits real-video tracking, contact detection, persistent identities,
rally segmentation, and doubles. It demonstrates remaining error propagation;
it is not complete-event video accuracy or a completed release gate.

## Application behavior and checks

Runtime captures the backbone descriptor without changing family logits and
loads the packaged head, or a compatible local weights/metadata override.
Incomplete/corrupt overrides fail explicitly. Unknown hitter court end, non-target
family, low family score, or side score below 0.8 keeps side unknown. JSON run
artifacts retain side probabilities, score, model hash, and the input-domain
limitation.

The editor preserves a manually entered side even when the model disagrees. It
fills an unknown side only when the reviewed persistent-hitter hint agrees with
the editor's hitter; otherwise it leaves the side unresolved. Predictions still
require update/save and retain classification provenance. The independent-label
evaluator excludes those assisted labels from accuracy scoring.

An actual seven-target singles run produced four side proposals while all seven
family outputs remained identical to the prior run. The real pilot stays at
revision 2 with unknown family/side truth; these new proposals do not establish
its recognition accuracy. Local checks cover source joins, unsafe archive paths,
tampering, split leakage, train-only normalization, abstention accounting, model
loading, descriptor-hook cleanup, CPU/GPU inference, and review behavior. The CPU
container smoke also loads the packaged head. A repeat of the fixed training
recipe reproduced every packaged model/normalization tensor and loaded correctly
through its versioned checkpoint pointer.

## Reproduce and continue

With the repository's tracking/recognition/download extras and source label index
installed, use a current official [7-Zip command-line extractor](https://www.7-zip.org/download.html)
capable of reading RAR5. The preparation step downloads roughly 440 MiB and
extracts about 534 MiB into the ignored dataset directory.

```powershell
.\.venv\Scripts\python.exe scripts/prepare_side_features.py --download --extract --extractor C:/path/to/7z.exe
.\.venv\Scripts\python.exe scripts/train_stroke_side.py
.\.venv\Scripts\python.exe scripts/evaluate_published_recognition.py --output .cache/published-recognition-evaluation.json
```

Descriptor preparation and training share application job admission. Retraining
writes a versioned checkpoint before atomically replacing its metadata pointer.
Serialized hashes can differ across training environments; retain each run's
actual model/report pair. To use an override, keep the named checkpoint and
`stroke_side_v1.json` together in the configured weights directory.

The next priority is independently aligned source clips and validation on actual
YOLO features, with sparse strokes and difficult visibility included. Expand
rare backhand examples, measure complete events from predicted contacts, improve
family/contact errors, and implement reliable rallies and the four-player doubles
extension. None of those requirements is waived by this component baseline.
