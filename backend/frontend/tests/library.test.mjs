import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient, ApiError } from "../.test-build/api/client.js";
import {
  createLibraryController,
  createLibrarySession,
} from "../.test-build/library/controller.js";
import {
  parseVideos,
  parseJob,
  parsePlayback,
  parseAnalysis,
  validateYoutube,
  errorMessage,
} from "../.test-build/library/model.js";
import { uploadVideo } from "../.test-build/library/upload.js";
const video = (id) => ({
  id,
  name: `Video ${id}`,
  mode: "singles",
  duration_s: 2,
  frame_count: 60,
});
const settings = {
  player_model: "nano",
  auto_calibrate: false,
  recognize: true,
};
const job = (id, video_id = "a", extra = {}) => ({
  id,
  video_id,
  kind: "analysis",
  status: "running",
  progress: 0.4,
  message: "Processing",
  details: { settings },
  ...extra,
});
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const spin = () => new Promise((resolve) => setTimeout(resolve, 0));
const client = (handler) =>
  createApiClient({
    fetch: async (url, init) =>
      new Response(JSON.stringify(await handler(url, init))),
  });
function server({ videos = [video("a"), video("b")], jobs = [], handle } = {}) {
  return client(async (url, init) => {
    if (handle) {
      const value = await handle(url, init);
      if (value !== undefined) return value;
    }
    if (url === "/api/videos") return videos;
    if (url === "/api/jobs") return jobs;
    if (url.endsWith("/playback")) return { status: "missing", url: null };
    if (/\/analysis\//.test(url)) {
      const id = url.split("/").at(-1);
      const j = jobs.find((j) => j.id === id);
      return {
        job: j,
        parts: [],
        state: j.status,
        requires_processing_rerun: false,
      };
    }
    return video(url.split("/").at(-1));
  });
}

test("runtime parsers reject malformed data and preserve unknown modes/job labels without inventing behavior", () => {
  assert.equal(
    parseVideos([{ ...video("a"), mode: "unknown" }])[0].mode,
    "unknown",
  );
  assert.equal(
    parseJob(job("j", "a", { status: "future-status", kind: "future-kind" }))
      .status,
    "future-status",
  );
  for (const value of [
    null,
    {},
    [video("a"), video("a")],
    [{ ...video("a"), duration_s: NaN }],
    [{ ...video("a"), frame_count: -1 }],
  ])
    assert.throws(() => parseVideos(value));
  for (const value of [
    job("j", 42),
    job("j", "a", { progress: 1.2 }),
    job("j", "a", { cancel_requested: "yes" }),
    job("j", "a", { id: "" }),
  ])
    assert.throws(() => parseJob(value));
  assert.deepEqual(parsePlayback({ status: "missing", url: null }, "a"), {
    status: "missing",
    url: null,
  });
  assert.equal(
    parsePlayback({ status: "ready", url: "/api/videos/a/playback/media" }, "a")
      .status,
    "ready",
  );
  for (const url of [
    "https://evil.test/video",
    "/api/videos/b/playback/media",
    "javascript:alert(1)",
  ])
    assert.throws(() => parsePlayback({ status: "ready", url }, "a"));
  assert.throws(() =>
    parseAnalysis(
      { job: job("j", "b"), requires_processing_rerun: false },
      "a",
      "j",
    ),
  );
  assert.throws(() =>
    parseAnalysis(
      { job: job("j"), requires_processing_rerun: "false" },
      "a",
      "j",
    ),
  );
});

test("YouTube validation allows only public single-video publisher URLs", () => {
  for (const url of [
    "https://youtu.be/abcdefghijk",
    "https://www.youtube.com/watch?v=abcdefghijk",
    "https://m.youtube.com/shorts/abcdefghijk",
  ])
    assert.equal(
      validateYoutube(url),
      "https://www.youtube.com/watch?v=abcdefghijk",
    );
  for (const url of [
    "http://youtu.be/abcdefghijk",
    "https://evil.test/watch?v=abcdefghijk",
    "https://youtube.com/watch?v=abcdefghijk&list=x",
    "https://youtu.be/abcdefghijk?v=abcdefghijk",
    "https://x:password@youtube.com/watch?v=abcdefghijk",
    "https://youtube.com:444/watch?v=abcdefghijk",
  ])
    assert.throws(() => validateYoutube(url));
});

