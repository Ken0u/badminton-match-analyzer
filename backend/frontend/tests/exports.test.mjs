import test from "node:test";
import assert from "node:assert/strict";
import {
  ExportPayloadError,
  parseExportStatus,
  parseRecoveredExports,
} from "../.test-build/editor/exports/model.js";
import { createExportController } from "../.test-build/editor/exports/controller.js";
import { isMediaExportInteractive } from "../.test-build/editor/exports/ExportPanel.js";
import { ApiError, ApiProtocolError } from "../.test-build/api/client.js";

const id = "a".repeat(32);
const request = { videoId: "video-a", revision: 2, mode: "plain-rallies" };
const hash = "b".repeat(64);
const job = (overrides = {}) => ({
  id,
  kind: "media-export",
  video_id: request.videoId,
  status: "completed",
  progress: 1,
  message: "Completed",
  details: { revision: request.revision, mode: request.mode },
  ...overrides,
});
const manifest = (overrides = {}) => ({
  schema_version: 1,
  purpose: "reviewed_rally_videos",
  source: { id: request.videoId },
  annotation_revision: request.revision,
  annotations: { revision: request.revision },
  counts: { total: 2, eligible: 1, ineligible: 1 },
  rallies: [
    {
      rally_id: "R1",
      eligible: true,
      reasons: [],
      clip: { file: "rally-000001.mp4", sha256: hash },
    },
    {
      rally_id: "R2",
      eligible: false,
      reasons: ["missing_source"],
      clip: null,
    },
  ],
  ...overrides,
});
const completed = (overrides = {}) => ({
  job: job(),
  available: true,
  manifest: manifest(),
  files: [
    {
      filename: "manifest.json",
      size_bytes: 10,
      sha256: hash,
      media_type: "application/json",
    },
    {
      filename: "rally-000001.mp4",
      size_bytes: 11,
      sha256: hash,
      media_type: "video/mp4",
    },
  ],
  ...overrides,
});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const settle = () => new Promise((resolve) => setImmediate(resolve));
const current = () => ({ ...request, dirty: false, saving: false });

for (const failure of [
  new TypeError("Failed to fetch"),
  new ApiError(503, "Temporarily unavailable", "", "/api/jobs"),
]) {
  test(`active export recovers after transient list failure: ${failure.name}`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    let lists = 0;
    const controller = createExportController({
      pollMs: 100,
      api: {
        request(method, path) {
          assert.equal(method, "get", "poll recovery cannot submit a mutation");
          if (path === "/api/jobs") {
            if (++lists === 2) return Promise.reject(failure);
            return Promise.resolve([job()]);
          }
          return Promise.resolve(
            lists < 3
              ? { job: job({ status: "running" }), available: false }
              : completed(),
          );
        },
      },
    });
    try {
      controller.select(request.videoId);
      await settle();
      t.mock.timers.tick(100);
      await settle();
      assert.equal(lists, 2);
      assert.equal(controller.getSnapshot().jobs[0].status, "running");
      assert.equal(controller.getSnapshot().loading, false);
      assert.equal(controller.getSnapshot().error, true);
      t.mock.timers.tick(100);
      await settle();
      assert.equal(lists, 3, "known active export must resume its list reads");
      assert.equal(controller.getSnapshot().jobs[0].available, true);
      assert.equal(controller.getSnapshot().error, false);
      t.mock.timers.tick(1000);
      await settle();
      assert.equal(lists, 3, "terminal exports stop polling");
    } finally {
      controller.dispose();
    }
  });
}

const pollingHarness = (t, { known = true } = {}) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let lists = 0,
    posts = 0;
  let list = () => Promise.reject(new TypeError("Connection lost"));
  let post = () => Promise.reject(new ApiError(409, "Busy", "", "/exports"));
  let status = () =>
    Promise.resolve({ job: job({ status: "running" }), available: false });
  const controller = createExportController({
    pollMs: 100,
    api: {
      request(method, path) {
        if (method === "post") {
          posts++;
          return post();
        }
        if (path === "/api/jobs") {
          lists++;
          return lists === 1 && known ? Promise.resolve([job()]) : list();
        }
        return status();
      },
    },
  });
  t.after(() => controller.dispose());
  controller.select(request.videoId);
  return {
    controller,
    counts: () => ({ lists, posts }),
    setList: (callback) => {
      list = callback;
    },
    setPost: (callback) => {
      post = callback;
    },
    setStatus: (callback) => {
      status = callback;
    },
    tick: async () => {
      t.mock.timers.tick(100);
      await settle();
    },
  };
};

