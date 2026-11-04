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

Before the CI fixture repair, all 130 focused generated-data tests passed. They cover source/cache changes,
independent and joint resealing, valid family/service aliases, fabricated
unknowns, partial unknown truth, invalid side flags, absent columns, exact row
identity/order, strict unavailable denominators, parser/mapping mutations,
unchanged fitting semantics and historical/current protocol compatibility.
The original three failing cases and their logs are preserved privately.
The full Python suite passes 5,909 tests with four optional GPU skips and one
existing Starlette warning; lint, format, dependencies, repository UTF-8/LF/JSON/
links and whitespace checks pass on unchanged sources.

The single read-only original-development audit completed November 4, 2026
(UTC), after [prospective publication](https://github.com/Ken0u/badminton-match-analyzer/issues/382#issuecomment-6624811146).
Tested consumer `ed8e2cd83ea8ef0de6418e08f8ab4456e403fe50` and private freeze
`177fc901928e36b334146a0782e55a4be19595ef9b49ee34d09d29e4f3249485`
precede that audit. The unchanged development manifest is
`0bea5f55f6ba402ca7665bb0d2d4bb8eaa903d0593ebc76870cf8901035bd059`;
the separately sealed original reference inventory is
`ec02275493b278a7d482ddbf9acd820ff1bc46d2d4da2b599fd1eadc358aaed2`.

| Development group | Clips | All source rows | Available inputs | Family mismatches | Side mismatches |
| --- | ---: | ---: | ---: | ---: | ---: |
| Training, Match001 | 67 | 624 | 608 | 0 | 0 |
| Validation, Match002 | 67 | 672 | 662 | 0 | 0 |

All 1,296 family targets and 1,296 side targets agree in both cached arrays and
metadata records. These particular original development inputs contain zero
unknown family or side labels; generated partial-unknown cases remain covered
separately. All 26 unavailable-input rows remain, with no source/cache edits or
denominator changes. All 276 original development seals and all 276 entries of
the earlier reference inventory match before and after the audit. Preservation
checks hash original artifacts without deserializing weights or prediction
values. Original consumer sources, historical protocols/results and deprecated
handoff edits remain unchanged. There was no mismatch requiring separate scope.

Private freeze, publication, process/check logs and aggregate audit receipts live
under `.cache/stroke382-*`; the conformity receipt is
`.cache/stroke382-conformity-v1/verification.json`. Exact final-head PR/main
checks, controller integration and public delivery remain required, with their
source revisions recorded on the owning issue. This repair does not rerun or
alter the negative capacity result or upgrade a running application model.

No images, media, native inference, real fitting, held-out predictions or model
promotion are part of this repair. Labels, features, weights and detailed
receipts remain private ignored artifacts, absent from a clone. S2Doubles
redistribution rights and upstream perception overlap remain unresolved.
Source conformity is agreement with published weak supervision, not independent
badminton truth. Complete-rally references remain 0/2 and full automatic
annotation accuracy remains unproven.

## Preserved PR failure and generated fixture repair

Original [PR #383](https://github.com/Ken0u/badminton-match-analyzer/pull/383)
at `2e87797fb9aa8f42e03784042a124bed0c1e7ba4` failed exact-head
[CI run 41790046630](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/41790046630):
ten verification jobs passed; macOS recorded one generated rally-review CLI
fixture failure and the final gate failed consequentially. The test retained
verified startup, normal `wait()` completion and an intermediate psutil access
denial. Its logs, XML and terminal observer receipt remain private preserved
evidence; no CI job was retried. Failed XML ZIP SHA-256 is
`de16b916e9c3effbd5d197247965c8eab4d1a659edac82e99ff9c4c36b3a0702`.

A generated probe demonstrates that an access denial after the owned process
exits falsely fails this fixture. It does not prove the unobserved historical
timing. The fixture now records a terminal observation only if startup and the
root identity were verified and the original direct `Popen` handle proves that
root exited. Live or unverified denial remains an error; root exit does not
resolve a descendant's denied observation. No signal authority, timeout, test
gate, workflow or retry policy changes. Deterministic generated regressions
exercise terminal metadata/child-list races, live-denial failures and denied
descendants after root exit.

The failed PR remains closed without merge, with its branch and both original
commits retained. Documented original-host terminal release and a fresh epoch-2
grant preserve all scientific results and the original fixed deadline; a
committed path-only expansion reserves this existing generated test file.
The sole real conformity audit stays consumed and is not rerun. The scientific
consumer source and fitting behavior remain unchanged. Fresh changed-source
PR/main verification and public delivery remain required for the repaired PR.

Fresh epoch-2 verification passes 174 focused and 5,914 full Python tests, with
four optional GPU skips and the existing Starlette warning. Required lint,
format, dependency, repository/UTF-8/LF/JSON/link and whitespace checks pass.
Clean source/wheel/installed-HTTP checks verify 110 package files, five frontend
files and 59 public manifests. Final documentation is checked again before
publication. All prior failed receipts remain separate. Only this report and
the generated CLI fixture differ from the already audited scientific consumer;
the original development audit is not repeated and no model is trained.
