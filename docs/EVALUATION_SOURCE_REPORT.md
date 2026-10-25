# Source hashes in saved prediction evaluation

[Issue #260](https://github.com/Ken0u/badminton-match-analyzer/issues/260)
repairs source provenance validation in contact and shuttle evaluation. A
completed run's video ID and stage do not establish that its prediction bytes
describe the registered video's current source hash.

## Reproduction and correction

Generated registered runs reproduce the defect on main
`1fa657a0069e3cfae7963eca04827fbee631b17b`. Both contact and shuttle evaluation
return HTTP 200 and F1 1.0 when the prediction artifact explicitly contains a
different source SHA256. The CLI also exits successfully with the same score.
Explicit null hashes are accepted too. Matching and missing legacy hashes form
separate controls; all eight cases preserve saved artifact and annotation bytes.
No real video, scientific label, image assessment or model inference is involved.

The shared evaluator entry point now validates an explicitly supplied
`video_sha256` before reading predictions or computing metrics. It must be a
64-character hexadecimal SHA256 string matching the registered video hash.
Conflicting, null, empty, nonstring and malformed values raise an actionable
validation error. Hexadecimal case is immaterial. The API returns HTTP 422;
the CLI exits with an error and writes no new report.

Legacy artifacts without the key remain supported. Contact and shuttle reports
add `prediction_source_hash_status`, with `matched` for validated equal hashes
and `unavailable` when the artifact supplies no hash. The existing top-level
`video_sha256` still identifies the registered source; it does not by itself
verify a legacy prediction artifact. Missing metadata is never inserted into
the artifact. Equality verifies declared provenance, not independent integrity
of every prediction or its physical correctness.

Matching and legacy cases retain existing metrics, frame/reference denominators,
source times, camera exclusions, unknown labels and missing-output behavior.
Recognition and rally evaluation retain their existing stricter source-hash
requirements. No inference, saved annotations, predictions, frontend contract,
model, dependency or workflow changes are included.

## Verification and limits

Generated tests cover both stages, valid uppercase hashes, legacy omission,
conflicting and malformed explicit values, wrong video/stage, rejection before
prediction parsing with no labels, and unchanged input bytes. API/CLI cases
exercise actual registered completed artifacts and verify rejected requests
produce no score or new report. All **328 focused tests** pass, including the
existing contact-camera, recognition and rally evaluation regressions.

The initial focused attempt passed 308 tests but its 20 new API/CLI cases failed
fixture setup because generated shots lacked the schema's required explicit
unknown family/side. Those fields were added to the fixture; no schema or
validation rule was relaxed. The failed attempt and process receipts are kept.
The first full-check attempt stopped at formatting before pytest; formatting was
corrected and the final unchanged-code run passes **3,393 Python tests**, with
four optional skips. Ruff lint/format, dependency consistency, repository
UTF-8/LF/JSON/local links and whitespace checks pass. Final executable/test files
predate this run; recorded verification process lifetimes are terminal. Exact
PR/main CI and public delivery evidence belong on the owning issue after
controller integration.

Complete scientific references remain **0/2** and all four research eligibility
flags remain false. This repair prevents misleading source-bound measurements;
green software checks do not establish full-match badminton annotation accuracy.
