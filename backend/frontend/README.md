# Frontend foundation

Phase [#95](https://github.com/Ken0u/badminton-match-analyzer/issues/95) introduces
an opt-in development workspace. FastAPI still serves the existing legacy UI.
The sandbox uses synthetic local samples; it is not a match library or annotation
editor. Software checks do not establish badminton annotation accuracy.

## Reproduce

Use the repository Node version and the root lockfile. From the repository root:

```sh
npm ci
npm run frontend:typecheck
npm run frontend:test
npm run frontend:build
npm run frontend:contract:check
npm run test:frontend-foundation
```

For development, `npm run dev --workspace @badminton/frontend` starts an opt-in
loopback Vite server. `npm run build --workspace @badminton/frontend` produces
static HTML/CSS/JS in `backend/frontend/dist/`; Node is a build/development tool.
This workspace does not add a production Node server. The Vite configuration
uses its built-in automatic JSX transform without an additional React plugin.
TypeScript 5.9.3 meets openapi-typescript 7.13.0's declared TypeScript 5 peer range.
Dependencies are exact and the workspace is resolved by the root package lock;
do not create another lockfile here.

## Contract ownership and limitations

`src/api/generated/openapi.json` is the actual `create_app().openapi()` document,
serialized deterministically with sorted keys and LF. `schema.ts` is generated
by the pinned openapi-typescript version. Both files are reviewed source inputs,
not hand-edited declarations. Run `npm run frontend:contract:generate` after an
intentional backend contract change, inspect the diff, then run the check.
The check recreates both files in memory and fails on any byte difference.
It requires the repository's locked Python review environment; set
`FRONTEND_CONTRACT_PYTHON` to its executable if it is outside `.venv/`.

The embedded exporter in `scripts/contract.mjs` sets `BADMINTON_ROOT`, `BADMINTON_DATA_DIR` and
`BADMINTON_EXPORT_DIR` before any backend/config import. Every invocation uses a
fresh temporary catalog/export directory, resolves platform temporary path
aliases, and removes its own temporary files. It neither starts app lifespan/
HTTP/inference nor reads an existing catalog. Backend imports still require the
declared Python review dependencies. The exporter stays embedded so this phase
adds no Python namespace package to existing distributions. Packaging and default
UI cutover remain scoped to phase 98. Do not point this tool at live data.

The current backend provides request schemas, parameters and validation errors,
but its JSON success responses generally have no declared response model.
Generated response types therefore remain `unknown`; this is a real contract
limitation. A feature must validate/narrow unknown responses before using them.
Generated types are compile-time checks, not runtime payload validation; they do
not capture every Pydantic validator or prove a server response conforms.
Schema-less response types must not be replaced with optimistic hand-written
server records. Backend response-model work needs its own granted scope.

`createApiClient().request(method, pathTemplate, options)` types known operations,
path/query parameters, JSON bodies and multipart upload bodies from that contract.
It forwards caller `AbortSignal` and same-origin credentials, checks cancellation
before sending and after body reading, encodes path/query values, and preserves
structured JSON errors or raw non-JSON errors in `ApiError`. `status` and
`isConflict` expose HTTP 409 without assuming every 409 is a revision conflict
(source/admission conflicts also exist). Network failures and caller aborts stay
distinct from HTTP errors. An invalid JSON success throws `ApiProtocolError`.
This request method is for JSON operations; browser media/download URLs are a
separate feature concern. The client does not retry mutations or resolve/merge
revision conflicts. A failed or aborted mutation may already have reached the
server: explicitly reload/reconcile its revision before retrying. Never treat
aborting a save as proof it did not commit.

## Module boundaries

| Module                   | Owner and responsibility                                                                                                                  |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `src/api/`               | Shared HTTP transport and generated contract only; no UI/drafts.                                                                          |
| `src/state/selection.ts` | Selection epochs and per-resource latest-read lanes; abort plus ownership fences late success/error, including transports ignoring abort. |
| `src/state/server.ts`    | Validated-by-feature server records and job responses in separate keyed collections. Unknown values stay unknown here.                    |
| `src/state/draft.ts`     | One unsaved document, its server revision, edit generation and save ticket. No polling or playback.                                       |
| `src/state/playback.ts`  | Imperative high-frequency video/canvas snapshots; exact source identity supplied by a verified mapping, never computed from nominal fps.  |
| `src/ui/`                | Native keyboard controls, labels/help/errors and live feedback. No API knowledge.                                                         |
| `src/App.tsx`            | Synthetic foundation demonstration; no production feature migration.                                                                      |
| Future feature modules   | Phase 96 owns library/import/jobs; phase 97 owns review editor, overlays, source-clock mapping and parity.                                |

Before a selection change, require `drafts.canLeave()`. If dirty, ask the user to
save or explicitly discard. Do not select first and then ask: selection aborts
read lanes. Saving blocks navigation/discard but allows edits. `beginSave()`
captures the exact draft/revision; pass the ticket snapshot to the API.
`completeSave()` must receive the validated persisted value and revision from
the server. It advances the saved base without clearing newer local edits.
`failSave()` retains the draft and error, including a 409. Do not feed a late
read/poll result into `drafts.open()` over a dirty or saving document. A save
completion requires both the exact pending ticket and current selection epoch.
Do not bypass navigation guards or reuse tickets across stores.

Use one `createLatestTask(scope)` lane per independently requested resource;
starting a read invalidates that lane's earlier completion. Commit through the
current owner. Job polling has a distinct lane and collection from annotations.
Unsubscribe/abort lanes when their owner unmounts. Snapshot collections and draft
values are treated as immutable by callers; use store methods for updates.

React panels may subscribe to server/draft stores with `useSyncExternalStore`.
Video frame callbacks and canvas drawing subscribe imperatively to playback and
clean up on unmount. Do not subscribe the app root or every panel to every tick.
The sandbox's 600-tick probe demonstrates notification/render isolation; it does
not measure actual decode, paint latency, source mapping or editor performance.
Those claims still require the frozen [baseline](../../docs/FRONTEND_BASELINE.md).

Controls use native button/input behavior, explicit labels, linked help/error
text, visible keyboard focus, disabled/busy semantics and live status/alert
feedback. Save/discard restore focus to the note field; error retry restores its
trigger. Later dialogs/features own initial focus, dismissal, keyboard shortcuts
and return focus. This foundation is not a WCAG or screen-reader certification.

## Verification and generated assets

`npm run frontend:test` compiles modules to ignored `.test-build/`, runs focused
Node tests and removes that directory. Compile-only probes reject missing paths,
unsupported methods, invalid request enums and missing mutation bodies.
Unit probes cover structured/non-JSON errors, status/conflict preservation,
request-body/revision forwarding, cancellation, late success/error, selection ABA,
separate records/jobs, edits during save, failed/stale mutation preservation and
imperative subscriber cleanup. The browser harness exercises the compiled
sandbox, native focus/keyboard behavior and actual backend HTTP contracts.

`dist/`, `.test-build/`, caches, node_modules, catalogs and browser receipts remain
ignored. Do not copy built output into `backend/badminton/static/` in this phase.
Phase 98 owns production asset packaging, Python package discovery exclusions,
CI/container wiring, the reversible default cutover and legacy retirement after
full parity evidence. No running application is restarted/upgraded here.
