# Independent read-only reviewer prompt

Start a fresh session independent from the implementation session and obtain a
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
frozen task. A non-author human PR review is optional; fresh independent agent
review and exact CI remain required. Review only observed evidence; report
unavailable checks rather than imply they passed.
