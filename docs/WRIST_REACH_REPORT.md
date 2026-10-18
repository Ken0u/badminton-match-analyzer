# Contact proximity contradicted by observed wrists

October 18, 2026. Release 0.16.1 corrects a false contact proposal near a
player's feet. It does not install the experimental learned models.

## Observed failure and change

The corrected 119-frame doubles development clip described in the
[camera-context report](EARLY_CAMERA_CUT_REPORT.md) produced proposals at 76 and
103. Source inspection shows the shuttle below/behind the near player around
100-108, with his racket well away and an apparent floor encounter around
101-104. The trajectory changes near the player's box, which previously
overrode the distant wrist observations. The
[source review](../data/manifests/terminal_contact_review.json) freezes that
negative interval. The baseline proposal was already known before review;
this is development evidence, not a blinded or held-out accuracy test.

For a fully observed seven-frame trajectory, the proximity fallback now excludes
a possible hitter when repeated observations of **both** wrists contradict
racket reach. Each wrist needs at least three finite observations with confidence
at least 0.3, observations before and after the candidate, one within a source
step, and no observation gap over 0.1 seconds. Every observed wrist distance must
exceed the larger of 0.10 image diagonal and 0.6 player-box diagonal.

This is a conservative image-space heuristic, not a physical racket measurement.
Missing, ambiguous, sparse or one-arm evidence leaves the fallback available.
Another plausible nearby player is still considered. A nearby stationary wrist
also retains the proposal: movement is not required for a visible contact.
Short-gap and subframe proposals keep their existing motion/pose requirements.
All new pose evidence stays inside the existing validated trajectory context;
no additional frames or fabricated shuttle points enter a proposal.

The method is version 4 and exports its guard settings in the proposal recipe.
Existing artifacts remain immutable; request new contact suggestions to apply
the change. Suggestions still require explicit inspection and saving.

## Verification and limits

Cached native inputs produce the following results. These are compatibility
checks; most proposals have not been adjudicated and counts are not accuracy.

| Development case | Before | After |
| --- | ---: | ---: |
| Reviewed floor-bounce case | 2 (76, 103) | 1 (76) |
| Public first training rally | 6 | 6 |
| Original singles first court view | 12 | 12 |
| Original doubles first court view | 20 | 20 |
| Original singles partial pilot | 6 | 6 |
| Original doubles partial pilot | 9 | 9 |

Every retained candidate matches the prototype output, including its evidence
and timing. An isolated API check reuses the real CUDA artifacts, emits only
76 with context 74-81, and preserves both isolated and main saved annotations.
The surviving proposal is not established as correct by this regression check.
Source review remains assistant first pass pending human adjudication, and
exact ending, line calls and whole-rally contact precision remain unverified.

Generated regressions cover repeated distant wrists, missing/low-confidence/
nonfinite/ambiguous pose, sparse temporal evidence, bounded context, another
possible hitter, stationary nearby wrists, image scaling and close player scale.
The local suite covers 518 passing standard tests and four unchanged optional
GPU skips. A new test initially treated the exclusive context end as inclusive;
correcting that assertion leaves all 91 contact/profile/interval tests passing.
Ruff, source formatting, dependency checks and browser formatting also pass.
Local verification records are gitignored:
`.cache/wrist-reach-native-verification.json`,
`.cache/wrist-reach-api-verification.json`, and
`.cache/wrist-guard-frozen-before-heldout.json`.

The feature-preparation job banner now describes analysis features; its previous
stroke-side-only wording was misleading for shared contact/stroke preparation.
The independent long-running corpus worker and its immutable runtime snapshot
are unchanged by this release.
