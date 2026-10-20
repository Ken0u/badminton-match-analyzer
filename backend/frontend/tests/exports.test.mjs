import test from "node:test";
import assert from "node:assert/strict";
import {
  ExportPayloadError,
  parseExportStatus,
  parseRecoveredExports,
} from "../.test-build/editor/exports/model.js";
import { createExportController } from "../.test-build/editor/exports/controller.js";
import { isMediaExportInteractive } from "../.test-build/editor/exports/ExportPanel.js";

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
