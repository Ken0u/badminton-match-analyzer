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

Execution and verification are pending. Record aggregate results here after the
prospective commitment and the two prescribed fits. A worse result is retained;
there is no parameter sweep or test-based tuning. A new original-source holdout
and complete event/identity evaluation remain necessary. The complete-rally
reference pilot remains 0/2, and full automatic annotation is unproven.
