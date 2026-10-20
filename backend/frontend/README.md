# Frontend preview workspace

Phase [#95](https://github.com/Ken0u/badminton-match-analyzer/issues/95) introduces
an opt-in development workspace. FastAPI still serves the existing legacy UI.
The root sandbox uses synthetic local samples. Phase [#96](https://github.com/Ken0u/badminton-match-analyzer/issues/96) adds an opt-in match library at `/library`; it is not an annotation editor. Software checks do not establish badminton annotation accuracy.

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
| `src/library/`           | Phase 96 library/import/jobs runtime validation, selection controller, upload transport and React screen.                                 |
| Future feature modules   | Phase 97 owns review editor, overlays, source-clock mapping and parity.                                                                   |

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
required queries, unsupported methods, invalid request enums and missing mutation bodies.
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

## Library preview (phase 96)

The root route preserves the phase-95 foundation browser contract; `/library`
opens the real library/import/job preview. Static hosts must serve `index.html`
for `/library` and `/library/` and assets at `/assets/`. The default FastAPI UI
and its source files are unchanged. No production package/cutover is included.
The foundation page links to the preview, and the preview links back.

Point only an owned development fixture at the Vite loopback proxy:

```sh
BADMINTON_FRONTEND_BACKEND_URL=http://127.0.0.1:8000/ npm run dev --workspace @badminton/frontend
```

The optional variable accepts a loopback HTTP(S) backend origin only. `/api`
requests use the same-origin proxy and existing authentication; the browser
client never forwards session credentials to a configured remote origin. The
legacy editor link points to the actual backend root (this origin, or
`http://127.0.0.1:8000/` when unset). It does not promise a selected-video deep
link. For builds the origin is frozen at build time. A separate static preview
server must proxy `/api` to its own backend. These settings neither launch nor
upgrade an existing app. Node remains a build/development dependency only.

The controller validates unknown success payloads at runtime, including video
identity, finite progress, analysis ownership, server processing settings and the
exact selected video's relative playback-proxy URL. Unknown video modes and job
kind/status labels remain visible; they do not acquire pause/resume semantics.
Annotation documents, source timestamps and original predictions are not written
or reinterpreted by this phase. Preview media time is not exact source timing.

Uploads use the generated multipart operation through the shared typed client
with an XHR fetch adapter. This supplies actual transferred byte counts (or an
indeterminate bar when unavailable), same-origin cookies, abort, network errors
and a bounded 30-minute transfer timeout. Transfer completion precedes server
import completion. Cancelling or timing out is not proof that the server rolled
back an import; refresh jobs before retrying. Imports and completed background
jobs never select a video or replace a draft. Failed imports remain visible.
Only queued/running full-match analysis jobs can request cooperative pause;
resume submits a new analysis job using its validated original settings and
retains job history. Missing previous settings require an explicit new start.

`createLibrarySession<T>()` owns the shared selection and draft navigation guard
for the future editor. Inject that session into `createLibraryController` and
use its draft store for the editor document. Selection checks `canLeave()`
before aborting any reads. Dirty/saving drafts block navigation; callers must
save successfully or explicitly discard through the draft store. The preview
does not invent an editable annotation field to demonstrate this guard.
Library/jobs polling, selected metadata, analysis and playback use independent
latest-read lanes and selection epochs. Late successes/errors and mutation
completions cannot overwrite another selected source. Dispose cancels timers,
read lanes and pending upload transport; an already-submitted server job may
continue. Job records are separate from the annotation draft.

Focused unit probes cover malformed/unknown payloads, YouTube validation,
late success/error, selection/draft guards, pause/resume settings, selected-job
ownership, HTTP 401/403/413/409/422 guidance, upload bytes/cancellation and polling
cleanup. `tests/frontend-library.mjs` exercises the built preview against an
owned generated-media backend with downloader/perception stubs. It does not
prove external downloader availability, model accuracy, source-clock editor
parity, or screen-reader certification. The legacy editor remains available
until the later review-editor and default-cutover phases establish parity.

Run the built library integration from the repository root:

```sh
npm run frontend:build
node tests/frontend-library.mjs
```

As with the foundation harness, `FRONTEND_PYTHON` and
`PLAYWRIGHT_BROWSERS_PATH` may select the locked review interpreter and cached
test Chromium. The harness rejects `BASE_URL`, owns both loopback listeners,
retains source/build hashes and cleanup receipts, and preserves generated
source bytes, native timestamps, saved annotations and original predictions.
