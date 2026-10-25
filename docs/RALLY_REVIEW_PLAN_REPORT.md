# Prospective native rally review plan

Prepared October 25, 2026 for [issue #262](https://github.com/Ken0u/badminton-match-analyzer/issues/262).

The [protocol](../data/manifests/rally_review_plan_v1.json) prepares a deterministic
chronological review schedule from the original native packets and temporal
galleries. It adds no source assessment, image dispatch or annotation truth.
The [joined evidence](RALLY_EVIDENCE_JOIN_REPORT.md), all 1,532 native frames,
53 sparse samples, original conflicts and unknowns remain preserved. Complete
references remain **0/2** and all four research eligibility flags remain false.

Each native frame receives navigation context from the gallery sheet containing
the nearest sampled source time, with lower native ordinal breaking ties.
This association supplies no scene, visibility, actor or contact label for an
unsampled frame. Native source hashes, clocks, PTS/time bases, orientation,
image identities and unavailable inputs remain explicit.

Chronological batches include exactly one preceding native frame after the
first batch. Every relevant gallery sheet is repeated and charged in full.
The proposed limits are 9 MiB and 20 distinct images per session, including
native and gallery inputs. An infeasible minimum batch produces an unavailable
plan with its entire original denominator, without omitting frames, resizing
images or increasing limits. Gallery input order does not change packing.

Two independent prospective lanes and a separately named source-adjudication
lane retain the same exhaustive schedule. These are planned lanes, without new
sessions or votes. Independent manifests exclude historical semantic labels,
descriptions, event intervals and other-stream outputs. A versioned future
output contract requires whole-window context, physical-contact correspondence
through overlaps, document-local actor evidence, inclusive uncertainty for
contacts/serves/endings, unknown family/side and missing evidence. It supplies
no alternative acceptance criterion or scientific execution authority.

## Original-host execution

The [metadata command](../scripts/plan_rally_review.py) supports `freeze`, `run`
and read-only `audit`. It requires the original private artifacts and a current
committed original-host grant. A clone cannot replace those inputs with generated
fixtures. Freeze follows final generated/full checks and a clean consumer commit.
A prospective owning-issue seal binds the exact context, protocol and consumers.
The immutable metadata interval is four hours from the fresh grant, additionally
bounded by its lease; no earlier scientific clock or image allowance is renewed.

```text
python scripts/plan_rally_review.py freeze --root ORIGINAL_ROOT --output ORIGINAL_ROOT/.cache/rally262-plan-v1 --grant CURRENT_COMMITTED_GRANT
python scripts/plan_rally_review.py run --root ORIGINAL_ROOT --output ORIGINAL_ROOT/.cache/rally262-plan-v1 --timestamp PROSPECTIVE_ISSUE_SEAL
python scripts/plan_rally_review.py audit --root ORIGINAL_ROOT --output ORIGINAL_ROOT/.cache/rally262-plan-v1 --timestamp PROSPECTIVE_ISSUE_SEAL
```

Credentials are cleared and original root/data are pinned before application
imports. The real shared Store admits the one metadata plan. The original tested
#250 read-only completed audit runs in a separate credential-free process before
packet/gallery metadata is parsed. Historical writing preparation, assessment,
aggregation and sealing helpers are never invoked. Original input bytes and
consumer revisions remain bound by hashes. Outputs are exclusive and private;
an attempted or failed run prevents implicit repetition. A timeout gives no
permission to signal or restart a process.

The post-exit audit verifies Store, terminal, artifact, immutable-time and
process-lifetime evidence, reruns only the historical read-only audit and
reconstructs the new metadata schedule. It checks exact no-gap native coverage,
overlap memberships and repeated-byte costs without repeating any scientific
preparation or assessment. Task limits are 512 MiB new outputs and 8 GiB
cumulative retained scientific outputs, with at most three diagnosed repair
rounds. New scientific sessions and outbound image bytes are both zero.

## Verification and result

Generated verification passes **451 focused and 3,525 full Python tests**,
with four optional skips, plus Ruff lint/format, dependency consistency,
repository UTF-8/LF/JSON/local links and whitespace checks. Final source timing
and recorded terminal verification lifetimes were checked. The first core and
parent fixture failures and lint failures remain preserved. Task-owned inspection
found and corrected a separate hash/parse-read race and loss of a subprocess
receipt after access-denied observation; generated regressions cover both.

The clean tested consumer `e59840e3bc9e5040ef6e07a583f17c59067e5f9e` was committed before the
[prospective owning-issue seal](https://github.com/Ken0u/badminton-match-analyzer/issues/262#issuecomment-6393060021). Exactly one original-host
metadata plan completed under the real shared Store in about
10 seconds. The frozen #250 read-only
audit passed before packet/gallery metadata was parsed. A separate post-exit
audit revalidated unchanged inputs, Store/terminal/artifact evidence and the
original wrapper/launcher/worker chain, finding all
8 recorded outer execution lifetimes
absent. It reconstructed the exact new schedule and costs after another
read-only historical audit; no scientific preparation or assessment was repeated.

| Source | Plan | Native frames | Samples | Sessions per lane | Native bytes once | Overlap bytes per lane | Gallery bytes per lane | Total bytes per lane |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Doubles | planned | 541 | 19 | 136 | 554667137 | 151796412 | 469847247 | 1176310796 |
| Singles | planned | 991 | 34 | 267 | 1112863758 | 307069175 | 929236895 | 2349169828 |

Across three prospective exhaustive lanes, the schedule status is
**planned**, with **1,209 proposed sessions** and
**10,576,441,872 proposed image bytes**. Native byte totals count
each original image once; overlap and gallery costs include every repeated
membership in a lane. A session counts every distinct native/gallery image
against both caps. These are prospective transport costs, without confirmation
that a future transport or assessor can execute them or resolve the evidence.
All 1,532 native frames and 53 samples remain, with no omitted native frame.
The 1,479 unsampled frames receive navigation context, without new sparse labels.

Actual new scientific sessions and dispatched image bytes are **both zero**.
Historical payload accounting, original 1,020 execution identities/256 targets,
unknowns, conflicting event intervals and scientific acceptance remain unchanged.
Complete references remain **0/2** and all four eligibility flags remain false.
No old allowance or runtime is renewed by these prospective costs.

Aggregate SHA256 is `2d9712684072798c17a74aa0845e5157286da4ecbd2e5748802dca07de1bd8db`; private plan SHA256 is
`870272e7206f4957373a70ed077df4067dff7763663ecdb8f14dc97f42459c34`. Only code, protocol, aggregate counts and hashes are
published; images, labels, process/session paths and the per-frame schedule stay
private. Exact PR/main CI, normal controller integration and complete independent
public delivery remain pending at this report checkpoint; their eventual
receipts belong on the owning issue.

Any actual future image assessment requires a separate frozen task, specifically
authorized payload/destination and fresh execution budget. This planner does
not complete #62, #66, #67 or #71, change scientific acceptance, promote a model
or establish complete automatic badminton annotation accuracy.
