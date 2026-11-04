# Controlled development stroke classifier capacity

Task [#380](https://github.com/Ken0u/badminton-match-analyzer/issues/380) compares
one smaller classifier against the fixed [R3 reproduction](PORTABLE_STROKE_TRAINING_REPORT.md).
The MLP has 56,522 parameters for 608 available training rows; the linear model
has 3,720 parameters. This is a development capacity ablation, not evidence that
the original model overfits or that the smaller model generalizes.

The [fixed protocol](../data/manifests/stroke_capacity_protocol_v1.json) retains
the original training/validation matches, input audits, normalization, class
weights, optimizer, seed, schedule, selection and abstention policy. Only model
capacity changes: the linear model uses independent affine family/side outputs
without shared hidden layers or dropout. Both requested and other/serve labels
remain present; half smash is excluded. No test files are opened.

The existing private inputs retain all 624/672 original rows, with 608/662
available inputs across 67 training and 67 validation clips. Published source
clock and hitter association remain weak supervision. The one validation match
has sparse classes, including only three clear labels. Upstream perception
overlap is unresolved. S2Doubles has no license file at its pinned commit;
labels, features and derived weights remain private research assets.

The CLI first audits and freezes exact original inputs, protocol, runtime and
execution sources. Publish the prospective source/hash commitment before either
real fit. Both fits share the real main Store admission; configuration is pinned
before imports, outputs use a new exclusive ignored directory, and code/input
mutation or deadline expiry prevents completion. Successful partial artifacts
remain on failure. Completion follows durable main-job completion. No model is
installed in the application.

```text
python scripts/compare_stroke_capacity.py freeze --root INPUT_ROOT --manifest ORIGINAL_MANIFEST --manifest-sha256 ORIGINAL_HASH --protocol data/manifests/stroke_capacity_protocol_v1.json --deadline GRANT_DEADLINE --output NEW_FREEZE
python scripts/compare_stroke_capacity.py run --workspace REAL_WORKSPACE --root INPUT_ROOT --freeze NEW_FREEZE --freeze-sha256 FROZEN_HASH --output REAL_WORKSPACE/.cache/NEW_RUN
```

## Completed comparison

Both prescribed 300-epoch fits completed on November 4, 2026 (UTC), after the
[prospective commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/380#issuecomment-6623926377).
Consumer source `113d1bc10b1b3301bf7ec2d31da7c99e2ad8562a` and execution freeze
`0426864fe4ab5b6d5881d608c432470b47de85a4023019432542c7a582177aca`
precede the single real main Store job `93c20f7db9fd4a56b21ff6f96fdd0faf`.
Its durable status is completed and its original PID/creation-time lifetime is
absent. Windows Python 3.10.5, PyTorch 2.8.0+cu126 in CPU mode and NumPy 2.2.6
use two CPU threads. The baseline reproduces its original epoch and metrics
exactly; no comparison of checkpoint tensor bytes is claimed here.

| Validation measure | Fixed MLP baseline | Linear alternative |
| --- | ---: | ---: |
| Parameters | 56522 | 3720 |
| Selected epoch | 295 | 110 |
| Predeclared selection score | 0.742370 | 0.716688 |
| Eight-group family macro F1 | 0.590437 | 0.566710 |
| Requested six-family macro F1 | 0.567343 | 0.529992 |
| Side balanced recall | 0.894304 | 0.866667 |
| Strict conditional family/side accuracy | 0.574405 | 0.565476 |
| Family answers after abstention | 200 | 270 |
| Side answers after abstention | 662 | 589 |
| Strict conditional joint accuracy after abstention | 0.232143 | 0.294643 |

Both validation denominators remain 672 known family/side rows, including ten
unavailable inputs; neither unavailable rows nor unknowns are reclassified.
There are zero unknown family/side labels in these particular cached development
inputs. All 624 training rows remain, including 16 unavailable inputs. Strict
metrics count unavailable inputs and abstentions as misses.

| Requested family | Validation support | Baseline F1 | Linear F1 |
| --- | ---: | ---: | ---: |
| clear | 3 | 0.222222 | 0.000000 |
| lift | 110 | 0.825112 | 0.848214 |
| net | 151 | 0.536398 | 0.500000 |
| drop | 42 | 0.557377 | 0.605263 |
| smash | 90 | 0.748663 | 0.751381 |
| drive | 118 | 0.514286 | 0.475096 |

The smaller alternative is rejected for advancement under the predeclared
selection rule. Lift, drop and smash F1 improve slightly or moderately, and its
validation abstention joint score is higher, but overall family F1, side recall
and closed-set joint recognition decline; clear F1 falls to zero on three rows.
These mixed outcomes do not justify a changed selection rule, an ensemble or a
parameter sweep. One seed and one validation source cannot determine whether
capacity is generally the problem. This experiment supplies no improved
application model or unseen-match accuracy result.

## Verification and next work

All 67 focused tests and 5,846 full Python tests pass; four optional GPU checks
are skipped. Ruff, formatting, dependencies, repository/LF/JSON/link and
whitespace checks pass. Clean wheel/source checks verify 110 package files,
five frontend files and 58 public manifests, followed by installed HTTP checks.
Generated controls exercise partial labels, strict unavailable denominators,
train-only normalization, missing classes, deterministic CPU/RNG behavior,
selection ties, admission denial, changed code/inputs/deadlines, immutable output
and completion after Store release. Original development seals, all 276 entries
of the earlier reference inventory, frozen consumers and the preserved deprecated
handoff remain unchanged. Private models and validation outputs stay under
`.cache/stroke380-experiment-v1/`; the surrounding `.cache/stroke380-*` files
retain freeze and verification receipts. A clone does not supply these artifacts.

Exact final-head PR/controller/main checks and public delivery remain required;
their owning-issue checkpoints identify final source revisions. Research weights
remain private and no running app is upgraded. Next prioritize better balanced,
source-aligned development supervision and supported shuttle/contact inputs,
then freeze a fresh original-source holdout for any test-informed development.
The consumed tests remain untouched, the complete-rally reference pilot remains
0/2, and full automatic annotation remains unproven.
