# Weak AI CUP hitter-coordinate correspondence

Task [#387](https://github.com/Ken0u/badminton-match-analyzer/issues/387) tests
whether the published hitter/defender image-foot positions support stable weak
associations to the original native pose observations from the
[balanced pilot](AICUP_POSE_PILOT_REPORT.md). Implementation and generated
verification pass. No original correspondence audit has run, and no
improved accuracy result or trained model is claimed.

The fixed [protocol](../data/manifests/aicup_actor_correspondence_protocol_v1.json)
retains all 45 development clips, 24,273 native frames and 784 published rows,
including three censored H0 intervals. The
[official source schema](https://sites.google.com/view/coachai-challenge-2023/tasks/track1)
describes dominant-foot/toe positions in image pixels and court-plane projections
when jumping. An observed ankle or box bottom need not equal either convention.
Landing is a trajectory-end projection, not contact or necessarily rally end.

At both inclusive `[H-1,H]` frames, each coordinate is compared with confident
observed ankles and box-bottom centers. Distances use each candidate's own box
height. Both representations require at least two distinct supported tracks,
unique best distance at most 0.5 and a margin at least 0.25 to the next candidate.
The pair must agree across both frames and representations, use distinct
hitter/defender tracks and remain in one calibrated camera context. Missing
ankles, ties, remote points and conflicting choices remain unresolved; there
is no interpolation or fallback. Family, side, landing, A/B and winner do not
enter geometric matching.

Source CSVs, original complete prepared/native inventories, native integer PTS,
rational clocks, orientation, camera/calibration state and shared Store terminal
completion are checked before observation. A new consumer checks each original
producer dependency seal individually; adding this module cannot retroactively
change the old producer's frozen all-module inventory. Detailed sources and
diagnostics remain private. All rows retain unknown true hitter/scene and false
training eligibility; complete scientific rally references remain **0/2**.

After generated tests and a tested code commit, publish an exact prospective
consumer/input freeze before the single original audit. A permanent exclusive
claim tied to the original completion prevents repeating that audit under a new
output or prospective directory. Deadline and cumulative output limits are four
hours from the fresh grant and 1 GiB. Verification can reproduce the fixed
diagnostics read-only after that deadline. No media decode, model runtime,
inference, image transfer, fitting, model promotion or annotation update occurs.

```text
python scripts/audit_aicup_actor_correspondence.py freeze --workspace REAL_WORKSPACE --prepared ORIGINAL_PREPARATION --native ORIGINAL_NATIVE_OUTPUT --protocol data/manifests/aicup_actor_correspondence_protocol_v1.json --granted-at ORIGINAL_GRANT_UNIX --deadline ORIGINAL_GRANT_PLUS_FOUR_HOURS --output NEW_PRIVATE_FREEZE
python scripts/audit_aicup_actor_correspondence.py audit --prospective NEW_PRIVATE_FREEZE/prospective.json --prospective-sha256 PUBLISHED_HASH --output NEW_PRIVATE_AUDIT
python scripts/audit_aicup_actor_correspondence.py verify --prospective NEW_PRIVATE_FREEZE/prospective.json --prospective-sha256 PUBLISHED_HASH --output NEW_PRIVATE_AUDIT
```

These are reproduction placeholders, not permission to rerun a consumed audit.
Exact PR/main checks and public delivery remain separate completion requirements.

## Generated software verification

The 80 new generated tests and 169 focused tests pass. Controls exercise
label-blind matching, unavailable/ambiguous observations, exact distance and
margin limits, canonical source-row corruption, a held-out archive sentinel,
native clock and shared-job conflicts, exclusive execution, cumulative limits,
source mutation during an audit and reproducible verification after its deadline.
The prospective writer refuses outputs inside original input folders. Missing
temporary-parent failures from the initial test invocation are preserved; a
fresh private temporary directory passes without changing the test semantics.
The full generated regression passes 6,054 tests with four optional skips.
Lint, formatting, dependencies and repository UTF-8/LF/JSON/local-link/whitespace
checks pass. Clean source/wheel/installed-HTTP verification checks 112 package
files, 61 public manifests, five frontend assets, three SPA routes and
authentication; packaging is rechecked when the final report changes.
These generated checks establish software behavior, not badminton accuracy.