test("list recovery stops after exactly three extra reads and manual refresh resets the episode", async (t) => {
  const h = pollingHarness(t);
  await settle();
  for (let i = 0; i < 4; i++) await h.tick();
  assert.deepEqual(h.counts(), { lists: 5, posts: 0 });
  assert.match(h.controller.getSnapshot().message, /stopped.*Refresh jobs/);
  assert.equal(h.controller.getSnapshot().jobs[0].status, "running");
  assert.equal(h.controller.getSnapshot().loading, false);
  for (let i = 0; i < 5; i++) await h.tick();
  assert.equal(h.counts().lists, 5);
  await h.controller.refresh();
  for (let i = 0; i < 4; i++) await h.tick();
  assert.equal(h.counts().lists, 9, "manual read plus three additional reads");
});

test("a successful current read resets the recovery budget", async (t) => {
  const h = pollingHarness(t);
  await settle();
  for (let i = 0; i < 3; i++) await h.tick();
  h.setList(() => Promise.resolve([job()]));
  await h.tick();
  assert.equal(h.controller.getSnapshot().error, false);
  h.setList(() => Promise.reject(new TypeError("Offline again")));
  for (let i = 0; i < 4; i++) await h.tick();
  assert.equal(h.counts().lists, 9);
  await h.tick();
  assert.equal(h.counts().lists, 9);
});

test("an unknown active job cannot be inferred from a failed initial read", async (t) => {
  const h = pollingHarness(t, { known: false });
  await settle();
  for (let i = 0; i < 5; i++) await h.tick();
  assert.equal(h.counts().lists, 1);
  assert.equal(h.controller.getSnapshot().loading, false);
  assert.equal(h.controller.getSnapshot().jobs.length, 0);
});

test("cancelling a recovery read replaces its automatic-refresh notice and stops", async (t) => {
  const h = pollingHarness(t);
  await settle();
  await h.tick();
  assert.match(h.controller.getSnapshot().message, /automatically/);
  h.setList(() => Promise.reject(new DOMException("Cancelled", "AbortError")));
  await h.tick();
  assert.match(h.controller.getSnapshot().message, /cancelled.*Refresh jobs/);
  assert.doesNotMatch(h.controller.getSnapshot().message, /automatically/);
  for (let i = 0; i < 4; i++) await h.tick();
  assert.equal(h.counts().lists, 3);
});

test("queued exports recover from a browser NetworkError without losing a start error", async (t) => {
  const h = pollingHarness(t);
  await settle();
  h.setList(() => Promise.resolve([job({ status: "queued" })]));
  h.setStatus(() =>
    Promise.resolve({ job: job({ status: "queued" }), available: false }),
  );
  await h.tick();
  await h.controller.start(request, current);
  h.setList(() =>
    Promise.reject(new DOMException("Network unavailable", "NetworkError")),
  );
  await h.tick();
  assert.match(h.controller.getSnapshot().message, /shared admission is busy/);
  assert.match(h.controller.getSnapshot().message, /Network unavailable/);
  h.setList(() => Promise.resolve([job()]));
  h.setStatus(() => Promise.resolve(completed()));
  await h.tick();
  assert.equal(h.controller.getSnapshot().jobs[0].available, true);
  assert.equal(h.controller.getSnapshot().error, true);
  assert.match(h.controller.getSnapshot().message, /shared admission is busy/);
  assert.doesNotMatch(
    h.controller.getSnapshot().message,
    /Network unavailable/,
  );
  assert.equal(h.counts().posts, 1);
});

for (const failure of [
  ...[400, 401, 403, 404, 409, 429].map(
    (code) => new ApiError(code, "Rejected", "", "/api/jobs"),
  ),
  new ApiProtocolError(200, "not JSON", "/api/jobs"),
  new ExportPayloadError("Malformed list"),
  new Error("Unexpected application error"),
  new DOMException("Cancelled", "AbortError"),
]) {
  test(`nonretryable list failure stops automatic reads: ${failure.name} ${failure.status ?? failure.message}`, async (t) => {
    const h = pollingHarness(t);
    await settle();
    h.setList(() => Promise.reject(failure));
    await h.tick();
    assert.equal(h.controller.getSnapshot().loading, false);
    for (let i = 0; i < 5; i++) await h.tick();
    assert.equal(h.counts().lists, 2);
    assert.equal(h.controller.getSnapshot().jobs[0].status, "running");
    h.setList(() => Promise.resolve([job()]));
    h.setStatus(() => Promise.resolve(completed()));
    await h.controller.refresh();
    assert.equal(h.controller.getSnapshot().jobs[0].available, true);
    assert.equal(h.controller.getSnapshot().error, false);
  });
}

