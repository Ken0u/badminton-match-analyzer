# Integrated project progress

Updated October 18, 2026. This summary describes committed capabilities and the
current DevOps increment; it is not a live process registry.

## Product state

The app supports local uploads/public YouTube import, exact-source-frame review,
revisions and JSON/CSV exports, player/pose and shuttle tracking, court geometry,
camera/scene corrections, experimental event suggestions and resumable source
processing. Singles recognition is experimental; doubles recognition and reliable
persistent identities remain open. Full automatic annotation accuracy is unproven.

Merged increments through PR #29 are the historical baseline. The direct RGB
learner completed its held-out evaluation but was rejected for app promotion
(contact F1 0.159; complete tuple F1 0.028). See `PROJECT_PLAN.md` and committed
reports for methods, denominators and limitations, not just software test counts.

## Autonomous DevOps increment

Implementation is [PR #76](https://github.com/Ken0u/badminton-match-analyzer/pull/76)
on `codex/autonomous-devops`. The queue uses durable GitHub
requests, atomic path/resource grants, independent agent review and serial
integration; local Mac/Windows workers execute work. Automation starts in
**observation** mode. CI, reproducible profiles and private candidates are part
of this increment. The implementation report is [docs/AUTONOMOUS_DEVOPS_REPORT.md](docs/AUTONOMOUS_DEVOPS_REPORT.md); final checks are recorded on the bootstrap PR before activation.

Local Python 3.10 and clean locked Python 3.12 each pass 880 tests with 11 skips.
Package/installed-byte checks, lint, lock and dependency checks pass. Independent
review found no remaining blocking code findings. Hosted native/container checks
and the owner setup/pilot remain required; this workflow is not active yet.

All 29 merged PRs and a report index are backfilled as 30 closed evidence records. Twelve roadmap tasks, PR #30 recovery, and [queue control #74](https://github.com/Ken0u/badminton-match-analyzer/issues/74) remain open. Historical PRs are completed implementation/research issues,
with links to their original evidence. Completed research does not mean its model
was accepted. PR #30 (broadcast supervision importer) was open at inventory time;
do not create competing work. Recheck GitHub before continuing it.

## Outstanding setup and work

- Owner `Ken0u` must configure eligible private branch protections and the Project
  automation credential before active integration. `dootz1` has write, not admin.
- Project sync is idempotent; issue backfill works independently of Project auth.
- Run the documented two-task pilot before changing observation to active.
- Continue source-aligned supervision, perception, complete contact/rally/identity
  evaluation and doubles recognition under the approved roadmap.

## Historical workstation evidence

The full previous handoff is preserved byte-for-byte at
[`docs/history/PROGRESS-2026-10-18.md`](docs/history/PROGRESS-2026-10-18.md).
It describes Windows-only artifacts and five previously observed workers. Their
current liveness is unknown from this Mac. Do not restart them because this clone
lacks their datasets, weights or caches. Verify original PID/creation/cwd/command,
Store ownership and durable artifacts on that host first.

Task-specific checkpoints now live on their GitHub issues. Update this summary
through a bounded documentation task after meaningful integrated milestones.
