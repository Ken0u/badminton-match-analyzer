# Contact generation: native input identity

Issue [#323](https://github.com/Ken0u/badminton-match-analyzer/issues/323),
continuing [#321](https://github.com/Ken0u/badminton-match-analyzer/issues/321),
repairs visual contact generation accepting perception artifacts whose frame
times or declared source hashes disagree with the registered video. This is
input-integrity work; full-match badminton annotation accuracy remains unproven.

## Reproduced behavior

The baseline is `4fa37eb004e24eaa3a75d305a87fb651bb0fade7`. An actual admitted
API job used generated trajectories over a generated 25-frame H.264 video.
Independent decoding verified all native timestamps and 640-by-360 dimensions.
The 4,900-byte video SHA256 is
`e6944e85d2a87d2e15b414ed9ce72ba0acb22e15299be6d60243df987102be90`.
No research footage, labels, weights or model inference was used.

For both singles and doubles, shifting the shuttle timestamps by 0.4 seconds
published a completed proposal at frame 12 / 0.88 seconds, although native frame
12 is at 0.48 seconds. Shifting only player timestamps or supplying a conflicting
player/shuttle source hash also completed. All ten inconsistent cases and two
stable controls retained their original input artifacts and saved annotations.

The evaluator's existing source/clock checks and optional acoustic alignment
checks act later or on different evidence. They did not prevent these visual
artifacts from being generated. A separate pipeline regression also showed
that a completed contact artifact could remain when a later rally stage rejected
the same inconsistent inputs.

## Validation and compatibility

`validate_contact_inputs` checks the full native timestamp map and original
perception records before proposal generation. It rejects invalid frame counts,
nonfinite/negative/unordered native times, wrong run video/stage identities,
invalid declared ranges, malformed or conflicting supplied SHA256 values, and
nonintegral, duplicate, unordered or out-of-range perception frame indices.
Each supplied row time must agree with its native frame within the existing
20-microsecond absolute tolerance. Boolean values are not accepted as indices
or timestamps. Rejected evidence is not repaired, retimed, deduplicated or
discarded through scene filtering.

The API validates the original runs before applying scene context or admitting
a job. Invalid input returns HTTP 422 without creating a job or contact artifact.
The whole-match caller passes its native timestamp map into the shared producer.
New application artifacts bind the video hash, record
`source_timestamps_validated`, and distinguish `matched`, `unavailable` and
`not_requested` input source-hash states. Missing legacy hashes remain unavailable;
an explicitly null or malformed hash is an error.

Valid sparse player observations, different valid input ranges, optional
shuttle-only proposals, VFR timestamps and legacy artifacts without source
hashes remain supported. Existing camera, scene, calibration, source-gap and
default-off audio rules remain in force. Original candidate IDs, coordinates,
timing, hints, scores and uncertainty are preserved for unchanged valid inputs.

Historical three-argument pure research calls remain available without a native
map; they make no native-validation claim. The two application callers supply
that map explicitly. No historical artifact, annotation, model, threshold or
eligibility flag is rewritten. Validation is not atomic source snapshot isolation
and does not prove that the upstream perception observation is correct.

## Verification and remaining delivery

The generated-video rerun rejects all ten inconsistent API cases before
publication; both stable controls retain the exact original contact at frame
12 / 0.48 seconds. Source bytes, perception artifacts and annotations remain
unchanged. The actual video hash matches the baseline reproduction.

The new 102-case API suite initially recorded 94 expected failures and eight
passes against original production bytes: 80 invalid cases were admitted and
14 valid controls lacked the new provenance fields. Six pipeline regressions
also failed against the correct baseline. An earlier pipeline test attempt
used the original checkout's editable import and attempted to change an existing
fixture's registered mode; that diagnostic is preserved separately and is not
used as baseline repair evidence.

The first repaired focused run passed 317 tests. Eight older audio API cases
still expected admission of malformed visual inputs. The controller accepted a
paths-only reservation for that existing test file; all eight now require HTTP
422, no new job/artifact and unchanged inputs/annotations. Direct optional-audio
exclusion tests remain unchanged. The expanded final focused suite passes
**399 tests**, including direct audio and pipeline coverage. An initial scope
request that also edited acceptance prose was rejected; the corrected request
preserved task semantics and the original runtime deadline.

Full local verification passes **5,121 tests**, with four opt-in GPU/checkpoint
tests skipped. Ruff, formatting, dependency consistency, repository text/link
checks and diff checks pass on unchanged executable bytes. Scoped UTF-8/LF,
JSON/local-link and frontend/package provenance checks also pass.
Initial PR #322 failed the hosted browser processing check: the synthetic
contact callback still accepted three arguments while the pipeline supplied
native timestamps as a fourth. A genuine independent review confirmed this
blocking defect, inspected all eight original scoped files and passed 20
targeted API cases. The failed run `40315690500`, its generated artifact and
completed cleanup receipt remain preserved.

The original 14:06:18 UTC deadline on October 26 expired during an approval-service
outage. Task #321 was released with original-host terminal proof; PR #322 was
closed unmerged with its branch, exact source and review retained. A separately
frozen nine-path grant under #323 carries the actual finding and cumulative
output/repair limits. The generated callback now accepts and checks the native
clock without weakening production validation or browser assertions.

The original full/focused Python results and generated native API evidence are
reused only after exact covered production/test/input hashes and baseline agree.
The only executable difference from the reviewed predecessor is the synthetic
browser callback. New browser verification passes **19 production checks,
eight library checks and 13 export groups**, including the formerly failing
processing path. All three fixture cleanup receipts are complete; the recorded
runner and fixture lifetimes are independently absent. The original shared Store
bytes and existing local edit remain unchanged. Final required repository checks
are recorded with source hashes on the owning issue. Exact PR/main integration
and public artifact verification remain pending at this revision; final delivery
evidence belongs on the owning issue.

Private generated receipts and failed logs remain under ignored `.cache/` on
the original workstation. A clone does not contain them. Software integrity and
generated parity checks do not establish contacts, identities or stroke accuracy
on real matches. Complete scientific rally references remain **0/2**; no new
scientific assessment, training or model promotion occurred.
