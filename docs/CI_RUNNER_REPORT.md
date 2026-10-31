# Standard macOS native runner migration

Owner-authorized [#355](https://github.com/Ken0u/badminton-match-analyzer/issues/355),
October 30, 2026 (Toronto). Frozen specification:
`e73dc74c457fe176869f3eabbbc9c3a8e497c7537bdaf5b580b2bde7b182e67c`.

The native CI matrix now uses standard `macos-15` alongside `windows-2022`.
The workflow change is exactly one label replacement. Native test commands,
locked environments, Python versions, frontend checks, action commit pins,
timeouts, permissions, gate dependencies and controller integration are retained.
No larger runner, paid service, new dependency or retry-policy change is added.

## Failure evidence and migration choice

PR #354's original CI run `41145428910` cancelled native macOS job
`124369351515` before runner allocation or any step. GitHub's annotation
identifies the scheduled macOS 14 image brownout, not a test failure.
All ten other verification jobs passed; the required gate failed because the
native job did not succeed. Original logs and annotations are preserved privately.

GitHub's [official retirement notice](https://github.com/actions/runner-images/issues/13518)
lists the October 30 14:00 UTC to October 31 00:00 UTC brownout and November 2
retirement. The [official image inventory](https://github.com/actions/runner-images#available-images)
lists standard `macos-15` as Arm64, matching standard `macos-14`'s architecture.
The explicit supported label avoids another implicit `latest` migration.
Hosted image contents still evolve; a label is not an immutable VM image.

The owner separately approved one unsuccessful-job retry of #354's unchanged
head `8f92d123bd248c74dc4b01981997877655db214a` after the brownout ended.
That single retry passed; the controller merged #354 at
`036bdc8f4aab0869d7e44b8f04d779990e09d530`, verified all twelve main checks,
and completed public delivery before this task's fresh grant. The authorization
and original cancelled attempt remain preserved; no further retry follows.

GitHub reissued job IDs for the second attempt, including reused successful
records. An initial ID-only audit assertion failed. Comparing preserved
execution timestamps, step records and runner metadata confirms the ten
successful executions were reused; only macOS and the gate have new execution
records. Both the initial assertion and its correction are retained. No retry
network mutation was repeated.

## Verification and limits

Generated structural regressions require standard macOS 15 plus existing
Windows coverage, exact-source checkout, the locked environment, complete
native/frontend commands and the existing timeout. They also execute the
workflow's actual gate script against every required dependency with failure,
cancellation and skip results, and verify the complete successful case.
Before the workflow edit, one matrix regression fails and 27 preservation/gate
controls pass. This baseline distinguishes the needed label update from the
already intact verification policy.

Final workflow validation compares all source bytes against the granted baseline
after reversing the single label substitution. Local syntax, focused protocol
and full-suite results, exact submitted/main revisions, actual hosted macOS 15
native results and public delivery receipts belong on the owning issue. A local
Windows check alone does not establish macOS 15 runtime compatibility; the
hosted native job must pass with the existing full suite.

Private source-host receipts are under `.cache/scene353-ci-failure-v1/`,
`.cache/scene353-authorized-retry-terminal-v1.json`,
`.cache/scene353-completion-v1.json` and `.cache/scene355-before-v1/`.
A clone supplies reproducible code and this aggregate report, not those local
logs or the original media, models and annotations.

This task sends zero scientific images, starts no assessment, inference or
training, and changes no application truth or installed weights. It does not
reclaim expired source-assessment runtimes or establish improved badminton
annotation accuracy. Complete independent rally references remain 0/2.