test("late selected metadata success/error and proxy reads cannot cross selection epochs", async () => {
  for (const lateError of [false, true]) {
    const gate = deferred();
    const api = {
      request: (method, path, opts) => {
        const id = opts.path?.video_id;
        if (path.endsWith("/playback"))
          return Promise.resolve({
            status: "ready",
            url: `/api/videos/${id}/playback/media`,
          });
        if (id === "a") return gate.promise; // Deliberately ignores AbortSignal.
        return Promise.resolve(video(id));
      },
    };
    const c = createLibraryController({ api });
    const first = c.select("a");
    await c.select("b");
    if (lateError) gate.reject(new Error("old failure"));
    else gate.resolve(video("a"));
    await first;
    assert.equal(c.getSnapshot().video.id, "b");
    assert.equal(c.getSnapshot().playback.url, "/api/videos/b/playback/media");
    assert.deepEqual(c.getSnapshot().errors, {});
    c.mediaFailed("a");
    assert.deepEqual(c.getSnapshot().errors, {});
    c.dispose();
  }
});

test("shared selection session preserves a real-shaped unsaved or saving annotation draft", async () => {
  const session = createLibrarySession(),
    c = createLibraryController({ api: server(), session });
  await c.select("a");
  const owner = session.selection.current();
  const document = {
    schema_version: 1,
    revision: 2,
    mode: "singles",
    players: [
      { id: "p1", name: "Player 1", team: "T1", handedness: "unknown" },
      { id: "p2", name: "Player 2", team: "T2", handedness: "unknown" },
    ],
    events: [],
    calibrations: [],
    review_windows: [],
    shuttle_points: [],
    track_assignments: [],
    camera_corrections: [],
    scene_ranges: [],
  };
  assert.equal(session.drafts.open(owner, document, 2), true);
  session.drafts.edit((value) => ({
    ...value,
    events: [
      {
        id: "manual-contact",
        frame: 3,
        kind: "shot",
        rally_id: "r1",
        time_s: 0.1,
        status: "reviewed",
        family: "unknown",
        side: "unknown",
      },
    ],
  }));
  assert.equal(await c.select("b"), false);
  const ticket = session.drafts.beginSave();
  assert.equal(await c.select("b"), false);
  assert.equal(session.drafts.discard(), false);
  await c.refreshJobs();
  assert.equal(
    session.drafts.getSnapshot().value.events[0].id,
    "manual-contact",
  );
  session.drafts.failSave(
    ticket,
    new ApiError(409, "revision changed", "", "/"),
  );
  assert.equal(await c.select("b"), false);
  session.drafts.discard();
  assert.equal(await c.select("b"), true);
  c.dispose();
});

test("selected jobs and late processing mutations remain scoped; pause and resume use server settings", async () => {
  const submitted = [],
    jobs = [job("first")],
    gate = deferred();
  const api = server({
    jobs,
    handle: async (url, init) => {
      if (init.method === "POST") {
        submitted.push({ url, body: init.body ? JSON.parse(init.body) : null });
        if (url.endsWith("/pause")) {
          jobs[0] = job("first", "a", {
            status: "interrupted",
            cancel_requested: true,
          });
          return jobs[0];
        }
        if (url.endsWith("/analysis")) return gate.promise;
      }
    },
  });
  const c = createLibraryController({ api });
  await c.select("a");
  await c.refreshJobs();
  await c.pause();
  assert.equal(submitted[0].url, "/api/videos/a/analysis/first/pause");
  assert.equal(c.getSnapshot().analysis.job.status, "interrupted");
  const resume = c.process(c.getSnapshot().analysis.job.settings);
  await c.select("b");
  gate.resolve(job("second", "a", { status: "queued" }));
  await resume;
  assert.deepEqual(submitted[1].body, settings);
  assert.equal(c.getSnapshot().selectedId, "b");
  assert.equal(c.getSnapshot().analysis, null);
  assert.equal(c.getSnapshot().action, null);
  assert.equal(c.getSnapshot().notice, "");
  assert.equal(
    c.getSnapshot().jobs.filter((j) => j.video_id === "b").length,
    0,
  );
  c.dispose();
});