test("malformed returned lists and failures without known active jobs do not retry", async (t) => {
  const h = pollingHarness(t);
  await settle();
  h.setList(() => Promise.resolve({ jobs: [] }));
  await h.tick();
  for (let i = 0; i < 4; i++) await h.tick();
  assert.equal(h.counts().lists, 2);
  h.controller.select("video-b");
  h.setList(() => Promise.reject(new TypeError("Offline")));
  await settle();
  for (let i = 0; i < 4; i++) await h.tick();
  assert.equal(h.counts().lists, 3);
  assert.equal(h.controller.getSnapshot().jobs.length, 0);
});

for (const guard of ["post", "dirty", "saving", "revision"]) {
  test(`successful recovery preserves independent ${guard} error and never retries POST`, async (t) => {
    const h = pollingHarness(t);
    await settle();
    await h.tick();
    const now = current();
    if (guard === "dirty") now.dirty = true;
    if (guard === "saving") now.saving = true;
    if (guard === "revision") now.revision = 3;
    await h.controller.start(request, () => now);
    const message = h.controller.getSnapshot().message;
    const expected =
      guard === "post"
        ? /Refresh or start a new export/
        : guard === "revision"
          ? /saved revision changed/
          : /Save annotations/;
    assert.match(message, expected);
    h.setList(() => Promise.resolve([job()]));
    h.setStatus(() => Promise.resolve(completed()));
    await h.tick();
    assert.equal(h.controller.getSnapshot().jobs[0].available, true);
    assert.equal(h.controller.getSnapshot().error, true);
    assert.match(h.controller.getSnapshot().message, expected);
    assert.doesNotMatch(h.controller.getSnapshot().message, /Connection lost/);
    assert.equal(h.counts().posts, guard === "post" ? 1 : 0);
  });
}

for (const staleOutcome of ["success", "failure"]) {
  test(`superseded ${staleOutcome} recovery cannot change current error or revive a timer`, async (t) => {
    const h = pollingHarness(t);
    await settle();
    await h.tick();
    const stale = deferred();
    h.setList(() => stale.promise);
    await h.tick();
    h.setList(() => Promise.resolve([job()]));
    h.setStatus(() => Promise.resolve(completed()));
    await h.controller.refresh();
    if (staleOutcome === "success") stale.resolve([job()]);
    else stale.reject(new TypeError("Stale offline"));
    await settle();
    assert.equal(h.controller.getSnapshot().error, false);
    assert.equal(h.controller.getSnapshot().jobs[0].available, true);
    await h.tick();
    assert.equal(h.counts().lists, 4);
  });
}

for (const ending of ["switch", "dispose", "start"]) {
  test(`pending recovery is fenced by ${ending}`, async (t) => {
    const h = pollingHarness(t);
    await settle();
    await h.tick();
    const pending = deferred();
    h.setList(() => pending.promise);
    await h.tick();
    let started;
    if (ending === "dispose") h.controller.dispose();
    if (ending === "switch") {
      h.setList(() => Promise.resolve([]));
      h.controller.select("video-b");
      h.controller.select(request.videoId);
    }
    if (ending === "start") {
      const post = deferred();
      h.setPost(() => post.promise);
      started = h.controller.start(request, current);
      await h.controller.refresh();
      await h.tick();
      assert.equal(h.counts().lists, 3);
      post.reject(new ApiError(401, "Sign in", "", "/exports"));
    }
    pending.reject(new TypeError("Stale offline"));
    await started;
    await settle();
    const state = h.controller.getSnapshot();
    assert.doesNotMatch(state.message, /Stale offline/);
    if (ending === "start") {
      h.setList(() => Promise.resolve([job()]));
      h.setStatus(() => Promise.resolve(completed()));
    }
    const before = h.counts().lists;
    await h.tick();
    assert.equal(h.counts().lists, before + (ending === "start" ? 1 : 0));
    assert.equal(h.counts().posts, ending === "start" ? 1 : 0);
  });
}

