# Static versus temporal weak pose learning

Task [#391](https://github.com/Ken0u/badminton-match-analyzer/issues/391) tests
whether short-window observed player motion improves conditional stroke family
and forehand/backhand classification over a matched-capacity static control.
The [original pose inputs](AICUP_POSE_PILOT_REPORT.md) and
[weak actor associations](AICUP_ACTOR_CORRESPONDENCE_REPORT.md) are consumed
historical experiments and must not be repeated. This follow-up introduces no
media decoding, perception inference, image transfer or application model change.
Implementation preparation is not a completed learning result.

## Fixed inputs and comparison

The [versioned protocol](../data/manifests/aicup_pose_learning_protocol_v1.json)
retains 45 clips, 24,273 native frames and all 784 published weak references:
431 training and 353 validation rows. Exactly 652 weakly paired rows supply
research inputs; 132 unresolved rows, including three censored H0 rows, remain
in evaluation denominators. True hitters, scene eligibility and original-match
independence remain unverified. Training-ready rows remain zero; permitting a
private weak-supervision experiment does not promote their scientific status.

Both contact endpoints `[H-1,H]` remain. For shoulders, elbows and wrists of the
provisional hitter then defender, observed joint coordinates are normalized by
that frame's observed box height and box center/bottom. Finite display bounds,
confidence at least 0.25, a unique observed track, current calibration and the
contact camera namespace are required. Unavailable joints retain zero values,
zero confidence and explicit masks. There is no interpolation or identity repair.

Each arm has 108 inputs. The temporal arm concatenates three 36-value blocks:
contact-center pose, mean pose over native slots `H-5..H+4`, and mean adjacent
observed velocity using exact rational PTS differences up to 0.1 seconds.
Geometry averages observed values only; confidence sums use nominal divisors
2, 10 and 9. Nonadjacent samples are never differentiated. Native offsets do
not imply a constant elapsed-time horizon. The static arm concatenates center,
center and zero velocity. Features contain no family/side target, winner,
landing position or published A/B identity; only the previously frozen weak
correspondence selects provisional tracks.

Both models use the same 108→64→32 ReLU/dropout-0.1 network and biased eight-family
and two-side heads. Each has 9,386 parameters. Exactly two CPU fits run, static
then temporal, with seed 20261104, two CPU threads, 300 epochs, batch 64 and
AdamW (learning rate 0.001, weight decay 0.01). Family/side losses weigh 1/0.5.
Normalization and inverse-square-root class weights use weakly paired training
rows only. Missing raw values/confidences remain zero in saved features; the
fixed train-only affine normalization retains their encoded missingness.
No unavailable row is removed from reporting. Unknown targets are not negatives.

Every five epochs, retain a private checkpoint and select by the mean of
supported eight-group family macro F1 and side balanced recall, then strict
joint correctness over all validation rows, then earlier epoch. Compare the
selected arms by the first two scores, retaining static on a tie. Unsupported
training classes cannot be predicted as known. No threshold search, seed sweep,
test read, tuning after results or automatic model installation is permitted.
Private loss histories are integrity-sealed observations; verification does not
claim to recreate optimizer steps. It reloads every selection checkpoint and
recomputes predictions, validation metrics, selection and final reports.

## Reproduction and execution

Use the real workstation's existing environment and private input paths; a clone
does not include them. A fresh committed grant fixes a four-hour scientific
deadline and 1 GiB cumulative output limit. Commit the tested code, run the
integrity-only freeze and publish its exact consumer/runtime/protocol/input and
prospective hashes before any real feature extraction or fitting.

```text
python scripts/compare_aicup_pose_learning.py freeze --workspace REAL_WORKSPACE --prepared ORIGINAL_PREPARATION --native ORIGINAL_NATIVE --actor-prospective ORIGINAL_ACTOR_PROSPECTIVE_JSON --audit ORIGINAL_ACTOR_AUDIT --protocol data/manifests/aicup_pose_learning_protocol_v1.json --granted-at ORIGINAL_GRANT_UNIX --deadline ORIGINAL_GRANT_PLUS_FOUR_HOURS --output NEW_PRIVATE_FREEZE
python scripts/compare_aicup_pose_learning.py run --prospective NEW_PRIVATE_FREEZE/prospective.json --prospective-sha256 PUBLISHED_HASH --output NEW_PRIVATE_RUN
python scripts/compare_aicup_pose_learning.py verify --prospective NEW_PRIVATE_FREEZE/prospective.json --prospective-sha256 PUBLISHED_HASH --output NEW_PRIVATE_RUN
```

The entire original extraction/two-fit operation requires real shared Store
admission with root/data pinned before configuration imports. An exclusive
cohort-bound execution claim prevents repeating it using another output/freeze.
Failures preserve partial evidence and consume the claim. Verification remains
read-only after the original deadline and never refits. Original producer seals
are checked individually; this consumer does not retroactively enter historical
producer inventories. Source/frame clocks, orientation, cameras, calibrations,
annotations and all unknowns remain intact.

Report every original fold/capture, each family, side and family/side support,
confusion, precision/recall/F1, unavailable cases and full-denominator joint
correctness. Conditional results explicitly name their narrower denominator.
Even a positive comparison is familiar development evidence, not independent
accuracy, automatic contact detection, persistent identity, verified doubles
support or complete full-match annotation. Complete scientific rally references
remain **0/2**. Exact PR/main checks and full public code delivery are separate
completion requirements; source rows, pose features and model weights stay private.

## Software verification before the original experiment

Seventy-two new generated controls and all 212 focused checks pass. The full
suite passes 6,126 tests with four optional skips; lint, formatting, dependency,
strict JSON, UTF-8/LF, local links and whitespace checks pass. Clean source/wheel
and installed HTTP verification checks 113 package files, 62 public manifests,
five frontend assets, three SPA routes and authentication. An earlier sandboxed
package attempt could not fetch the pinned build dependency; its failure is
preserved separately from the successful normal-network verification.

Generated review exposed a checkpoint substitution that retained identical
argmax predictions; each checkpoint now has an independent saved record and
weight digest checked alongside prediction/history reproduction. Tests also
reject a competing isolated Store, preserve both ambiguous contact endpoints,
mask invalid native gaps/cameras/joints, retain unavailable/unknown rows, and
verify all checkpoint selections without refitting. These are software controls,
not improved badminton accuracy. No original real-source fit has run at this
preparation checkpoint.

The original [#389](https://github.com/Ken0u/badminton-match-analyzer/issues/389)
lease and scientific window expired before a real-source freeze, extraction or
fit. Its tested source and timing incident are preserved in
[draft PR #390](https://github.com/Ken0u/badminton-match-analyzer/pull/390) and the
[owning preservation checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/389#issuecomment-6641011191).
An authenticated original-host terminal-proof release was accepted before that
task was closed as superseded. This is a transfer, not scientific completion.
The fresh #391 grant supplies its own four-hour window; the old deadline is not
reset. Its adopted scientific code and recipe are byte-identical to the tested
preparation. Cumulative limits remain one original operation, two real CPU fits
and 1 GiB scientific output. No images, new inference or source replacements are
added. No original real fit has run at this continuation preparation checkpoint.