test("HTTP authentication, upload limit, admission and validation errors retain status with recovery guidance", async () => {
  for (const status of [401, 403, 413, 409, 422]) {
    const api = createApiClient({
      fetch: async () =>
        new Response(JSON.stringify({ detail: "server detail" }), { status }),
    });
    const c = createLibraryController({ api });
    await c.refreshLibrary();
    assert.match(
      c.getSnapshot().errors.library,
      new RegExp(`HTTP ${status}: server detail`),
    );
    assert.match(
      errorMessage(new ApiError(status, "detail", "", "/")),
      /Authentication|smaller|Reload|Check/,
    );
    c.dispose();
  }
});

test("import completion never selects or replaces current video and cancellation warns about server acceptance", async () => {
  const gate = deferred();
  let signal, progress;
  const c = createLibraryController({
    api: server(),
    upload: async (_file, _mode, s, p) => {
      signal = s;
      progress = p;
      return gate.promise;
    },
  });
  await c.select("a");
  const transfer = c.upload(new File(["bytes"], "match.mp4"), "doubles");
  progress({ loaded: 5, total: 20 });
  assert.deepEqual(c.getSnapshot().transfer, { loaded: 5, total: 20 });
  c.cancelUpload();
  assert.equal(signal.aborted, true);
  gate.resolve(job("import", null, { kind: "import" }));
  await transfer;
  assert.equal(c.getSnapshot().selectedId, "a");
  assert.equal(c.getSnapshot().importing, false);
  // Noncompliant transport may resolve after cancellation; still no successful import claim.
  assert.doesNotMatch(c.getSnapshot().notice, /Import queued/);
  assert.match(c.getSnapshot().notice, /server may already/);
  c.dispose();
});

test("unchanged import polls retry a failed library read without disturbing selection or drafts", async () => {
  const jobs = [],
    session = createLibrarySession();
  let reads = 0;
  const c = createLibraryController({
    session,
    api: server({
      jobs,
      handle: (url) => {
        if (url !== "/api/videos") return undefined;
        ++reads;
        if (reads === 2) throw new Error("Transient library failure");
        return reads === 1 ? [] : [video("a"), video("b")];
      },
    }),
  });
  try {
    await c.refreshLibrary();
    await c.select("b");
    session.drafts.open(session.selection.current(), { note: "saved" }, 1);
    session.drafts.edit(() => ({ note: "unsaved" }));
    jobs.push(job("import-a", "a", { kind: "import", status: "completed" }));
    await c.refreshJobs();
    assert.match(c.getSnapshot().errors.library, /Transient library failure/);
    assert.deepEqual(c.getSnapshot().videos, []);
    await c.refreshJobs();
    assert.equal(reads, 3);
    assert.deepEqual(c.getSnapshot().videos, [video("a"), video("b")]);
    assert.equal(c.getSnapshot().errors.library, undefined);
    assert.equal(c.getSnapshot().selectedId, "b");
    assert.deepEqual(session.drafts.getSnapshot().value, { note: "unsaved" });
    await c.refreshJobs();
    assert.equal(reads, 3);
  } finally {
    c.dispose();
  }
});

test("superseded import refresh success or error cannot acknowledge pending imports or clear a current error", async () => {
  for (const lateError of [false, true]) {
    const firstRead = deferred(),
      currentRead = deferred(),
      jobs = [job("import-a", "a", { kind: "import", status: "completed" })];
    let reads = 0;
    const c = createLibraryController({
      api: server({
        jobs,
        handle: (url) => {
          if (url !== "/api/videos") return undefined;
          if (++reads === 1) return firstRead.promise;
          if (reads === 2) return currentRead.promise;
          return [video("a"), video("b")];
        },
      }),
    });
    try {
      const first = c.refreshJobs();
      await spin();
      jobs.push(job("import-b", "b", { kind: "import", status: "completed" }));
      const second = c.refreshJobs();
      await spin();
      currentRead.reject(new Error("Current library failure"));
      await second;
      if (lateError) firstRead.reject(new Error("Superseded failure"));
      else firstRead.resolve([video("old")]);
      await first;
      assert.deepEqual(c.getSnapshot().videos, []);
      assert.match(c.getSnapshot().errors.library, /Current library failure/);
      await c.refreshJobs();
      assert.equal(reads, 3);
      assert.deepEqual(c.getSnapshot().videos, [video("a"), video("b")]);
      assert.equal(c.getSnapshot().errors.library, undefined);
    } finally {
      c.dispose();
    }
  }
});

