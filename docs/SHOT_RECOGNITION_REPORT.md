# Experimental singles shot-family baseline

October 17, 2026. This increment adds learned family suggestions to the existing
review pipeline. It does **not** establish family accuracy, automatic stroke side,
complete rally detection, or doubles recognition. The real pilot's reviewed
family/side labels remain unknown at revision 2; predictions were saved separately.

## Published model and adaptation

The architecture comes from the authors' [BST repository](https://github.com/Va6lue/BST-Badminton-Stroke-type-Transformer/tree/c93acfa736ed784ba7bea4ec9d360001dea9b728),
commit `c93acfa736ed784ba7bea4ec9d360001dea9b728`. Its MIT license, upstream/local
source hashes, and package import adjustment are recorded in
`backend/badminton/vendor/bst/`. The checkpoint is the official
`bst_0_JnB_bone_2.pt`, SHA-256
`5291095b880088ebb9aa5ec8a868ba1e0ced0cd57285b508feb495d94582cbe0`.
Its download source is pinned in the packaged model manifest. Strict,
`weights_only=True` loading matches **BST_0** with 1,809,985 parameters; it is
not the larger BST architecture with position features.

This head expects two ordered players, 30 time steps, COCO-17 joints plus 19
bone vectors, and normalized shuttle coordinates. The adapter follows the
published center/box-diagonal pose normalization, bone masks, temporal decimation,
zero padding, and valid sequence length. Missing pose frames have zero model
inputs; missing shuttle locations use zero only in the private input tensor.
Raw tracking artifacts retain missing values and are never interpolated.

The upstream pipeline uses MMPose. Our cached inputs use YOLO COCO-17. A shared
joint definition does not establish equivalent model inputs: this pose-estimator
domain transfer is unvalidated. Camera calibration orders and filters players;
it does not add the court-position branch absent from this checkpoint.

The upstream 35 classes comprise 17 types for the far player, the same 17 for
the near player, and unknown. The mapping preserves ranked source types:

| Published source type | Project event/family |
| --- | --- |
| Clear | Shot / clear |
| Lob, defensive return lob | Shot / lift |
| Net shot, cross-court net shot | Shot / net |
| Drop, passive drop | Shot / drop |
| Smash | Shot / smash |
| Drive, back-court drive, defensive return drive | Shot / drive |
| Return net, push, rush, wrist smash | Shot / other |
| Short service, long service | Serve / no family |
| Unknown | Shot / unknown |

The non-target wrist-smash source label remains `other` under the current
conservative mapping policy. There is no half-smash output class. This mapping
still needs adjudication against the project guide. Scores sum softmax mass
over source subtypes and court ends; they are uncalibrated rankings, not measured
probabilities of correctness. The default suggestion threshold is 0.5. Stroke
side is always unknown because this head has no forehand/backhand output.

## Processing and review contract

The API, CLI, and browser use cached same-video players/shuttle runs. Contact
proposals must reference those same parent runs. Targets include reviewed shot
events and unreviewed proposals within the runs' common range. A reviewed contact
inside a proposal's uncertainty interval takes priority, avoiding duplicate
classification targets. A serve may be suggested at a proposal; this is not a
verified start-of-rally detector.

Each target needs half a second of context on either side, player tracking at
stride 1, a single calibration covering the full clip, consistent source times,
no explicitly marked camera cut, two usable on-court poses in at least 80% of
frames, and visible unrepaired shuttle observations in at least 50%. The contact
frame must have two usable poses. These are engineering input gates, not tuned
accuracy thresholds. Automatic cut/replay detection is still absent.

Results are immutable job artifacts containing source/model hashes, input run
IDs, annotation revision, clip frames, input coverage, ranked source types, scores,
and abstention reasons. Reviewed identity mappings are applied to hitter hints
when retrieving a view; that does not rewrite the raw artifact.

Inference never updates annotations. A user must load a suggestion into the
editor, inspect the source, update, and save. Manually entered stroke side and
known hitter remain in the editor. Exports preserve separate contact and
classification provenance. Changing the family, kind, or contact frame clears
the displayed family score; the API rejects attaching that old score to changed
labels. Changed/deleted source events disable stale suggestions. Doubles requests
are rejected with an explanation instead of feeding four players into this head.

## Local evidence

Actual CLI run `69bf12fd32c74b359b9cb4bfcf6866d7` used singles source
`970dbd8adfe548d8`, annotation revision 2, players
`b8bdae17e8374a20bbf16f554c551f19`, shuttle
`ad0696c19b4b4be0beddf592a641cca0`, and contacts
`1f287c4134aa4633ad694d33c2ce9b42`.

| Contact frame | Output | Family score |
| --- | --- | --- |
| 2007 | Abstained: tracking window lacks preceding context | — |
| 2039 | Other | 0.675 |
| 2048 | Other | 0.980 |
| 2077 | Lift | 0.856 |
| 2130 | Net | 0.939 |
| 2154 | Lift | 0.929 |
| 2229 | Net | 0.824 |

The seven targets produced six suggestions. CUDA processing took 0.426 seconds
excluding model loading. These counts and labels are **smoke outputs, not accuracy
measurements**; some targets are unverified contact proposals. There are no
held-out family labels in this pilot. High scores on `other` are a reason to
inspect domain transfer and mapping, not evidence of correct recognition.

Local tests cover source-class order/marginal scores, pose and bone normalization,
padding, context/cut/time gates, target deduplication, model provenance, invalid
parent runs, no automatic annotation changes, stale-score rejection, and current
identity views. The opt-in CUDA checkpoint test verifies actual inference and
unchanged pilot/raw inputs. The isolated Chromium check runs real inference,
reviews and saves a synthetic fixture, preserves its manually entered backhand,
checks score clearing, immutable predictions, stale events, doubles switching,
and tablet layout. Its artificial label is never copied into pilot annotations.

Run the browser integration locally with the sample media, checkpoints, and
`scripts/ui_test_server.py` on isolated port 8001:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path (Get-Location) '.cache\ms-playwright'
node tests/recognition-browser.mjs
```

Ordinary CI runs generated-fixture API/feature tests without PyTorch, sample
media, or model weights. The CPU image installs the recognition dependencies;
local CUDA checks do not prove GPU container compatibility on another host.

## Work required for the full analyzer

1. Import compatible public stroke labels with original match identities and
   source taxonomy, then freeze match-separated development/validation/test sets.
   [ShuttleSet](https://github.com/wywyWang/CoachAI-Projects/tree/main/ShuttleSet)
   is a candidate for singles; compatibility and usable footage must be checked.
2. Adjudicate complete local rallies with family, forehand/backhand, hitter, and
   observable rally boundaries. Keep these separate from model suggestions.
3. Measure family macro F1, per-class errors, `other`/unknown behavior, abstention
   coverage, and complete-event correctness. Compare source-aligned MMPose versus
   YOLO inputs or fine-tune on the actual pose source.
4. Train and evaluate a stroke-side head, including left-handed and around-the-head
   forehands. Screen position cannot provide this label.
5. Improve contact recall and implement rally/camera/replay segmentation. Build a
   four-player doubles model with format-specific labels and occlusion tests.
