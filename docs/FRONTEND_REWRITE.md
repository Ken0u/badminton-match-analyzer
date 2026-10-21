# Approved frontend rewrite

The collaborators approved the phased React + TypeScript + Vite rewrite on
October 19, 2026, recorded by
[task #93](https://github.com/Ken0u/badminton-match-analyzer/issues/93).
Phases #94–#98 are integrated and delivered as of October 20, 2026. React is the
default packaged UI, served by FastAPI in the existing application/container.
The GitHub milestone is **Review and product**; issues define task requirements
and dispatcher grants define ownership.

## Verified delivery

[Phase #98 / PR #148](https://github.com/Ken0u/badminton-match-analyzer/pull/148)
merged as `4ebd2f025da117ba617d5b092d5a9cc25d53eabc`. The controller recovered
the external merge using the preserved original grant, exact source/base,
independent review and identical reviewed/merged trees. The
[owning checkpoint](https://github.com/Ken0u/badminton-match-analyzer/issues/98#issuecomment-6293143852)
records the audit and complete delivery acknowledgement.

- [Exact merged-main CI](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39462227527)
  passed all 12 jobs, including 18 production, 8 library and 13 media-export
  browser groups, installed-package checks, native Mac/Windows checks and
  authenticated review/CPU container checks. Frozen parity and performance
  evidence remains attached to the phase checkpoints.
- [Candidate delivery](https://github.com/Ken0u/badminton-match-analyzer/actions/runs/39469465774)
  succeeded for the package and both public images. Independent verification
  matched all 75 application source/runtime files in the wheel and source archive
  to that merged commit, verified the dependency-lock hash and anonymously
  checked both immutable image manifests. The controller recorded
  `delivery_pending=false`.
- [Export controls #138 / PR #147](https://github.com/Ken0u/badminton-match-analyzer/pull/147)
  are included in this default delivery. They expose the reviewed plain/annotated
  export service with saved-revision submission, source-bound job status,
  eligibility reasons and verified manifest/MP4 downloads. The preceding backend
  increments and their receipts remain linked from
  [the export milestone](https://github.com/Ken0u/badminton-match-analyzer/issues/70).

These receipts establish software parity and artifact delivery. They do not
establish full automatic badminton annotation accuracy or unseen-match product
validation, which remains separate work under
[task #71](https://github.com/Ken0u/badminton-match-analyzer/issues/71).
No running application was upgraded by this delivery.

## Target architecture

- React components own the library, import forms, job controls, review panels,
  dialogs and timeline interaction. TypeScript describes UI state and the API
  contract; Vite builds static assets.
- Source lives in `backend/frontend/`, within the queue's existing permitted
  source roots. Build output is packaged under `backend/badminton/static/`.
  The delivery phase must explicitly exclude frontend source/build tooling from
  Python package discovery and include only intended runtime assets.
- A typed client uses the existing FastAPI HTTP API. Check its contract against
  reproducibly generated OpenAPI. Handle errors, cancellation and late responses.
- Keep server records/jobs, unsaved annotation drafts, and ephemeral playback
  state separate. Frequent frame/overlay updates must not cause broad component
  rerenders. Preserve the source-time mapping rather than deriving annotation
  frames from a browser's nominal frame rate.
- FastAPI serves the production UI in the existing single application/container.
  Node is a frontend build/development dependency; no additional runtime frontend
  server or distributed service is introduced by this rewrite. The existing
  runtime Node requirement for YouTube import remains separate.

## Phases and dependencies

| Phase | Owning issue | Dependency | Outcome |
| --- | --- | --- | --- |
| 1. Behavior and performance baseline | [#94](https://github.com/Ken0u/badminton-match-analyzer/issues/94) | Roadmap #93 and integrated playback proxies [#69](https://github.com/Ken0u/badminton-match-analyzer/issues/69) | Freeze generated-media fixtures, supported workflow matrix, timing tolerances and performance budgets. |
| 2. Typed foundation | [#95](https://github.com/Ken0u/badminton-match-analyzer/issues/95) | #94 | React/TypeScript/Vite workspace, typed API client, state boundaries, accessible controls and build/typecheck scripts. |
| 3. Library, imports and jobs | [#96](https://github.com/Ken0u/badminton-match-analyzer/issues/96) | #95 | Migrate library selection, upload/YouTube import, processing controls and recovery states. |
| 4. Review editor | [#97](https://github.com/Ken0u/badminton-match-analyzer/issues/97) | #96 | Migrate playback, timeline, overlays and all existing review/evaluation interactions with parity evidence. |
| 5. Delivery and legacy retirement | [#98](https://github.com/Ken0u/badminton-match-analyzer/issues/98) | #97 | Package/install/container/CI verification, default UI cutover and removal of replaced assets. |

The table preserves the completed migration order; playback-proxy task #69 and
all five phase dependencies are now satisfied. Future frontend increments still
require bounded specifications and compatible dispatcher grants. Respect current
backend, model and research reservations; never expand a running specification
without a grant. Dependencies require verified completion, not just an open PR.

## Acceptance criteria

1. Preserve the complete supported workflow: uploads/public YouTube import,
   selection, playback, seeking, camera/scene/court editing, player mappings,
   shuttle/contact/rally/stroke review, evaluation, save/reload and JSON/CSV export.
   Map each interaction to a deterministic browser check in the baseline matrix.
2. Preserve native source PTS, frame identity, orientation, proxy mapping, camera
   boundaries, scene exclusions and calibration expiry. Cover variable-frame-rate
   and oriented generated media, exact-frame navigation and overlay alignment.
3. Preserve saved annotation revisions, unknown/ineligible labels and original
   predictions. Suggestions require explicit review/acceptance. Test concurrent
   revision conflicts, unsaved edits, video switches and delayed network results;
   drafts or late responses must not silently overwrite another video's state.
4. Test job progress, errors, interruption, pause and resume without starting
   competing inference. Generated fixtures require no private datasets or weights.
5. Freeze seek-to-overlay latency, playback responsiveness, timeline interaction
   measurements and permitted regression budgets before migration. Record the
   host/browser, fixtures, method and timing tolerance; evaluate the replacement
   on the same setup. No unsupported performance claim follows from unit tests.
6. Verify keyboard navigation, labels, focus restoration and accessible feedback
   for loading, errors and unsaved changes. Use reusable controls where useful;
   keep extra dependencies justified by a concrete UI need.
7. Pass strict TypeScript checking, production build, relevant existing and new
   browser checks, package asset checks outside the checkout, and authenticated
   review/CPU container checks. Retain native Mac and Windows development support.

Software parity and green checks do not establish badminton annotation accuracy.
The rewrite changes the interface and maintainability, not model promotion or
scientific evaluation criteria.

## Integration and rollout boundaries

The default cutover and retirement of replaced assets followed the full parity
matrix and frozen performance budgets. Phase #98 owns Python package discovery,
built assets, Docker and CI wiring; [deployment documentation](DEPLOYMENT.md)
describes the reversible code-release rollback without changing annotations.
Future sensitive workflow/deployment scope requires explicit configured-owner
authorization of the frozen task, as specified by [AGENTS.md](../AGENTS.md) and
the [collaboration protocol](COLLABORATION.md). Exact CI remains required; agent
and non-author human code reviews are optional when `require_agent_review` is
explicitly false in trusted configuration.
Original issue specifications and historical reviews remain audit evidence.

Each implementation requires an isolated granted worktree, current CI and
controller integration/main verification. Requested code reviews use genuine
fresh sessions and exact-revision grants. Completion also requires
successful package and both image receipts matching the approved candidate
visibility policy, currently public. Deployment to a running instance
remains explicit; no automatic application upgrade, data migration, model change,
paid service or research-process restart is authorized here. Shared frontend
contracts remain with the phase owner; subagents may work only on bounded,
explicitly owned files inside that owner's grant.
