# Source appearance study: OSNet

Player IDs fragment during occlusion and fast pose changes, and matching uniforms
make doubles identity especially difficult. A fixed local study tests whether an
author-published person descriptor separates actual endpoint crops before adding
it to automatic track association. It fails the appearance-only diagnostic and
is **not installed or used for automatic identity links**.

## Reproducible model and inputs

The [author's OSNet repository](https://github.com/KaiyangZhou/deep-person-reid)
links the [author's public weight release](https://huggingface.co/kaiyangzhou/osnet).
The study pins release commit `a5c5cc037c24235cda3b21085b93ad77c9616224` and code
commit `f8cd150fdf77e8d9e1ed143b7f308c2c609ded50`. The source MIT license is retained
with the local source audit.

The MSMT17-trained `osnet_x1_0` checkpoint has SHA256
`48df972f72887b95cf3b43b3a07c3a7d2398381aea0f9cae64a7ef11d512b727`
and 17,273,805 bytes. The unmodified author architecture uses `pretrained=False`
and strictly loads all compatible checkpoint state with `weights_only=True`.
There is no implicit ImageNet download, model training or production weight
replacement.

CPU inference follows the author's RGB 256-by-128 bilinear resize and ImageNet
normalization. Each 512-value embedding is normalized to unit length. Endpoint
prototypes normalize the mean of the available endpoint embeddings. Controls
compare individual unit embeddings. Cosine similarities are descriptor scores,
not identity probabilities.

The sources are the existing supplied singles and doubles videos. All 32
temporally close old-track pairs from the 18 full-source player windows are
retained, including boundary-window duplicates and ambiguous alternatives.
Before new tracker or embedding outputs, source-frame sheets and crops were
reviewed: 11 pairs continue the same player, four show different opponents and
17 remain unknown because of occlusion, mixed crops or same-uniform ambiguity.
This is coding-agent visual development review, not independent human ground
truth or unseen evaluation.

A separate source-only review freezes 21 co-present different-person controls
from four doubles frames, including seven same-uniform pairs. Mixed crops and
occlusion are retained. One control frame contains three detected boxes for
four actual players; no missing player is invented.

Every crop is a PNG made from an exact source-frame JPEG. Crop and input-review
hashes are verified. The experiment consumes 255 distinct crop files with 226
distinct content hashes. All pair references remain present; duplicate pixels
can share an inference result.

## Fixed diagnostic result

The 0.90 diagnostic threshold was recorded before any embedding output and was
not adjusted after seeing failures.

| Source-reviewed group | Cases | Similarity at least 0.90 |
| --- | ---: | ---: |
| Same continuing player | 11 | 8 |
| Different opponents at track endpoints | 4 | 0 |
| Co-present different-person controls | 21 | 1 |
| Same-uniform subset of those controls | 7 | 1 |

All 17 unresolved endpoint pairs retain their descriptors and unknown source
labels. They do not become positive or negative truth. These selected cases
and overlapping control groups do not support a population accuracy or F1 claim.

The false match is between two distinct near-court doubles partners at source
frame 10,237, with similarity **0.900579**. The reviewed positive range is
0.807750 to 0.959409; the same-uniform negative range is 0.713000 to 0.900579.
Their overlap exposes the limit of appearance-only linking on these crops.
Raising the threshold to remove this one observed failure would not establish
generalization or recover the low-scoring true continuations.

## Decision and remaining requirements

No descriptor scores become player names, actor links or saved annotation truth.
The checkpoint stays outside the app; existing tracking and stroke weights are
unchanged. Source review files and annotations remain unchanged. Evidence is
preserved in `.cache/person-reid-source-audit-v1`,
`.cache/person-reid-pairs-v1` and `.cache/person-reid-evaluation-v1`.

Future appearance work needs reliable primary-person crops, explicit ambiguity
checks, temporal and motion evidence, and broader independent identity labels.
Cross-camera identity, end changes, replays and complete-match correctness remain
unproven. The next motion-tracker comparison retains the same source windows and
the additional breaks found in the first confidence-gate experiment.