test("recovered list keeps per-card status failures unavailable", async (t) => {
  const h = pollingHarness(t);
  await settle();
  await h.tick();
  h.setList(() => Promise.resolve([job()]));
  h.setStatus(() =>
    Promise.reject(new ApiError(409, "Changed bytes", "", "/status")),
  );
  await h.tick();
  assert.equal(h.controller.getSnapshot().error, false);
  assert.equal(h.controller.getSnapshot().jobs[0].available, false);
  assert.match(
    h.controller.getSnapshot().jobs[0].unavailableReason,
    /saved inputs changed/,
  );
});

for (const outcome of [
  "401",
  "409",
  "malformed",
  "completed",
  "failed",
  "future-state",
]) {
  test(`delayed initial list and ${outcome} start leave manual job recovery usable`, async () => {
    const initialList = deferred();
    let reads = 0,
      posts = 0;
    const controller = createExportController({
      api: {
        request(method, path) {
          if (path === "/api/jobs")
            return ++reads === 1
              ? initialList.promise
              : Promise.resolve([job()]);
          if (method === "post") {
            posts++;
            if (posts > 1) return Promise.resolve(job());
            if (outcome === "401" || outcome === "409")
              return Promise.reject(
                new ApiError(Number(outcome), "Rejected", "", path),
              );
            return Promise.resolve(
              outcome === "malformed" ? {} : job({ status: outcome }),
            );
          }
          return Promise.resolve(
            reads > 1 || outcome === "completed"
              ? completed()
              : { job: job({ status: outcome }), available: false },
          );
        },
      },
    });
    try {
      controller.select(request.videoId);
      assert.equal(controller.getSnapshot().loading, true);
      await controller.start(request, current);
      initialList.resolve([]);
      await settle();
      const state = controller.getSnapshot();
      assert.equal(
        state.loading,
        false,
        "Refresh jobs must be enabled after both requests settle",
      );
      assert.equal(state.starting, false);
      assert.equal(state.error, ["401", "409", "malformed"].includes(outcome));
      if (!state.error) {
        assert.equal(state.jobs[0].status, outcome);
        assert.equal(state.jobs[0].available, outcome === "completed");
      }
      if (outcome === "401")
        assert.match(state.message, /Sign in, then refresh/);
      if (outcome === "409")
        assert.match(state.message, /Refresh or start a new export/);
      await controller.refresh();
      assert.equal(controller.getSnapshot().loading, false);
      assert.equal(controller.getSnapshot().jobs[0].id, id);
      assert.equal(controller.getSnapshot().jobs[0].available, true);
      assert.equal(reads, 2, "recovery is an explicit read");
      assert.equal(posts, 1, "recovery never retries the mutation");
      if (state.error) {
        await controller.start(request, current);
        assert.equal(posts, 2, "an explicit retry is available after recovery");
        assert.equal(controller.getSnapshot().error, false);
        assert.equal(controller.getSnapshot().jobs[0].available, true);
      }
    } finally {
      controller.dispose();
    }
  });
}

test("refresh waits for the current POST and first status, retaining the posted job and older jobs", async () => {
  const post = deferred(),
    firstStatus = deferred();
  const historicalId = "c".repeat(32);
  const historical = job({
    id: historicalId,
    details: { revision: 1, mode: request.mode },
  });
  let lists = 0,
    posts = 0,
    statusReads = 0;
  const controller = createExportController({
    api: {
      request(method, path, options) {
        if (path === "/api/jobs") {
          lists++;
          return Promise.resolve(
            lists === 1 ? [historical] : [job(), historical],
          );
        }
        if (method === "post") {
          posts++;
          assert.deepEqual(options.json, { revision: 2, mode: request.mode });
          return post.promise;
        }
        if (options.path.job_id === historicalId)
          return Promise.resolve({ job: historical, available: false });
        return ++statusReads === 1
          ? firstStatus.promise
          : Promise.resolve(completed());
      },
    },
  });
  try {
    controller.select(request.videoId);
    await settle();
    const started = controller.start(request, current);
    await controller.refresh();
    await controller.start(request, current);
    assert.equal(
      lists,
      1,
      "a refresh cannot capture an empty list before the POST settles",
    );
    post.resolve(job());
    await settle();
    await controller.refresh();
    assert.equal(
      lists,
      1,
      "the first status belongs to the same start operation",
    );
    assert.equal(controller.getSnapshot().starting, true);
    firstStatus.resolve(completed());
    await started;
    assert.deepEqual(
      controller.getSnapshot().jobs.map(({ id }) => id),
      [id, historicalId],
    );
    assert.equal(controller.getSnapshot().jobs[1].revision, 1);
    await controller.refresh();
    assert.equal(controller.getSnapshot().jobs[0].available, true);
    assert.equal(lists, 2);
    assert.equal(posts, 1);
  } finally {
    controller.dispose();
  }
});

