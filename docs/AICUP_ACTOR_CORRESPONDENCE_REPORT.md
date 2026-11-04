# Weak AI CUP hitter-coordinate correspondence

Task [#387](https://github.com/Ken0u/badminton-match-analyzer/issues/387) tests
whether the published hitter/defender image-foot positions support stable weak
associations to the original native pose observations from the
[balanced pilot](AICUP_POSE_PILOT_REPORT.md). The single original audit and read-only verification completed on
November 4, 2026: 652 of 784 rows meet the fixed weak geometric pair rules;
132 remain unresolved. No improved accuracy result or trained model is claimed.

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

The tested code commit and exact prospective consumer/input freeze were
published before the single original audit. A permanent exclusive
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

## Original correspondence results

The [prospective commitment](https://github.com/Ken0u/badminton-match-analyzer/issues/387#issuecomment-6633082819)
binds tested consumer commit `21b26b3342a0f13ea523c443471217855929a786`, protocol
`3956531361944fdeb9b7f55e218ff026e3d1e49a12973c7daa501085d6c7b650`,
90-file consumer dependency inventory
`a772099e98ce46a59b8149a888cb6ad3285ee4977251a8eec12419051f0f52ae`,
and prospective freeze
`ed36c13f0c87fc867ccf0736311c4d8a39c87361a9a2bfd3e0c515d43fd5e030`.
The original preparation/native hashes remain those in the fixed protocol;
no native input, original execution claim, annotation or completed Store job
changed. The original audit exited successfully within its unchanged window;
its permanent execution claim is consumed and must not be rerun.

All 784 references remain: 781 intervals are available, three H0 rows remain
censored, 652 weak pairs meet every fixed rule and 132 remain unresolved.
The 83.16% geometric agreement coverage is **not hitter accuracy**. All 784 true
actors and live-scene labels remain unverified, training-ready rows remain zero,
and complete scientific rally references remain 0/2. No images were transferred,
media decoded, new model inference performed or model fitted/installed.

Read-only CLI verification reproduces all 784 diagnostics and aggregates. A
separate standard-library checker uses original coordinates/native observations
and `hypot`/box-height arithmetic without importing consumer matching helpers;
it independently agrees on all 12,306 candidate distances and all 784 pair
decisions. This checks the fixed calculation, not the correctness of source
labels or actor/scene truth. Completion SHA256 is
`b89e2d5c7e2ca711ccdc36f83dfb9eae673ac8317bf3fe9f06ee60256a48d7fb`;
private diagnostic SHA256 is
`6d01625e726d113ba17a82df59ae976dd628727386ebe2bf094a5fc5bb745856`.
Original audit files occupy 3,473,386 bytes, below the fixed 1 GiB ceiling.
Detailed source rows, positions and labels remain private.

The tables retain every group and denominator. `family:None` is the source's
null stroke-family field on serve rows, not an omitted group or a target family.
Geometric selection never uses those family/side values. All unresolved rows
remain present; zero unresolved rows are converted into negatives or labels.

| Group | References | Available intervals | Weak pairs | Unresolved |
| --- | ---: | ---: | ---: | ---: |
| all | 784 | 781 | 652 | 132 |
| context:bangkok | 132 | 132 | 116 | 16 |
| context:birmingham | 24 | 24 | 21 | 3 |
| context:jakarta_red | 121 | 121 | 95 | 26 |
| context:kualalumpur | 30 | 29 | 25 | 5 |
| context:odense | 353 | 351 | 290 | 63 |
| context:osaka | 35 | 35 | 26 | 9 |
| context:tokyo | 89 | 89 | 79 | 10 |
| family-side:None:backhand | 42 | 39 | 39 | 3 |
| family-side:None:forehand | 3 | 3 | 3 | 0 |
| family-side:clear:backhand | 10 | 10 | 10 | 0 |
| family-side:clear:forehand | 55 | 55 | 53 | 2 |
| family-side:drive:backhand | 12 | 12 | 11 | 1 |
| family-side:drive:forehand | 17 | 17 | 14 | 3 |
| family-side:drop:backhand | 10 | 10 | 9 | 1 |
| family-side:drop:forehand | 60 | 60 | 59 | 1 |
| family-side:lift:backhand | 89 | 89 | 68 | 21 |
| family-side:lift:forehand | 69 | 69 | 49 | 20 |
| family-side:net:backhand | 148 | 148 | 109 | 39 |
| family-side:net:forehand | 131 | 131 | 98 | 33 |
| family-side:other:backhand | 13 | 13 | 12 | 1 |
| family-side:other:forehand | 23 | 23 | 22 | 1 |
| family-side:smash:backhand | 6 | 6 | 6 | 0 |
| family-side:smash:forehand | 96 | 96 | 90 | 6 |
| family:None | 45 | 42 | 42 | 3 |
| family:clear | 65 | 65 | 63 | 2 |
| family:drive | 29 | 29 | 25 | 4 |
| family:drop | 70 | 70 | 68 | 2 |
| family:lift | 158 | 158 | 117 | 41 |
| family:net | 279 | 279 | 207 | 72 |
| family:other | 36 | 36 | 34 | 2 |
| family:smash | 102 | 102 | 96 | 6 |
| fold:train | 431 | 430 | 362 | 69 |
| fold:validation | 353 | 351 | 290 | 63 |
| side:backhand | 330 | 327 | 264 | 66 |
| side:forehand | 454 | 454 | 388 | 66 |

Failure reasons overlap. Across all rows, hitter resolution is unavailable in
118 and defender resolution in 51. Hitter box-bottom distance exceeds the
fixed limit in 97 rows; hitter ankle distance does so in 37. Ankle ranking has
fewer than two supported tracks in 32 rows, box-bottom ranking in 31. One
defender has a representation/endpoint disagreement. These are diagnostic
reasons, not independently established detection or identity errors; the foot
projection convention can differ from an observed ankle or box bottom.

Each distance cell below is mean normalized distance (number of comparisons).
It includes **all supported candidate tracks and both endpoints**, including
distant nonmatching players; it is neither the accepted-match distance nor an
accuracy score. Normalization uses each candidate's own positive box height.
Original private aggregates also retain minima/maxima and complete reasons;
the public CLI deterministically reproduces them from the unchanged inputs.

| Group | Hitter ankle | Hitter box bottom | Defender ankle | Defender box bottom |
| --- | ---: | ---: | ---: | ---: |
| all | 0.861367 (3,076) | 0.940322 (3,077) | 0.844880 (3,076) | 0.910688 (3,077) |
| context:bangkok | 0.861226 (527) | 0.945425 (527) | 0.860774 (527) | 0.923327 (527) |
| context:birmingham | 0.722722 (94) | 0.784874 (94) | 0.675817 (94) | 0.720128 (94) |
| context:jakarta_red | 0.948278 (476) | 1.006240 (476) | 0.962515 (476) | 1.015116 (476) |
| context:kualalumpur | 0.704785 (114) | 0.791518 (114) | 0.688640 (114) | 0.726216 (114) |
| context:odense | 0.892420 (1,370) | 0.977773 (1,370) | 0.869319 (1,370) | 0.947349 (1,370) |
| context:osaka | 0.782305 (139) | 0.880851 (140) | 0.758094 (139) | 0.871135 (140) |
| context:tokyo | 0.743489 (356) | 0.812591 (356) | 0.698577 (356) | 0.736207 (356) |
| family-side:None:backhand | 0.710090 (156) | 0.728075 (156) | 0.780330 (156) | 0.767840 (156) |
| family-side:None:forehand | 0.720943 (12) | 0.698573 (12) | 0.702547 (12) | 0.706334 (12) |
| family-side:clear:backhand | 0.973938 (40) | 1.031204 (40) | 0.873703 (40) | 0.964746 (40) |
| family-side:clear:forehand | 0.948897 (221) | 0.996100 (221) | 0.799645 (221) | 0.879568 (221) |
| family-side:drive:backhand | 0.914749 (48) | 0.972858 (48) | 0.831751 (48) | 0.901153 (48) |
| family-side:drive:forehand | 1.043931 (68) | 1.141185 (68) | 0.888443 (68) | 1.018616 (68) |
| family-side:drop:backhand | 1.243863 (40) | 1.286207 (40) | 0.958514 (40) | 1.078873 (40) |
| family-side:drop:forehand | 0.990732 (239) | 1.044017 (239) | 0.861467 (239) | 0.945257 (239) |
| family-side:lift:backhand | 0.672560 (343) | 0.753279 (343) | 0.683404 (343) | 0.725157 (343) |
| family-side:lift:forehand | 0.620423 (269) | 0.732393 (270) | 0.705089 (269) | 0.739577 (270) |
| family-side:net:backhand | 0.837144 (575) | 0.961422 (575) | 0.926340 (575) | 1.001197 (575) |
| family-side:net:forehand | 0.836478 (514) | 0.951709 (514) | 0.989552 (514) | 1.051459 (514) |
| family-side:other:backhand | 0.718292 (51) | 0.768528 (51) | 0.739898 (51) | 0.769949 (51) |
| family-side:other:forehand | 0.685210 (92) | 0.770763 (92) | 0.792905 (92) | 0.827087 (92) |
| family-side:smash:backhand | 0.844083 (24) | 0.866783 (24) | 0.707374 (24) | 0.801350 (24) |
| family-side:smash:forehand | 1.175059 (384) | 1.186799 (384) | 0.831875 (384) | 0.938061 (384) |
| family:None | 0.710865 (168) | 0.725968 (168) | 0.774774 (168) | 0.763447 (168) |
| family:clear | 0.952735 (261) | 1.001480 (261) | 0.810995 (261) | 0.892622 (261) |
| family:drive | 0.990476 (116) | 1.071533 (116) | 0.864984 (116) | 0.970011 (116) |
| family:drop | 1.027024 (279) | 1.078740 (279) | 0.875381 (279) | 0.964413 (279) |
| family:lift | 0.649643 (612) | 0.744080 (613) | 0.692936 (612) | 0.731508 (613) |
| family:net | 0.836829 (1,089) | 0.956838 (1,089) | 0.956176 (1,089) | 1.024920 (1,089) |
| family:other | 0.697008 (143) | 0.769966 (143) | 0.774000 (143) | 0.806709 (143) |
| family:smash | 1.155589 (408) | 1.167975 (408) | 0.824552 (408) | 0.930019 (408) |
| fold:train | 0.836430 (1,706) | 0.910265 (1,707) | 0.825255 (1,706) | 0.881264 (1,707) |
| fold:validation | 0.892420 (1,370) | 0.977773 (1,370) | 0.869319 (1,370) | 0.947349 (1,370) |
| side:backhand | 0.792741 (1,277) | 0.880316 (1,277) | 0.827494 (1,277) | 0.883085 (1,277) |
| side:forehand | 0.910081 (1,799) | 0.982893 (1,800) | 0.857222 (1,799) | 0.930270 (1,800) |

This development diagnostic supports proposing a separately bounded temporal
pose experiment with explicitly weak actor associations and all missing-input
cases retained. It does not authorize training, certify scenes/contacts or
establish original-match independence. Sparse cells (including six backhand
smash rows), selection bias and unresolved media/pretraining overlaps still
limit any future learning/evaluation claim. Freeze a new protocol and validation
criteria before fitting; do not tune these gates to increase coverage.

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
