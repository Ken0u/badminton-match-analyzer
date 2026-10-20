import test from "node:test";
import assert from "node:assert/strict";
import {
  createApiClient,
  ApiError,
  ApiProtocolError,
  isCancellation,
} from "../.test-build/api/client.js";
import {
  createSelectionScope,
  createLatestTask,
} from "../.test-build/state/selection.js";
import { createDraftStore } from "../.test-build/state/draft.js";
import { createServerStore } from "../.test-build/state/server.js";
import { createPlaybackStore } from "../.test-build/state/playback.js";

const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const apiWith = (fn) =>
  createApiClient({ baseUrl: "https://example.test/", fetch: fn });

test("client encodes path/query, preserves unknown JSON and forwards cancellation and credentials", async () => {
  const controller = new AbortController();
  let call;
  const client = apiWith(async (url, init) => {
    call = { url, init };
    return new Response('{"not_yet_typed":[null,"unknown"]}');
  });
  const result = await client.request("get", "/api/videos/{video_id}/frame", {
    path: { video_id: "a/b ?" },
    query: { frame: 0 },
    signal: controller.signal,
  });
  assert.deepEqual(result, { not_yet_typed: [null, "unknown"] });
  assert.equal(
    call.url,
    "https://example.test/api/videos/a%2Fb%20%3F/frame?frame=0",
  );
  assert.equal(call.init.signal, controller.signal);
  assert.equal(call.init.credentials, "same-origin");
});

test("HTTP errors retain structured detail/status and non-JSON bodies including revision conflicts", async () => {
  for (const [body, status, detail] of [
    [
      '{"detail":[{"loc":["body","mode"],"msg":"invalid"}]}',
      422,
      [{ loc: ["body", "mode"], msg: "invalid" }],
    ],
    ['{"detail":"Revision conflict"}', 409, "Revision conflict"],
    ["Not found", 404, "Not found"],
    ["<h1>Unavailable</h1>", 503, "<h1>Unavailable</h1>"],
  ]) {
    await assert.rejects(
      apiWith(async () => new Response(body, { status })).request(
        "get",
        "/api/videos",
        {},
      ),
      (error) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.status, status);
        assert.equal(error.isConflict, status === 409);
        assert.deepEqual(error.detail, detail);
        assert.equal(error.rawBody, body);
        return true;
      },
    );
  }
});

test("success invalid JSON is a protocol error; empty success and fetch failures stay distinct", async () => {
  await assert.rejects(
    apiWith(async () => new Response("<html>login</html>")).request(
      "get",
      "/api/health",
      {},
    ),
    ApiProtocolError,
  );
  assert.equal(
    await apiWith(async () => new Response(null, { status: 204 })).request(
      "get",
      "/api/health",
      {},
    ),
    undefined,
  );
  const network = new TypeError("network down");
  await assert.rejects(
    apiWith(async () => {
      throw network;
    }).request("get", "/api/health", {}),
    (error) => error === network,
  );
});

test("caller cancellation is checked before send and after noncompliant body completion", async () => {
  const controller = new AbortController();
  controller.abort();
  let calls = 0;
  await assert.rejects(
    apiWith(async () => {
      ++calls;
      return new Response("{}");
    }).request("get", "/api/health", { signal: controller.signal }),
    isCancellation,
  );
  assert.equal(calls, 0);
  const active = new AbortController();
  const response = deferred();
  const pending = apiWith(async () => response.promise).request(
    "get",
    "/api/health",
    { signal: active.signal },
  );
  active.abort();
  response.resolve(new Response("{}"));
  await assert.rejects(pending, isCancellation);
});

test("JSON mutations preserve revision; FormData does not invent multipart boundaries", async () => {
  const calls = [];
  const client = apiWith(async (_url, init) => {
    calls.push(init);
    return new Response("{}");
  });
  await client.request("put", "/api/videos/{video_id}/annotations", {
    path: { video_id: "v" },
    json: { revision: 7, untouched_unknown: null },
  });
  assert.equal(calls[0].body, '{"revision":7,"untouched_unknown":null}');
  assert.equal(calls[0].headers.get("Content-Type"), "application/json");
  const body = new FormData();
  body.set("file", new Blob(["fixture"]), "fixture.txt");
  await client.request("post", "/api/upload", { body });
  assert.equal(calls[1].body, body);
  assert.equal(calls[1].headers.has("Content-Type"), false);
});

