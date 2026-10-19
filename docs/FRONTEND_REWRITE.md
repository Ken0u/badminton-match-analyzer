# Approved frontend rewrite

The collaborators approved adding a phased React + TypeScript + Vite rewrite to
the roadmap on October 19, 2026. This is planned work, not a claim that the new
frontend is implemented. [Task #93](https://github.com/Ken0u/badminton-match-analyzer/issues/93)
records the roadmap addition. The GitHub milestone is **Review and product**;
issues define task requirements and dispatcher grants define ownership.

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

Prioritize foundation work before substantial new editor features, while backend,
model and research tasks continue under compatible grants. Do not interrupt or
overwrite the active playback-proxy task #69. Its broad backend/test reservation
also prevents conflicting implementation from starting before integration.
Each phase is a bounded increment, not a mandate to finish a whole migration in
one session. Split further when necessary before claiming; never expand a running
specification. Dependencies require verified completion, not just an open PR.

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

Keep the working UI available during migration. Do not switch the default UI or
remove legacy behavior until the full matrix and frozen budgets pass. The final
integration task owns Python package discovery/data, built assets, Docker and CI
wiring, and documents a reversible code-release cutover. It requires a real
non-author human approval because it changes workflow/deployment configuration;
this roadmap approval does not substitute for review of that actual diff.

Each implementation requires an isolated granted worktree, independent review,
current CI and controller integration/main verification. The final phase also
requires successful private candidate receipts. Deployment to a running instance
remains explicit; no automatic application upgrade, data migration, model change,
paid service or research-process restart is authorized here. Shared frontend
contracts remain with the phase owner; subagents may work only on bounded,
explicitly owned files inside that owner's grant.