for (const staleOutcome of ["success", "failure"]) {
  test(`superseded ${staleOutcome} list cannot release the newer recovery read`, async () => {
    const stale = deferred(),
      recovery = deferred();
    let lists = 0;
    const controller = createExportController({
      api: {
        request(method, path) {
          if (path === "/api/jobs")
            return ++lists === 1 ? stale.promise : recovery.promise;
          if (method === "post")
            return Promise.reject(new ApiError(401, "Sign in", "", path));
          return Promise.resolve(completed());
        },
      },
    });
    try {
      controller.select(request.videoId);
      await controller.start(request, current);
      const refreshed = controller.refresh();
      if (staleOutcome === "success") stale.resolve([]);
      else stale.reject(new Error("Stale failure"));
      await settle();
      assert.equal(controller.getSnapshot().loading, true);
      assert.match(controller.getSnapshot().message, /Sign in, then refresh/);
      recovery.resolve([job()]);
      await refreshed;
      assert.equal(controller.getSnapshot().loading, false);
      assert.equal(controller.getSnapshot().jobs[0].available, true);
    } finally {
      controller.dispose();
    }
  });
}

for (const oldPostOutcome of ["success", "failure"]) {
  test(`new selections refresh behind an old ${oldPostOutcome} POST and fence A-B-A replies`, async () => {
    const post = deferred(),
      returnedList = deferred();
    const reads = [];
    let posts = 0,
      aReads = 0;
    const controller = createExportController({
      api: {
        request(method, path, options) {
          if (method === "post") {
            posts++;
            return post.promise;
          }
          if (path === "/api/jobs") {
            const selected = options.query.video_id;
            reads.push(selected);
            if (selected === request.videoId && ++aReads === 2)
              return returnedList.promise;
            return Promise.resolve([]);
          }
          return Promise.resolve(completed());
        },
      },
    });
    try {
      controller.select(request.videoId);
      await settle();
      const started = controller.start(request, current);
      controller.select("video-b");
      await settle();
      await controller.refresh();
      assert.deepEqual(reads, [request.videoId, "video-b", "video-b"]);
      assert.equal(controller.getSnapshot().loading, false);
      controller.select(request.videoId);
      if (oldPostOutcome === "success") post.resolve(job());
      else post.reject(new ApiError(401, "Old login error", "", "/api/export"));
      await started;
      assert.equal(controller.getSnapshot().loading, true);
      assert.equal(controller.getSnapshot().starting, false);
      assert.equal(controller.getSnapshot().error, false);
      assert.equal(controller.getSnapshot().jobs.length, 0);
      returnedList.resolve([job()]);
      await settle();
      assert.equal(controller.getSnapshot().loading, false);
      assert.equal(controller.getSnapshot().jobs[0].available, true);
      assert.equal(posts, 1);
    } finally {
      controller.dispose();
    }
  });
}

test("polling pauses during a start and manual read, then recovers an older active job after rejection", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const post = deferred(),
    manualList = deferred();
  let lists = 0,
    posts = 0;
  const controller = createExportController({
    pollMs: 100,
    api: {
      request(method, path) {
        if (method === "post") {
          posts++;
          return post.promise;
        }
        if (path === "/api/jobs") {
          lists++;
          return lists === 2 ? manualList.promise : Promise.resolve([job()]);
        }
        return Promise.resolve(
          lists < 3
            ? {
                job: job({ status: "running", progress: 0.4 }),
                available: false,
              }
            : completed(),
        );
      },
    },
  });
  try {
    controller.select(request.videoId);
    await settle();
    const started = controller.start(request, current);
    t.mock.timers.tick(1000);
    await settle();
    assert.equal(
      lists,
      1,
      "the scheduled poll must not race the pending mutation",
    );
    post.reject(new ApiError(409, "Busy", "", "/api/export"));
    await started;
    assert.equal(controller.getSnapshot().jobs[0].status, "running");
    const refreshed = controller.refresh();
    t.mock.timers.tick(1000);
    await settle();
    assert.equal(lists, 2, "manual refresh cancels the older scheduled poll");
    manualList.resolve([job()]);
    await refreshed;
    t.mock.timers.tick(100);
    await settle();
    assert.equal(lists, 3);
    assert.equal(controller.getSnapshot().jobs[0].available, true);
    assert.equal(controller.getSnapshot().loading, false);
    assert.equal(posts, 1);
  } finally {
    controller.dispose();
  }
});