test("latest read fences both out-of-order same selection and changed selection; stale errors ignored", async () => {
  const scope = createSelectionScope();
  const lane = createLatestTask(scope);
  const writes = [];
  const a = scope.select("a");
  const slow = deferred();
  const first = lane.run(
    a,
    () => slow.promise,
    (value) => writes.push(value),
  );
  await lane.run(
    a,
    async () => "new",
    (value) => writes.push(value),
  );
  slow.resolve("old");
  assert.equal((await first).status, "stale");
  const late = deferred();
  const previous = lane.run(
    a,
    () => late.promise,
    (value) => writes.push(value),
  );
  scope.select("b");
  late.reject(new Error("late a error"));
  assert.equal((await previous).status, "stale");
  assert.deepEqual(writes, ["new"]);
  assert.equal(a.signal.aborted, true);
});

test("server records/jobs stay distinct and reject selection ABA stale writes", () => {
  const scope = createSelectionScope();
  const store = createServerStore(scope);
  const old = scope.select("a");
  scope.select("b");
  const current = scope.select("a");
  assert.equal(store.setRecord(old, "stale"), false);
  assert.equal(store.setJobs(old, "stale"), false);
  assert.equal(store.setRecord(current, { unknown: null }), true);
  store.setJobs(current, ["queued"]);
  assert.deepEqual(store.getSnapshot(), {
    records: { a: { unknown: null } },
    jobs: { a: ["queued"] },
  });
});

test("draft save snapshot preserves edits made during save and advances only saved revision", () => {
  const scope = createSelectionScope();
  const owner = scope.select("a");
  const drafts = createDraftStore(scope);
  drafts.open(owner, { note: "initial", unknown: null }, 3);
  drafts.edit((value) => ({ ...value, note: "first" }));
  const ticket = drafts.beginSave();
  assert.equal(ticket.revision, 3);
  assert.equal(drafts.canLeave(), false);
  assert.equal(drafts.beginSave(), null);
  assert.equal(drafts.discard(), false);
  drafts.edit((value) => ({ ...value, note: "second" }));
  assert.equal(drafts.completeSave(ticket, 4, ticket.value), true);
  assert.equal(drafts.completeSave(ticket, 9, { note: "stale" }), false);
  assert.equal(drafts.getSnapshot().revision, 4);
  assert.equal(drafts.getSnapshot().value.note, "second");
  assert.equal(drafts.getSnapshot().dirty, true);
  drafts.discard();
  assert.deepEqual(drafts.getSnapshot().value, {
    note: "first",
    unknown: null,
  });
  assert.equal(drafts.canLeave(), true);
});

test("failed and stale mutations preserve local draft without changing another selection", () => {
  const scope = createSelectionScope();
  const owner = scope.select("a");
  const drafts = createDraftStore(scope);
  drafts.open(owner, { unknown: null }, 2);
  drafts.edit(() => ({ unknown: "edited" }));
  const ticket = drafts.beginSave();
  const conflict = new ApiError(409, "conflict", "conflict", "/api");
  drafts.failSave(ticket, conflict);
  assert.equal(drafts.getSnapshot().error, conflict);
  assert.equal(drafts.getSnapshot().dirty, true);
  assert.equal(drafts.getSnapshot().revision, 2);
  const retried = drafts.beginSave();
  scope.select("b");
  assert.equal(drafts.completeSave(retried, 5, { unknown: "late" }), false);
  assert.equal(drafts.getSnapshot().value.unknown, "edited");
});

test("600 playback updates notify only imperative subscribers and preserve unknown source identity", () => {
  const scope = createSelectionScope();
  const records = createServerStore(scope);
  const drafts = createDraftStore(scope);
  const playback = createPlaybackStore();
  let broad = 0;
  let ticks = 0;
  records.subscribe(() => ++broad);
  drafts.subscribe(() => ++broad);
  const stop = playback.subscribe(() => ++ticks);
  for (let i = 0; i < 600; ++i)
    playback.update({
      mediaTime: i / 60,
      playing: true,
      sourceFrame: null,
      sourceTime: null,
    });
  assert.equal(ticks, 600);
  assert.equal(broad, 0);
  assert.equal(playback.getSnapshot().sourceFrame, null);
  stop();
  playback.update({
    mediaTime: 10,
    playing: false,
    sourceFrame: 7,
    sourceTime: 9.74,
  });
  assert.equal(ticks, 600);
  assert.equal(playback.getSnapshot().sourceTime, 9.74);
});