test("a current library response started before a newer import does not acknowledge it", async () => {
  const oldRead = deferred(),
    playback = deferred(),
    jobs = [];
  let reads = 0,
    delayPlayback = false;
  const c = createLibraryController({
    api: server({
      jobs,
      handle: (url) => {
        if (url.endsWith("/playback") && delayPlayback) return playback.promise;
        if (url !== "/api/videos") return undefined;
        return ++reads === 1 ? oldRead.promise : [video("a"), video("b")];
      },
    }),
  });
  try {
    await c.select("b");
    const manual = c.refreshLibrary();
    jobs.push(job("import-a", "a", { kind: "import", status: "completed" }));
    delayPlayback = true;
    const poll = c.refreshJobs();
    await spin();
    oldRead.resolve([video("b")]);
    await manual;
    playback.resolve({ status: "missing", url: null });
    await poll;
    assert.equal(reads, 2);
    assert.deepEqual(c.getSnapshot().videos, [video("a"), video("b")]);
    await c.refreshJobs();
    assert.equal(reads, 2);
  } finally {
    c.dispose();
  }
});

test("repeated library failures remain visible and a current manual reload satisfies import synchronization", async () => {
  let reads = 0;
  const c = createLibraryController({
    api: server({
      jobs: [job("import-a", "a", { kind: "import", status: "completed" })],
      handle: (url) => {
        if (url !== "/api/videos") return undefined;
        if (++reads <= 2) throw new Error(`Library unavailable ${reads}`);
        return [video("a")];
      },
    }),
  });
  try {
    for (let attempt = 1; attempt <= 2; ++attempt) {
      await c.refreshJobs();
      assert.equal(reads, attempt);
      assert.match(
        c.getSnapshot().errors.library,
        new RegExp(`unavailable ${attempt}`),
      );
      assert.deepEqual(c.getSnapshot().videos, []);
    }
    await c.refreshLibrary();
    assert.equal(c.getSnapshot().errors.library, undefined);
    assert.deepEqual(c.getSnapshot().videos, [video("a")]);
    await c.refreshJobs();
    assert.equal(reads, 3);
  } finally {
    c.dispose();
  }
});

test("automatic import recovery waits for the normal polling interval and stops on disposal", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let reads = 0;
  const c = createLibraryController({
    api: server({
      jobs: [job("import-a", "a", { kind: "import", status: "completed" })],
      handle: (url) => {
        if (url !== "/api/videos") return undefined;
        ++reads;
        if (reads === 2) throw new Error("Transient polling failure");
        return reads === 1 ? [] : [video("a")];
      },
    }),
  });
  try {
    c.start();
    await new Promise(setImmediate);
    assert.equal(reads, 2);
    assert.match(c.getSnapshot().errors.library, /Transient polling failure/);
    t.mock.timers.tick(1499);
    await new Promise(setImmediate);
    assert.equal(reads, 2);
    t.mock.timers.tick(1);
    await new Promise(setImmediate);
    assert.equal(reads, 3);
    assert.deepEqual(c.getSnapshot().videos, [video("a")]);
    c.dispose();
    const snapshot = c.getSnapshot();
    t.mock.timers.tick(3000);
    await new Promise(setImmediate);
    await c.refreshJobs();
    assert.equal(reads, 3);
    assert.equal(c.getSnapshot(), snapshot);
  } finally {
    c.dispose();
    t.mock.timers.reset();
  }
});

test("disposal fences an in-flight import refresh success and failure", async () => {
  for (const lateError of [false, true]) {
    const gate = deferred();
    let reads = 0;
    const c = createLibraryController({
      api: server({
        jobs: [job("import-a", "a", { kind: "import", status: "completed" })],
        handle: (url) => {
          if (url !== "/api/videos") return undefined;
          ++reads;
          return gate.promise;
        },
      }),
    });
    const poll = c.refreshJobs();
    await spin();
    c.dispose();
    const snapshot = c.getSnapshot();
    if (lateError) gate.reject(new Error("After disposal"));
    else gate.resolve([video("a")]);
    await poll;
    await c.refreshJobs();
    assert.equal(reads, 1);
    assert.equal(c.getSnapshot(), snapshot);
  }
});

