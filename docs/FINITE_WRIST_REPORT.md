# Invalid wrist observations and contact proximity

October 18, 2026. Release 0.17.1 fixes a reproduced numerical bug in contact
suggestions. It does not install an experimental learned model.

The generated regression has a genuine shuttle direction change, a player box
far from it, and a confident wrist with a NaN coordinate. The previous wrist
distance could become NaN; comparing that distance with the proximity limit
then failed to reject the player. A false proposal appeared at frame 12 despite
the distant box. Infinite confidence could also supply invalid near-wrist
evidence. This is a controlled failure, not a claim that a reviewed source video
produced those malformed keypoints.

The shared wrist check now requires numeric, finite x/y/confidence before
applying the existing confidence threshold. Observed-contact proximity and the
repeated-wrist guard retain their 0.3 threshold; moving-wrist gap/profile evidence
retains 0.5. Invalid observations count as missing. A nearby valid box can still
provide the existing observed-contact fallback, and a valid other wrist is
still considered. Source observations are not repaired or written back.

Contact method/recipe provenance advances to version 5. Existing saved runs stay
immutable; request new suggestions to use the correction.

Ten new regressions cover NaN/infinite/missing/nonnumeric coordinates, invalid
confidence, short-gap evidence and a valid other arm. The full local run passed
547 standard tests with four unchanged optional GPU skips; the final additional
infinite-confidence regression also passes, for 548 tests covered. Ruff and
formatting pass.

All complete candidate dictionaries remain unchanged in six finite-input cached
native controls: the reviewed floor-bounce development case, public training
excerpt, both original first court views and both partial pilots. The source
bounce remains excluded. An isolated API check reuses the real CUDA inputs,
emits only frame 76 with context [74,81), and leaves isolated/main annotations
unchanged. No GPU rerun is needed for this numerical correction. These controls
verify compatibility and the known negative; most contacts are unadjudicated
and their counts do not establish full accuracy.

Local evidence: `.cache/finite-wrist-native-verification.json` and
`.cache/finite-wrist-api-verification.json`. Whole-match recognition and the
independent 75-rally head evaluation remain unfinished as recorded in the
[observed-context report](OBSERVED_STROKE_CONTEXT_REPORT.md).
