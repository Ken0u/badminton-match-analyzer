# Canonical stroke target integrity

Task [#382](https://github.com/Ken0u/badminton-match-analyzer/issues/382)
repairs a generated-data failure in the portable stroke learner's input audit.
The old audit pinned original CSV bytes and ordered row identities, but checked
target arrays against cached metadata. Changing both cached representations and
resealing them could therefore turn source clear/forehand into drive/backhand,
or fabricate unknown targets, without changing the source CSV. Three new
regressions fail against the original code; the six independently changed
array-only/metadata-only controls already reject the disagreement.

This probe does not establish historical contamination. The executed capacity
study used an immutable precommitted manifest, which remains unchanged.

## Repair

The audit now derives ordered identities, families and mechanics directly from
the pinned original `ball_type` and `backhand` values. It uses the reviewed
`doubles_data.TYPES` aliases and the doubles normalizer's 0/1 flag convention.
Short/long service map to the separate serve class, combined push/kill and wrist
smash remain other, and unmapped families or missing/invalid mechanics remain
unknown. There is no half-smash class. Both target arrays and metadata must agree
with these canonical weak targets; unavailable descriptors retain their rows.
Missing columns, unsupported cached labels and duplicate selected source stroke
identities reject the input. Header-only source sets require the same columns.

The existing optimization, seed, source groups, normalization, class weighting,
selection, thresholds and strict unknown/unavailable denominator semantics are
unchanged. Training additionally seals `doubles_data.py`, alongside the already
sealed CSV parser in `datasets.py`; code changes prevent model publication.
Generated tests simulate these mutations without editing either source module.

## Historical protocol compatibility

The executed [capacity v1 protocol](../data/manifests/stroke_capacity_protocol_v1.json),
its source/hash commitment and [negative result](STROKE_CAPACITY_REPORT.md) remain
unchanged. Exact v1 reproduction uses its original consumer revision
`113d1bc10b1b3301bf7ec2d31da7c99e2ad8562a`, whose learner hash is
`745de9212ef0ecf41d47b9ad96426c46741b330e462783baecdcc5c46c700932`.

Current code uses the explicit [capacity v2 protocol](../data/manifests/stroke_capacity_protocol_v2.json).
It binds the stronger learner and exact CSV parser/mapping source hashes while
retaining the v1 fitting and comparison parameters. The CLI still requires an
explicit protocol: use `--protocol data/manifests/stroke_capacity_protocol_v2.json`
with current code. It rejects v1 rather than silently reinterpreting its executed
record. No v2 scientific fit or result is claimed, and this task permits zero
real fits. Both public protocol files are included in the source distribution.

## Verification and original-development conformity

All 130 focused generated-data tests pass. They cover source/cache changes,
independent and joint resealing, valid family/service aliases, fabricated
unknowns, partial unknown truth, invalid side flags, absent columns, exact row
identity/order, strict unavailable denominators, parser/mapping mutations,
unchanged fitting semantics and historical/current protocol compatibility.
The original three failing cases and their logs are preserved privately.

Before any original-development conformity audit, commit the tested consumer
and prospectively publish its code/mapping hashes, the unchanged development
manifest and original reference-inventory hashes. Then perform one read-only
audit of the 134 original development clips, retaining 624/672 rows and
608/662 available inputs. An unexpected real mismatch stops work for separate
scope; no rows may be relabeled or dropped. This audit has not yet executed.

No images, media, native inference, real fitting, held-out predictions or model
promotion are part of this repair. Labels, features, weights and detailed
receipts remain private ignored artifacts, absent from a clone. S2Doubles
redistribution rights and upstream perception overlap remain unresolved.
Source conformity is agreement with published weak supervision, not independent
badminton truth. Complete-rally references remain 0/2 and full automatic
annotation accuracy remains unproven.