test("polling unmount aborts pending reads, clears future timers and never publishes late failures", async () => {
  const gate = deferred();
  let calls = 0,
    signal;
  const c = createLibraryController({
    pollMs: 5,
    api: {
      request: (_method, path, opts) => {
        ++calls;
        signal = opts.signal;
        return path === "/api/videos" ? Promise.resolve([]) : gate.promise;
      },
    },
  });
  c.start();
  await spin();
  c.dispose();
  const count = calls;
  assert.equal(signal.aborted, true);
  gate.reject(new Error("after unmount"));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(calls, count);
  assert.deepEqual(c.getSnapshot().errors, {});
});

test("XHR upload adapter sends multipart, same-origin cookies, true progress, status errors and abort", async () => {
  const oldXhr = globalThis.XMLHttpRequest,
    oldLocation = globalThis.location;
  let xhr;
  class FakeXHR {
    upload = {};
    headers = {};
    status = 202;
    responseText = JSON.stringify(job("i", null, { kind: "import" }));
    constructor() {
      xhr = this;
    }
    open(method, url) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(k, v) {
      this.headers[k] = v;
    }
    getResponseHeader() {
      return "application/json";
    }
    send(body) {
      this.body = body;
    }
    abort() {
      this.onabort();
    }
  }
  globalThis.XMLHttpRequest = FakeXHR;
  globalThis.location = {
    href: "http://localhost/library",
    origin: "http://localhost",
  };
  try {
    const abort = new AbortController(),
      seen = [];
    const pending = uploadVideo(
      new File(["bytes"], "match.mp4"),
      "doubles",
      abort.signal,
      (p) => seen.push(p),
    );
    assert.equal(xhr.url, "/api/upload");
    assert.equal(xhr.method, "POST");
    assert.equal(xhr.withCredentials, false);
    assert.equal(xhr.body.get("mode"), "doubles");
    assert.equal(xhr.body.get("file").name, "match.mp4");
    assert.equal(xhr.headers["content-type"], undefined);
    xhr.upload.onprogress({ loaded: 3, total: 5, lengthComputable: true });
    xhr.onload();
    await pending;
    assert.deepEqual(seen, [{ loaded: 3, total: 5 }]);
    const denied = uploadVideo(
      new File(["bytes"], "match.mp4"),
      "singles",
      new AbortController().signal,
      () => {},
    );
    xhr.status = 413;
    xhr.responseText = '{"detail":"too large"}';
    xhr.onload();
    await assert.rejects(
      denied,
      (e) => e instanceof ApiError && e.status === 413,
    );
    const controller = new AbortController();
    const cancelled = uploadVideo(
      new File(["bytes"], "match.mp4"),
      "singles",
      controller.signal,
      () => {},
    );
    controller.abort();
    await assert.rejects(cancelled, (e) => e.name === "AbortError");
  } finally {
    globalThis.XMLHttpRequest = oldXhr;
    globalThis.location = oldLocation;
  }
});

test("late playback ready/missing responses cannot cross a selection and malformed success can recover", async () => {
  for (const status of ["ready", "missing"]) {
    const gate = deferred();
    const api = {
      request: (_method, path, opts) => {
        const id = opts.path.video_id;
        if (path.endsWith("/playback"))
          return id === "a"
            ? gate.promise
            : Promise.resolve({ status: "missing", url: null });
        return Promise.resolve(video(id));
      },
    };
    const c = createLibraryController({ api });
    await c.select("a");
    await c.select("b");
    gate.resolve({
      status,
      url: status === "ready" ? "/api/videos/a/playback/media" : null,
    });
    await spin();
    assert.deepEqual(c.getSnapshot().playback, {
      status: "missing",
      url: null,
    });
    assert.equal(c.getSnapshot().selectedId, "b");
    c.dispose();
  }
  let malformed = true;
  const c = createLibraryController({
    api: server({
      handle: (url) =>
        url === "/api/videos" ? (malformed ? {} : []) : undefined,
    }),
  });
  await c.refreshLibrary();
  assert.match(c.getSnapshot().errors.library, /Invalid/);
  malformed = false;
  await c.refreshLibrary();
  assert.deepEqual(c.getSnapshot().videos, []);
  assert.equal(c.getSnapshot().errors.library, undefined);
  c.dispose();
});