test("a cancelled current read releases Refresh for explicit recovery", async () => {
  let reads = 0;
  const controller = createExportController({
    api: {
      request(method, path) {
        assert.equal(method, "get");
        if (path === "/api/jobs") {
          if (++reads === 1)
            return Promise.reject(new DOMException("Cancelled", "AbortError"));
          return Promise.resolve([job()]);
        }
        return Promise.resolve(completed());
      },
    },
  });
  try {
    controller.select(request.videoId);
    await settle();
    assert.equal(controller.getSnapshot().loading, false);
    await controller.refresh();
    assert.equal(controller.getSnapshot().jobs[0].available, true);
    assert.equal(reads, 2);
  } finally {
    controller.dispose();
  }
});

test("completed media exports require owned revision, manifest, and every safe native file", () => {
  const result = parseExportStatus(completed(), request, id);
  assert.equal(result.available, true);
  assert.equal(result.files.length, 2);
  assert.equal(
    result.files[1].href,
    `/api/videos/video-a/media-exports/${id}/files/rally-000001.mp4`,
  );
  for (const value of [
    completed({ files: completed().files.slice(1) }),
    completed({
      files: [
        ...completed().files,
        {
          filename: "../truth.mp4",
          size_bytes: 1,
          sha256: hash,
          media_type: "video/mp4",
        },
      ],
    }),
    completed({
      files: [
        { ...completed().files[0], media_type: "video/mp4" },
        completed().files[1],
      ],
    }),
    completed({
      manifest: manifest({ counts: { total: 3, eligible: 1, ineligible: 1 } }),
    }),
    completed({ job: job({ details: { revision: 3, mode: request.mode } }) }),
    completed({
      files: [
        { ...completed().files[0], filename: "manifest.json", sha256: "bad" },
        completed().files[1],
      ],
    }),
  ])
    assert.throws(
      () => parseExportStatus(value, request, id),
      ExportPayloadError,
    );
});

test("unknown, active, and unavailable statuses cannot produce downloads", () => {
  const unknown = parseExportStatus(
    { job: job({ status: "future-state" }), available: false },
    request,
    id,
  );
  const active = parseExportStatus(
    { job: job({ status: "running", progress: 0.4 }), available: false },
    request,
    id,
  );
  assert.equal(unknown.available, false);
  assert.equal(active.available, false);
  assert.throws(() =>
    parseExportStatus(
      {
        job: job({ status: "running" }),
        available: true,
        manifest: manifest(),
        files: [],
      },
      request,
      id,
    ),
  );
  assert.throws(() => parseRecoveredExports([job(), job()], request.videoId));
});

test("every rally receipt including partial labels is retained for completed exports", () => {
  const value = completed({
    manifest: manifest({
      rallies: [
        {
          rally_id: "R1",
          eligible: true,
          reasons: [],
          clip: { file: "rally-000001.mp4", sha256: hash },
        },
        {
          rally_id: "PARTIAL-R2",
          eligible: false,
          reasons: ["missing_or_ambiguous_end", "unreviewed_start"],
          clip: null,
        },
      ],
    }),
  });
  const result = parseExportStatus(value, request, id);
  assert.deepEqual(result.rallies[1], {
    rallyId: "PARTIAL-R2",
    eligible: false,
    reasons: ["missing_or_ambiguous_end", "unreviewed_start"],
  });
});

