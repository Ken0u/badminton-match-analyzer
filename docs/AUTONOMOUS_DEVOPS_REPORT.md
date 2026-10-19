# Autonomous development workflow implementation

October 18, 2026. This increment adds shared planning/ownership and delivery
infrastructure. It does not improve or certify badminton annotation accuracy.

## Implemented behavior

Local subscription-authenticated Codex sessions execute work on Mac/Windows.
GitHub Issues hold frozen task specs; the dispatcher alone writes an orphan
coordination branch. Atomic grants reserve paths/resources, fence stale epochs,
and keep same-host implementation and independent review sessions separate.
Observation mode grants no execution. Trusted comments are JSON data, never shell
commands; reconciliation tolerates retries, malformed requests and lost wakeups.

Routine integration requires exact-head/base review, current CI, granted paths
and protected main. Sensitive entry points need non-author human approval.
Inference changes require source/model/code-bound native evidence with explicit
limitations. Journalled merge attempts survive uncertain API responses. A main
failure creates a bounded repair lane while normal work pauses; verified repairs
resume work and retain original failure evidence. Publishing remains pending
until the complete private candidate workflow succeeds, with bounded retries.

Pinned uv profiles cover review, CPU and supported CUDA platforms. CI retains
Linux 3.10/3.12, browser and review/CPU containers and adds native Mac/Windows,
source receipts, wheel/sdist/installed-byte checks, repository validation and a
stable aggregate gate. Container bases and Actions are pinned. Running app state,
source videos, existing Windows environments and research workers were untouched.

## Historical backfill applied

At baseline `cc1a37b`, all 29 merged PRs received completed retrospective issues;
one completed report index preserves links to committed evidence. Twelve roadmap
issues remain proposed; existing PR #30 has a separate recovery-only record.
There are 43 managed backfill issues plus queue control #74. Research completion
is qualified separately from model promotion and full-match correctness.

GitHub temporarily returned HTTP 502 during backfill; retry reused existing
markers, and read-back verified 30 closed records, no open historical increment,
and 14 open backlog/control records before the bootstrap implementation issue.
The bootstrap implementation itself is tracked separately.

## Verification and rollout limits

Final local Python 3.10 and clean locked Python 3.12 runs each passed 877 tests
with 11 skips. Boundary tests cover repair (including pilot mode), publishing,
recovery and privileged entry points. Hosted exact-head results are recorded
on the PR; local tests do not establish Windows or container execution.
Wheel/sdist and fresh installed CLI checks passed with all 70 app package files
byte-identical. No inference/model weights or production labels were changed.

Independent review found and drove fixes for cross-host code recovery, explicit
failed-main repair, publishing completion, malformed request IDs, closed-issue
eligibility, Windows command resolution and privileged script classification.
Adapter tests exercise crash-before-merge and lost responses as well as failure
and cancellation outcomes. Source-clock/model accuracy evidence remains separate.

Activation is deliberately gated: the implementation account has write but not
admin access, current credentials lack Project scope, and GitHub reports that
private rulesets require an eligible paid plan. No Project, subscription or
protection change is claimed. Follow [owner setup](OWNER_SETUP.md), then the
human-reviewed two-host pilot, before enabling active integration. Until then,
no automatic production deployment or application/model upgrade occurs.
