# Completion-observer incident diagnosis

Investigated October 28, 2026 under
[issue #329](https://github.com/Ken0u/badminton-match-analyzer/issues/329).
The historical cause remains **unresolved**. Available immutable inputs and
retrieved terminal metadata pass the original validation. Controlled offline
examples reproduce several possible error paths, but the failed observer did
not retain its per-poll API responses or an identifying stack trace. None of
those examples establishes which path failed historically. No runtime repair
is justified by this evidence alone.

This diagnosis changes documentation only. It does not retry a historical run,
wake a controller, accept CI evidence, alter coordination or change publishing
policy. Task #327 remains separately completed and delivered. No scientific
images, labels, predictions, models or training inputs were accessed; complete
independent rally references remain **0/2** and match annotation accuracy is
unproven.

## Observed chronology

Times are UTC on October 27, 2026. Run and job timestamps establish chronology;
they do not reconstruct the JSON returned during a particular observer poll.

| Time | Retained evidence |
| --- | --- |
| 00:43:55 | Immutable coordination `832301e88cabd77d3ba803b4ffaa57f01bc64815` binds task #327, epoch 1, to merged source `aa8e53b33ab462bc5316065e0287a064a6f0fa81` in `verifying_main`. |
| 00:44:14 | The [failed observer](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40428267444) enters its observation step with that exact binding. |
| 00:47:59; 00:51:37 | Two later immutable coordination snapshots retain the identical observation binding and `verifying_main` status. |
| 00:52:01 | The gate job finishes successfully in [exact main CI](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40428251332). All 12 jobs succeeded; run metadata is updated at 00:52:02. |
| 00:53:40 | The retrieved reconcile-job record for [controller run 40428088241](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40428088241) starts. This is evidence of a controller job overlapping the observer failure, not a captured status-list response. |
| 00:53:42.513751 | The observer emits `ValueError`, `outcome: unknown`, `verification_accepted: false`, then exits 1. Its job finishes at 00:53:45. |
| 00:55:04 | Coordination records task #327 as `done`; its original main-stage observation binding no longer applies. |
| 00:55:14-00:57:45 | [Public publishing](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40429416923) succeeds. |
| 00:55:22-00:58:13 | The separate [delivery observer](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/40429430412) succeeds. |

Fresh read-only coordination inspection confirms task #327 is `done` with
`delivery_pending: false`. Its independent delivery audit is recorded in the
[original completion checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/327#issuecomment-6431098404).
That existing audit was not rerun or represented as newly performed here.
The main CI and failed observer both report attempt 1. Their preserved failure
and successful delivery remain distinct records.

## Immutable inputs and validation

The diagnosis freezes the original source's `scripts/devops` modules,
observation entry point and automation configuration from Git, rather than
reconstructing their contents from current behavior. The observation entry
point, observer, coordinator and queue bytes are unchanged between that source
and the diagnosis base `65cc7450eb017e2380e3a3dcc1f8084ded72aa40`.

| Evidence | SHA-256 |
| --- | --- |
| Original preserved masked step log | `e40d8241a011eada40f5684359844164ad11b4349465bb72dc5b0a257bc68948` |
| Original preserved run/job metadata | `0d81cd489a6138ac1441aa60842d484dffd67dbc2be98f5fda96cabd414d698f` |
| Original observer source bytes | `1aa1ee13a9657e0931327ae059a3eb4340d883fd6b8729d37d9b55ff48fbe3a8` |
| Original observation entry point | `749044464b62cc57ff62395b9d4e714d9dced5dcd662008c8b645dc7d95aa30e` |
| Private offline replay receipt | `af141882aeeb7d71c268165ed0afc42955285403a587de46a3d9d2e3e36d9b66` |

The original immutable task passes `identity()`, including its specification,
submission, ownership and integration-journal bindings. The 00:47:59 snapshot
`5da3aa493476996b2afcf05276514fcd54d77709` and 00:51:37 snapshot
`ce84bedda40352354929dec03050b970de118619` produce the same binding. The 00:55:04
snapshot `9e1874815a24988a4e8dbbb3bbb728e85fdec98b` has advanced normally.

The retrieved exact CI run passes the frozen `validate_target()`. Retrieved PR
#328 metadata still matches its submission head/base and merge source. These
checks establish consistency of the inputs available now; they do not prove
that every historical API observation was complete or consistent.

## Error-path analysis and offline replay

The entry point suppresses exception messages and payloads and logs only the
exception class. `ValueError` can therefore represent several distinct paths,
including subclasses such as `JSONDecodeError`.

| Path | What available evidence establishes |
| --- | --- |
| Input/configuration, original task identity, immutable-state ancestry, initial workflow metadata | Original task/configuration and frozen input values validate. Static rejection would ordinarily occur before sustained polling. The nine-minute interval alone does not prove which instructions executed or exclude delayed transport. |
| Current coordination/PR/main revalidation | A normal task transition returns `stale`; it is not a `ValueError`. Decoding malformed transport/state data or an invalid main revision can still raise before that result. Original per-poll responses are unavailable. |
| Workflow listings | Incomplete, inconsistent, duplicate or over-bound listings intentionally raise. The historical lists were not retained; today's complete lists cannot establish their earlier contents. |
| Selected target validation | Invalid run identity/state, changed attempt or changed terminal observations raise. Today's terminal target is valid and reports attempt 1; an actual completed rerun is not demonstrated. |
| Controller lifetime inspection | Wrong workflow/path/repository/status metadata or an incomplete listing raises instead of authorizing a wake. A valid active controller causes waiting, not an exception. |
| Transport request restrictions and decoding | Requests outside the fixed allowlist raise before transport. JSON/base64 decoding can also raise `ValueError` subclasses. No disallowed call or malformed historical response is demonstrated. |

Seven controlled scenarios run against the frozen original observer with a
fake clock and an offline transport that refuses every mutation. They are
counterexamples and behavior checks, **not recovered historical API responses**.

| Controlled scenario | Result |
| --- | --- |
| Valid terminal CI with an indefinitely active controller | `timeout_unknown` after 5,400 simulated seconds; no mutation. |
| Valid terminal CI, active controller, then normal task advance | `stale` after one simulated poll; no mutation. |
| Controller listing declares one run but returns none | `ValueError: Incomplete workflow listing`; no mutation. |
| Target changes from active to completed with no conclusion | Run-state `ValueError`; no mutation. |
| Selected run attempt changes from 1 to 2 | Attempt-change `ValueError`; no mutation. |
| Current-state observation becomes malformed JSON | `JSONDecodeError`; no mutation. |
| Valid terminal CI with an idle controller | Reaches the dispatch boundary; the offline transport refuses it. No workflow is dispatched. |

The ordinary 90-minute observation timeout produces a different result from
the preserved nine-minute `ValueError`; it does not explain that log. Equally,
an overlapping valid controller and a normal task advance do not reproduce the
failure. The possible malformed/listing/attempt cases demonstrate why the
exception class cannot distinguish causes. They do not establish an API race,
a controller defect or the correctness of any proposed retry.

The listing distinction can be reproduced without network or credentials from
the repository root using its project Python:

```python
import sys
sys.path.insert(0, "scripts")
from devops.completion_observer import runs_since

class Offline:
    def __init__(self, count):
        self.count = count

    def repo(self, path):
        assert path.startswith("actions/workflows/agent-queue.yml/runs?")
        return {"total_count": self.count, "workflow_runs": []}

assert runs_since(Offline(0), "agent-queue.yml", status="in_progress") == []
try:
    runs_since(Offline(1), "agent-queue.yml", status="in_progress")
except ValueError as exc:
    assert str(exc) == "Incomplete workflow listing"
else:
    raise AssertionError("An incomplete listing must not authorize a wake")
```

The fuller local replay receipt and read-only response inventory stay in ignored
storage. They are not supplied by cloning. Public run links, immutable commit
identifiers, frozen source and the small offline example above allow the
reported checks to be repeated without publishing raw coordination documents.

## Verification and next prerequisite

The existing observer suite passes **72 tests** on the project Python 3.10
environment. The seven offline scenarios make zero network requests and zero
actual mutations. Evidence acquisition uses **33 GET requests**, retaining about
22 MiB before final report/check receipts, within the 120-request/128-MiB task
allowance. The original log and metadata remain unchanged.

Repository/link/UTF-8-LF and whitespace checks, exact PR CI, controller merging,
merged-main verification and complete public delivery remain required for this
documentation change. Their final evidence belongs on issue #329.

A future telemetry repair should have its own owner-authorized frozen task
because it changes protected automation. Its useful outcome would be bounded,
allowlisted stage/reason codes that distinguish these paths while preserving
redaction, exact-source validation, unknown outcomes and mutation restrictions.
Do not log exception bodies, response payloads or credentials; do not relax
listing/identity checks or add retries on the strength of this diagnosis.
Original poll payloads or a safely identified recurrence would be needed to
establish the historical cause. This documentation task preserves that open
uncertainty rather than claiming a repaired observer.
