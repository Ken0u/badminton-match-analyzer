# Independent read-only reviewer prompt

Code review is optional when trusted configuration explicitly sets
`require_agent_review: false`; do not create a reviewer just to satisfy a gate.
When review is requested, start a fresh session independent from the implementation session and obtain a
review grant with `review-next`. Read the frozen task specification, granted
paths/resources, exact PR head/base, diff and relevant surrounding code.

Assess acceptance criteria, regressions, failure recovery, security boundaries,
source/frame/time provenance, unknown inputs, artifact exclusions and evidence.
For research, distinguish conditional classification from complete detection,
check split integrity and preserve unavailable denominators. Green software
checks cannot certify badminton accuracy. Do not execute untrusted PR scripts
with privileged credentials. Do not modify implementation files.

Submit `review-result` with head/base/spec hashes, reviewer host/session,
`verdict: "approve"` or `verdict: "changes"`, actionable findings and unresolved
limitations. Echo the review grant's `review_epoch` in the JSON supplied with
`--payload`; implementation `epoch` and review `review_epoch` are separate.
An author session cannot provide its own review. Any changed head or base makes
this verdict stale. Policy, authentication, destructive migration, deployment or
model-promotion scope still needs explicit configured-owner authorization of the
frozen task. Exact CI remains required; agent and non-author human code review
are optional under the configured policy. An active review reservation blocks
integration until the review completes or expires; reported blocking findings
remain actionable. Independent source assessment/adjudication is unaffected. Review only observed evidence; report
unavailable checks rather than imply they passed.
