# Source-only shuttle visibility development audit

October 20, 2026. Owning task: [issue 139](https://github.com/Ken0u/badminton-match-analyzer/issues/139), a bounded prerequisite to [issue 65](https://github.com/Ken0u/badminton-match-analyzer/issues/65).

The unchanged native TrackNet baseline correctly localizes **14 of 25 known visible cases** at the fixed nominal tolerance. It misses ten visible shuttles, selects one wrong location and produces three false detections in confirmed non-play negatives. Twenty-eight other cases remain unknown and do not become negatives. This measures failures on two familiar development videos; it does not improve the detector or establish full-match/unseen accuracy. Issue65 remains open.

## Frozen source protocol and assessments

The [public protocol](../data/manifests/shuttle_visibility_protocol_v1.json) fixes 25 uniformly spaced centers per source using `floor((i+0.5)*frame_count/25)`, plus ten already-known singles gap-neighborhood frames: 2039-2043, 2047-2048 and 2077-2079. All 60 selected centers remain. These highlight videos mix play, replays, close views and title graphics; a uniform sample is not a balanced action or visibility benchmark.

The CPU-only packet renders at most two native adjacent frames each side, producing 271 original-size PNGs. Full-source decoding checks the original 12,023 singles and 12,148 doubles ordinals/PTS; display orientation, source clocks and all original input hashes are retained. Neither interpolation nor a neighboring flight position supplies a hidden center label. Raw media and labels remain ignored and are not supplied by a clone.

Two genuinely separate source-only agent sessions inspected all 60 centers at original 1280x720 size, using bounded adjacent context as needed. They had no cached predictions, app truth, research code or other-assessor labels. A reported 28 visible / 8 not visible / 24 unknown; B reported 24 / 8 / 28. Neither reported visible-but-unlocalizable truth or a context cut. These are agent assessments, not human-certified truth.

There are 40 cases with at least one raw difference: six visibility states, fourteen point estimates, nine uncertainty radii and 28 difficulty tag sets. These categories overlap. No pair has disjoint localization uncertainty disks; that does **not** make the point estimates identical. There are zero camera-context disagreements. All original assessments/reasons remain immutable.

The owning agent actually inspected 47 original centers and needed neighboring views for every disagreement and agreed negative. Thirteen matching cases retain the two assessments without claiming a third inspection. Six visibility disagreements resolve to five unknown cases and one observed top-border shuttle. The explicit adjudication and label copies were frozen and [timestamped on the issue before additional cached prediction access](https://github.com/Ken0u/badminton-match-analyzer/issues/139#issuecomment-6285925236).

| Source/selection | Cases | Visible/localizable | Confirmed not visible | Unknown | Visible/unlocalizable |
| --- | ---: | ---: | ---: | ---: | ---: |
| Singles | 35 | 18 | 3 | 14 | 0 |
| Doubles | 25 | 7 | 4 | 14 | 0 |
| Uniform grid only | 50 | 21 | 7 | 22 | 0 |
| Known singles gap neighborhood | 10 | 4 | 0 | 6 | 0 |
| All | 60 | 25 | 7 | 28 | 0 |

`not_visible` needs affirmative source/scene evidence; failing to find a tiny object is insufficient. All seven confirmed negatives are non-play views. No confirmed in-play occlusion, camera-transition or visible/unlocalizable case is established. Unknown racket/line/object overlaps stay unresolved. This sampling cannot measure those missing categories or certify camera boundaries throughout a match.

## Unchanged cache and provenance

The auditor chooses the unique existing all-source v1 manifest per fixed source, then its unique core owner for each case. It refuses multiple manifests and never chooses the best halo or prediction. Both sources use nine 60-second cores with four-second halos, the original small YOLO pose model and automatic court context, and TrackNetV3 with its unchanged 0.5 heatmap threshold. No model is loaded or run.

The relevant transitive graph is 38 existing artifacts: two whole-source camera scans and eighteen player plus eighteen shuttle windows. It verifies compact-JSON analysis/stage recipe keys, source hashes/metadata/full native clocks, ordered complete source row membership/PTS, dependency checkpoints, 48 frozen runtime files and both original model checkpoints. These are the relevant stages, not a new audit of all 92 downstream pipeline artifacts.

Read-only SQLite snapshots bind the original registered source documents, inference-context annotation revision and completed parent/stage registrations to the artifacts. Metadata is authoritative in SQLite; the clock sidecar is an actual producer input. The independent packet's original source metadata remains separately sealed. Missing a redundant metadata sidecar cannot substitute for missing registered metadata. A preliminary parser incorrectly required that sidecar; source-code inspection and a generated SQLite-only regression corrected this before final scoring. Its diagnostic index is preserved, without changing data, labels, thresholds or the selected baseline.

The final baseline index seals 92 existing files and the absence of two optional metadata sidecars. It also retains per-target SQLite snapshots. Camera cuts and timestamp gaps, per-row camera identity, transitive component-selection history, neural/background view extents, scene exclusions and calibration expiry are checked. Missing or incompatible outputs remain unavailable; changed sealed bytes, substituted/duplicated/reordered rows, wrong native clocks and nonfinite visible coordinates are errors. Missing known visible outputs count as misses; missing negatives never become true negatives. All60 actual outputs are available here, with zero unavailable reasons.

Baseline inference context has no manual camera, scene or court annotations; automatic courts remain unreviewed. Source assessment labels are never installed as scene exclusions or app truth. Current pure context guards operate on copies of that frozen inference context. Raw outputs and original SQLite documents are unchanged. The report also seals/copies the ten consumer source files and rejects concurrent consumer/input changes.

## Visibility and localization results

The tolerance is `0.005 * hypot(1280,720)`, about 7.343 pixels. Visibility asks whether a shuttle is observed. Localization additionally requires its position within tolerance. A wrong position contributes one localization FP **and** one FN while remaining a visibility TP. Unknown truth is excluded from those binary metrics but retained in every coverage table. Unlocalizable positives would remain in visibility and strict localization recall denominators; none are established here.

| Group | Visibility TP/FP/FN/TN | Visibility F1 | Localization TP/FP/FN/TN | Localization precision | Localization recall | Localization F1 |
| --- | --- | ---: | --- | ---: | ---: | ---: |
| Singles | 10/2/8/1 | 0.667 | 10/2/8/1 | 0.833 | 0.556 | 0.667 |
| Doubles | 5/1/2/3 | 0.769 | 4/2/3/3 | 0.667 | 0.571 | 0.615 |
| Uniform grid only | 13/3/8/4 | 0.703 | 12/4/9/4 | 0.750 | 0.571 | 0.649 |
| Known gap neighborhood | 2/0/2/0 | 0.667 | 2/0/2/0 | 1.000 | 0.500 | 0.667 |
| All | 15/3/10/4 | 0.698 | 14/4/11/4 | 0.778 | 0.560 | 0.651 |

Of the 32 known-visibility/localization-eligible frames,18 are nominally correct (14 locations plus four absences), or 0.5625. This is not accuracy across all 60 cases. Mean error across the 15 known-visible/predicted-visible pairs is 32.429 pixels, dominated by one 451.326-pixel wrong component; singles' ten pairs average 2.531 pixels and doubles' five average 92.227 pixels. These conditional errors do not include the ten missed detections.

Explicit source-label uncertainty gives `max(0,distance-radius)..distance+radius` error bounds. Seven nominally correct locations straddle the fixed tolerance; seven are correct across their full uncertainty disk. Strict localization recall across all 25 visible cases is therefore bounded by **0.28 to 0.56** under those recorded radial assumptions. These are label-coordinate uncertainty bounds, not statistical confidence intervals or estimates of unseen-match performance. No radius, threshold or label was changed to fit predictions.

| Outcome | Cases |
| --- | ---: |
| Nominally correct localization | 14 |
| Visible shuttle missed | 10 |
| Wrong localization | 1 |
| False detection on confirmed absence | 3 |
| Correct absence | 4 |
| Unknown truth, unscored | 28 |
| Missing/incompatible output | 0 |

## Difficulty and disagreement coverage

Difficulty tags overlap. They describe inspected source evidence, not separately balanced populations. Unknown counts remain explicit; zero-support groups have undefined scores, not perfect accuracy.

| Difficulty | Cases | Visible | Not visible | Unknown | Nominal localization TP | Visible misses including wrong locations | Localization F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ordinary | 1 | 1 | 0 | 0 | 0 | 1 | 0.000 |
| fast_flight | 7 | 7 | 0 | 0 | 5 | 2 | 0.769 |
| occlusion | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| distractor | 29 | 9 | 0 | 20 | 4 | 5 | 0.571 |
| blur | 28 | 14 | 0 | 14 | 8 | 6 | 0.696 |
| small_far | 18 | 10 | 0 | 8 | 8 | 2 | 0.889 |
| camera_transition | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| non_play | 14 | 4 | 7 | 3 | 2 | 2 | 0.444 |
| unresolved | 28 | 0 | 0 | 28 | 0 | 0 | n/a |

Forty disagreement cases contain 20 visible and 20 unknown frames: localization TP 10/FP 1/FN 10/TN 0, F1=0.645. Twenty cases without a raw disagreement contain five visible, seven absent and eight unknown: TP 4/FP 3/FN 1/TN 4, F1=0.667. Neither subset is an independent accuracy test. The ten deliberately included known-gap frames supply only four visible cases; two are missed. They must not be presented as ten confirmed missed detections.

## Failure evidence and next improvement

All ten visible misses contain `no_observed_component` at the fixed threshold. Five involve blur (including replay/racket/lettering overlap), two small far-court objects near lines, two grounded non-play shuttles, and one isolated ordinary replay-view shuttle. Ranking existing components alone cannot recover an absent component.

The one wrong doubles localization selects the sole observed component in the umpire/advertising area, 451.326 pixels from the source-reviewed forecourt shuttle. Its true shuttle is absent from the saved candidate components. The three false detections occur in source-confirmed between-points/post-match shots. The original pipeline had no reviewed non-play exclusion for these views. Source non-play tags are not an automatic scene classifier.

A concrete follow-up to issue 65 should target **observed-component recall and visual distractors**: expand source-aligned development supervision around the verified blurred/near-line misses and the wrong/background components; preserve these frozen measurements as development evidence; compare an explicitly frozen detector/heatmap change against the original baseline with unknowns and unavailable inputs retained. Any inference/training requires a new bounded grant and the real shared job admission. Do not silently lower the heatmap threshold or interpolate missing positions. Scene/context work should separately evaluate automatic non-play handling, including visible grounded shuttles, rather than treating every non-play view as absent.

Broader validation still needs original-source-separated singles/doubles, fast flights, actual occlusions and camera transitions, more precise expert adjudication where needed, and another independent full-match holdout. No consumed holdout is reopened, no experimental weight is installed and no accuracy promotion is proposed here.

## Reproduction and seals

The clone contains `scripts/evaluate_shuttle_cases.py` and its `packet`, `freeze-labels`, `baseline` and `audit` commands. Run `--help` for required paths/hashes. Use the project environment, set `PYTHONPATH=backend`, and pin `BADMINTON_ROOT` and an isolated `BADMINTON_DATA_DIR` before imports. Supply the locally owned original inputs and inventory matching the public protocol; a clone does not contain them, the cached baseline, weights or assessments. There are no automatic downloads or inference fallbacks.

Create a new ignored lineage for every packet, label freeze, baseline index and report. `freeze-labels` validates both real assessment documents and explicit adjudication before sealing their original bytes. `baseline` requires that frozen label lineage before reading predictions. `audit` requires the externally recorded baseline SHA, revalidates the complete source/label/cache graph and copies its consumer source snapshot. Do not reuse or overwrite old output directories. The CLI validates provenance; it cannot establish that an assessor actually inspected images, so the actual separate sessions and source-based adjudication remain necessary evidence.

| Artifact | SHA-256 |
| --- | --- |
| Public protocol | `49062b9b904b76010e35314d0e98d2ba2481f85cf1acfb59996eb2d0d14578d1` |
| Original source inventory | `273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822` |
| Source packet | `3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d` |
| Source assessment A | `2ac3294ff310ae2a1d4a0691d2a894eabd15294dd457c9391131de718fe96536` |
| Source assessment B | `91654166aa8d1b05feb241856671ab9fed126671b1031974d0ed49d4f12f4a6b` |
| Source adjudication | `1be266e4cf647ae9737c9464572a1aa279956a1e6df55a9365a37f9644a598c8` |
| Frozen labels | `fd25029ae49891f544989cdbfa20e5077571c1048c960e2d77ddee1fe7abd158` |
| Original singles video | `970dbd8adfe548d8b43259e283ba30d6900f16a4c429f108df435cec82bbf14f` |
| Original doubles video | `c406a1187130b845ca03ba807199bbebb72924566c58cc294217c56dae0af4dd` |
| Singles native manifest | `2ce4ce345934c0716c6dc65521bbc1c75d5d39959584f3f1b1bf2c8ccb087e37` |
| Doubles native manifest | `a4d61c54cd794ac53f6d2697634e9d76ff70a1f6bf4a73bd7e1eafa3b2c4221f` |
| Original TrackNet checkpoint | `df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a` |
| Original small-pose checkpoint | `1060bda4a27012060eca246f9b2adeea22eabb045a1e58f8d229be29b7ebc2ba` |
| Native baseline index | `915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64` |
| Executed audit consumer | `54e23dd58ee7c4c5ec077a8ae263f1eddcc3ff02d38dabad266e2bd5bc594959` |
| Aggregate audit report | `7c9a4bfb305c6fc3513db75749bc6d5f238fe9846b80cc954af17e378b24c895` |

Native manifest analysis keys are `1f432dfdbc473884578f5cf3c5f22b1f4930537652897fce093dc0c4513bdd5d` (singles) and `fe21d86637beda40b7889750c37a1a6c092730b1354716dae5dc533b108d2dbe` (doubles). The baseline index retains every relevant output/runtime/input hash, registered document and original producer versions. Producer versions are PyAV16.1.0, NumPy2.2.6, OpenCV4.14.0.94, PySceneDetect0.7.2, Torch2.8.0+cu126, torchvision0.23.0+cu126 and Ultralytics8.4.178. The audit uses the existing Python3.10.5 environment and executes no model.

All 51 focused generated regressions pass. They cover immutable packets and labels; native VFR/orientation identity; changed seals/clocks/registrations; duplicate, reordered and substituted rows; native observed components; SQLite-only source metadata; camera/scene/selection invalidation; missing known-positive outputs; unknown/unlocalizable truth; wrong-location FP+FN; uncertainty; and zero-support/group denominators. Full project validation passes 1,349 tests with four optional GPU skips; lint, formatting, dependency consistency, UTF-8/LF, JSON/seal, local documentation links and diff checks pass. Final exact-head independent code review, CI and controller/main delivery evidence belong on the owning issue and PR. These software checks do not certify the source labels or badminton accuracy. See the [earlier localization study](SHUTTLE_LOCALIZATION_REPORT.md) and [full-source pipeline report](FULL_MATCH_PROCESSING_REPORT.md) for the original baseline's separate history and limits.
