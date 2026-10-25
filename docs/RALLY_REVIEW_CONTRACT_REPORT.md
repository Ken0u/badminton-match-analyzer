# Structural contract for contiguous rally review

[Issue #270](https://github.com/Ken0u/badminton-match-analyzer/issues/270)
adds a consumer for the prospective document contract described by
[#262's chronological review plan](RALLY_REVIEW_PLAN_REPORT.md).
The planner specifies source identities, native overlap, gallery context and
own-stream continuity, but does not validate new combined review documents.

The [versioned protocol](../data/manifests/rally_review_contract_v1.json) and
[pure validator](../backend/badminton/rally_review_contract.py) check that
documents follow that structure. This increment uses generated JSON only.
It reads no original scientific packet, gallery, image, label or private plan.
It provides no assessor, image dispatcher, model or scientific acceptance gate.

## Identity, coverage and uncertainty

Each document binds the exact supplied plan bytes, source and native clock,
contract hash, lane, batch ordinal and immediately preceding own-stream document
bytes. Hashing and parsing consume the same captured bytes. Whitespace changes
therefore change raw identity even when JSON values compare equally. A source
bundle requires explicit source selection; its complete supplied bytes remain
bound, and the result records that validation covers one selected source.

The validator reconstructs the planner's structural schedule, including native
frame identity, rational PTS/time base, orientation, gallery navigation, limits,
one-frame overlap and repeated-image costs. Original packet/gallery hashes are
retained as bindings. These checks cannot prove their acquisition history or
replace #262's historical provenance audit.

Every scheduled native frame, including repeated overlap, needs its own ordered
observation. Sparse gallery context supplies no native scene, contact or actor
label. Unknown and not-observed states remain distinct. A valid prefix retains
the complete expected native denominator and explicit missing coverage; an
unavailable plan retains its original reason and denominator with zero documents.

Actors and event mentions remain document-local. Inclusive contact uncertainty,
unsupported family/forehand/backhand, hidden actors, boundary censoring and
unknown evidence survive validation. Explicit predecessor correspondence claims
remain claims: they do not merge contacts, rename actors, average timestamps or
establish identity from equal strings. Positive correspondence requires shared
overlap evidence and consistent one-to-one claims. Missing correspondence stays
unresolved. Stopped play, a last stroke or shuttle absence supplies no exact
ending proof.

`structurally_complete` means the supplied documents cover the selected planned
schedule and satisfy this contract. It does not prove image inspection, assessor
independence, correct judgments, a complete rally reference or annotation accuracy.
Detailed original documents, hashes and diagnostics remain in the private result;
the CLI prints aggregate structural counts only.

## Offline generated-input consumer

```text
python scripts/validate_rally_review.py --plan PLAN.json --documents DOCUMENTS.json --lane independent_a --output PRIVATE_RESULT.json
```

Add `--source SOURCE_ID` for a source bundle. The document manifest is
`{"schema_version":1,"documents":["document-000.json","document-001.json"]}`;
paths are relative to that manifest's directory, in native batch order.
The CLI reads bounded UTF-8 JSON bytes and rejects unsafe paths, symlinks/reparse
points, changed reads, duplicate/nonfinite JSON and conflicting structure.
Validation finishes before an exclusive output is created. Existing outputs
are preserved. No image path is opened, and no application Store, credential
or network client is used. Actual scientific use needs its own granted protocol
and original provenance; this task executes the command on generated fixtures only.

## Verification and limits

All **1,034 focused** and **4,143 full Python tests** pass
(0 focused and 4 full skips). Ruff lint/format, dependency consistency,
repository UTF-8/LF/JSON/local links and whitespace checks pass. Generated
pure tests and actual CLI subprocesses cover native clock/orientation and
image identities, raw-byte chains, exact schedule reconstruction, prefix
and unavailable denominators, document-local variants, explicit correspondence,
strict JSON, path/read limits and preservation of inputs/existing outputs.
The public manifest matches the exact contract and CLI limits.

Final executable, protocol and test bytes remained unchanged during checks.
Recorded test processes and observed worker lifetimes were checked after exit.
An initial core lint-only failure and a failed broad process-observation
attempt remain preserved; no test verdict was inferred from either attempt.
Exact PR/main CI, controller integration and independent public delivery
receipts belong on the owning issue.

Actual new scientific sessions and image bytes are **zero**. The proposed
#262 schedule of 1,209 sessions / 10,576,441,872 image bytes is not executed or
authorized by this contract. Historical unknowns, failed attempts, budgets,
deadlines, labels and acceptance consumers remain unchanged. Complete references
remain **0/2** and all four research eligibility flags remain false. #62, #66,
#67, #71 and correct full-match automatic annotation remain incomplete.