test("controller fences stale post and status reads, keeps historical request revision, and never retries mutations", async () => {
  let resolvePost;
  const post = new Promise((resolve) => {
    resolvePost = resolve;
  });
  const calls = [];
  const api = {
    request(method, path, options) {
      calls.push([method, path, options]);
      if (method === "post") return post;
      if (path === "/api/jobs") return Promise.resolve([]);
      return Promise.resolve(completed());
    },
  };
  const controller = createExportController({ api, pollMs: 100000 });
  controller.select(request.videoId);
  await new Promise((resolve) => setTimeout(resolve, 0));
  let latest = {
    videoId: request.videoId,
    revision: 2,
    dirty: false,
    saving: false,
  };
  const started = controller.start(request, () => latest);
  latest = { ...latest, revision: 3 }; // A later save must not relabel the captured POST.
  resolvePost(job());
  await started;
  assert.equal(controller.getSnapshot().jobs[0].revision, 2);
  assert.equal(calls.filter(([method]) => method === "post").length, 1);
  controller.select("video-b");
  assert.equal(controller.getSnapshot().jobs.length, 0);
  controller.dispose();
});

test("click-time clean saved guard rejects dirty and saving documents without POST", async () => {
  let posts = 0;
  const controller = createExportController({
    api: {
      request(method) {
        if (method === "post") posts++;
        return Promise.resolve([]);
      },
    },
  });
  controller.select(request.videoId);
  await controller.start(request, () => ({
    videoId: request.videoId,
    revision: 2,
    dirty: true,
    saving: false,
  }));
  await controller.start(request, () => ({
    videoId: request.videoId,
    revision: 2,
    dirty: false,
    saving: true,
  }));
  assert.equal(posts, 0);
  assert.match(controller.getSnapshot().message, /Save annotations/);
  controller.dispose();
});

test("overlapping refreshes fence stale per-job success and fail closed 409 cards", async () => {
  let jobsRead = 0;
  let resolveFirst;
  const first = new Promise((resolve) => {
    resolveFirst = resolve;
  });
  const api = {
    request(method, path) {
      if (path === "/api/jobs") return Promise.resolve([job()]);
      if (++jobsRead === 1) return first;
      throw Object.assign(new Error("artifacts changed"), { status: 409 });
    },
  };
  const controller = createExportController({ api, pollMs: 100000 });
  controller.select(request.videoId);
  await new Promise((resolve) => setTimeout(resolve, 0));
  const newer = controller.refresh();
  await newer;
  assert.equal(controller.getSnapshot().jobs[0].available, false);
  assert.match(
    controller.getSnapshot().jobs[0].unavailableReason,
    /artifacts changed/,
  );
  resolveFirst(completed());
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(controller.getSnapshot().jobs[0].available, false);
  controller.dispose();
});

test("synchronous repeated starts submit one mutation and focused export controls isolate editor shortcuts", async () => {
  let resolvePost,
    posts = 0;
  const post = new Promise((resolve) => {
    resolvePost = resolve;
  });
  const controller = createExportController({
    api: {
      request(method, path) {
        if (method === "post") {
          posts++;
          return post;
        }
        if (path === "/api/jobs") return Promise.resolve([]);
        return Promise.resolve({
          job: job({ status: "queued", progress: 0 }),
          available: false,
        });
      },
    },
    pollMs: 100000,
  });
  controller.select(request.videoId);
  const current = () => ({
    videoId: request.videoId,
    revision: 2,
    dirty: false,
    saving: false,
  });
  const first = controller.start(request, current);
  const second = controller.start(request, current);
  assert.equal(posts, 1);
  resolvePost(job({ status: "queued", progress: 0 }));
  await Promise.all([first, second]);
  assert.equal(controller.getSnapshot().starting, false);
  for (const tag of ["A", "BUTTON", "INPUT", "SELECT", "TEXTAREA"])
    assert.equal(isMediaExportInteractive(tag), true);
  assert.equal(isMediaExportInteractive("DIV"), false);
  controller.dispose();
});

test("a known posted job keeps a per-card unavailable error when its first status read fails", async () => {
  const controller = createExportController({
    api: {
      request(method, path) {
        if (path === "/api/jobs") return Promise.resolve([]);
        if (method === "post") return Promise.resolve(job());
        throw Object.assign(new Error("login required"), { status: 401 });
      },
    },
  });
  controller.select(request.videoId);
  await controller.start(request, () => ({
    videoId: request.videoId,
    revision: 2,
    dirty: false,
    saving: false,
  }));
  assert.equal(controller.getSnapshot().jobs[0].available, false);
  assert.match(
    controller.getSnapshot().jobs[0].unavailableReason,
    /login required/,
  );
  controller.dispose();
});
