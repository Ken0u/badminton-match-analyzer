import test from "node:test";
import assert from "node:assert/strict";
import {
  frameAt,
  parseDocument,
  parseRun,
  parseTimes,
  parseVideo,
  displayCalibrations,
  courtSignature,
  cameraChanged,
  courtChanged,
  contextSignature,
  ownedCandidates,
  bounds,
} from "../.test-build/editor/model.js";
const doc = () =>
  parseDocument({
    mode: "singles",
    players: [{ id: "P1", name: "First", team: "T1", handedness: "unknown" }],
    revision: 2,
    calibrations: [
      {
        start_frame: 0,
        end_frame: 10,
        corners: [
          { x: 0.1, y: 0.1 },
          { x: 0.9, y: 0.1 },
          { x: 0.9, y: 0.9 },
          { x: 0.1, y: 0.9 },
        ],
      },
    ],
    events: [
      {
        id: "e",
        rally_id: "R1",
        frame: 2,
        kind: "shot",
        family: "unknown",
        side: "unknown",
        source_run_id: "original",
        candidate_id: "candidate",
        family_score: null,
      },
    ],
    shuttle_points: [],
  });
test("native timestamp clock preserves VFR, exact boundaries, and physical gaps", () => {
  const pts = [0, 0.04, 0.12, 0.68];
  assert.deepEqual(parseTimes(pts, 4), pts);
  assert.equal(frameAt(pts, 0.11998), 1);
  assert.equal(frameAt(pts, 0.12), 2);
  assert.equal(frameAt(pts, 0.67), 2);
  assert.equal(frameAt(pts, 0.68), 3);
  assert.equal(frameAt(pts, 99), 3);
  for (const v of [
    [0, NaN],
    [0, -1],
    [0, 0.2, 0.1],
  ])
    assert.throws(() => parseTimes(v, v.length));
  assert.throws(() => parseTimes(pts, 5));
});
test("annotation parsing keeps unknown labels and original source predictions immutable", () => {
  const input = doc();
  input.extra = { original_prediction: { family: "clear", score: 0.8 } };
  const parsed = parseDocument(input);
  parsed.events[0].family = "smash";
  assert.equal(input.events[0].family, "unknown");
  assert.equal(parsed.events[0].source_run_id, "original");
  assert.deepEqual(parsed.extra, input.extra);
  assert.notEqual(parsed.extra, input.extra);
});
test("malformed annotation truth cannot enter actionable editor state", () => {
  for (const mutate of [
    (d) => {
      d.events[0].frame = -1;
    },
    (d) => {
      d.events[0].family = "half_smash";
    },
    (d) => {
      d.players[0].team = "other";
    },
    (d) => {
      d.shuttle_points = [{ frame: 0, visible: true, x: NaN, y: 0.1 }];
    },
    (d) => {
      d.camera_corrections = [{ frame: 1, is_cut: "yes" }];
    },
    (d) => {
      d.review_windows = [{ id: "r", start_frame: 2, end_frame: 1 }];
    },
    (d) => {
      d.events.push({ ...d.events[0] });
    },
  ]) {
    const d = doc();
    mutate(d);
    assert.throws(() => parseDocument(d));
  }
});
test("court display expires at current draft cuts with no run and preserves saved calibration bytes", () => {
  const d = doc(),
    before = JSON.stringify(d.calibrations);
  d.camera_corrections = [{ frame: 4, is_cut: true }];
  const display = displayCalibrations(
    d,
    null,
    Array.from({ length: 10 }, (_, i) => i * 0.04),
    25,
    false,
  );
  assert.equal(display[0].end_frame, 4);
  assert.equal(JSON.stringify(d.calibrations), before);
  assert.equal(courtSignature(d, null, 0, 10)[0][1], 10);
  d.camera_corrections = [{ frame: 4, is_cut: false }];
  assert.equal(
    displayCalibrations(
      d,
      null,
      Array.from({ length: 10 }, (_, i) => i * 0.04),
      25,
      false,
    )[0].end_frame,
    10,
  );
});
test("timestamp gaps cannot be joined and stale automatic courts cannot display", () => {
  const d = doc();
  d.camera_corrections = [{ frame: 3, is_cut: false }];
  const run = parseRun({
    start_frame: 0,
    end_frame: 10,
    court_context_version: 1,
    raw_cut_frames: [3],
    automatic_calibrations: [
      { start_frame: 4, end_frame: 10, corners: d.calibrations[0].corners },
    ],
  });
  const output = displayCalibrations(
    d,
    run,
    [0, 0.04, 0.08, 0.68, 0.72, 0.76, 0.8, 0.84, 0.88, 0.92],
    25,
    false,
  );
  assert.equal(output[0].end_frame, 3);
  assert.equal(output.length, 1);
});
test("manual courts take priority over separate run-local automatic fits", () => {
  const d = doc();
  d.calibrations[0].end_frame = 4;
  const run = parseRun({
    start_frame: 0,
    end_frame: 10,
    court_context_version: 1,
    automatic_calibrations: [
      { start_frame: 0, end_frame: 10, corners: d.calibrations[0].corners },
    ],
  });
  const out = displayCalibrations(
    d,
    run,
    Array.from({ length: 10 }, (_, i) => i * 0.04),
    25,
    true,
  );
  assert.deepEqual(
    out.map((c) => [c.start_frame, c.end_frame, Boolean(c.automatic)]),
    [
      [0, 4, false],
      [4, 10, true],
    ],
  );
  assert.equal(d.calibrations.length, 1);
});
test("camera and court provenance includes preceding reviewed cuts", () => {
  const d = doc();
  const run = parseRun({
    start_frame: 5,
    end_frame: 10,
    known_preceding_cut_frames: [3],
    known_preceding_timestamp_gaps: [],
    preceding_reviewed_cut_frame: 3,
    applied_camera_corrections: [],
    court_context_version: 1,
  });
  assert.equal(cameraChanged(d, run), false);
  d.camera_corrections = [{ frame: 2, is_cut: true }];
  assert.equal(cameraChanged(d, run), false);
  d.camera_corrections.push({ frame: 4, is_cut: true });
  assert.equal(cameraChanged(d, run), true);
  const artifact = parseRun({
    court_context: { ...run },
    calibration_signature: courtSignature(d, run, 5, 10),
  });
  assert.equal(courtChanged(d, artifact), true);
});
test("owned full-match candidates do not duplicate overlap boundaries", () => {
  const run = parseRun({
    analysis_core_start_frame: 10,
    analysis_core_end_frame: 20,
    candidates: [
      { id: "left", frame: 9 },
      { id: "start", frame: 10 },
      { id: "last", frame: 19 },
      { id: "right", frame: 20 },
    ],
  });
  assert.deepEqual(
    ownedCandidates(run).map((c) => c.id),
    ["start", "last"],
  );
});
test("draft scene exclusion context preserves unknown ranges and original ordering", () => {
  const d = doc();
  d.scene_ranges = [
    { id: "u", start_frame: 4, end_frame: 8, scene: "unknown" },
    { id: "l", start_frame: 0, end_frame: 4, scene: "live" },
  ];
  const signature = contextSignature(d, 0, 10);
  assert.deepEqual(signature.scenes, [
    [0, 4, "live"],
    [4, 8, "unknown"],
  ]);
  assert.equal(d.scene_ranges[0].id, "u");
  assert.deepEqual(bounds("0", "10", 10), { start_frame: 0, end_frame: 10 });
  for (const v of [
    ["", "2"],
    ["2", "2"],
    ["-1", "3"],
    ["0", "11"],
  ])
    assert.throws(() => bounds(...v, 10));
});
test("invalid run geometry and candidates fail closed; source frame metadata is required", () => {
  for (const r of [
    { frames: [{ frame: 0, players: [{ box: [1, 2, 3] }] }] },
    { candidates: [{ id: "", frame: 0 }] },
    { candidates: [{ id: "x", frame: 0.5 }] },
    { frames: [{ frame: 0, shuttle: { visible: true, x: null, y: 1 } }] },
  ])
    assert.throws(() => parseRun(r));
  assert.throws(() =>
    parseVideo({
      id: "v",
      name: "n",
      mode: "singles",
      frame_count: 4,
      duration_s: 1,
      width: 64,
      height: 0,
      fps: 25,
    }),
  );
});

test("editor save uses current revision, keeps in-flight newer edits and rejects a conflict without losing them", async () => {
  const { createEditorController } =
    await import("../.test-build/editor/controller.js");
  const previousFetch = globalThis.fetch;
  let persisted = doc(),
    releaseSave,
    saveStarted;
  const started = new Promise((resolve) => {
    saveStarted = resolve;
  });
  const gate = new Promise((resolve) => {
    releaseSave = resolve;
  });
  let putCount = 0;
  const bodies = [];
  const video = {
    id: "v",
    name: "owned",
    mode: "singles",
    duration_s: 0.4,
    frame_count: 10,
    width: 64,
    height: 128,
    fps: 25,
  };
  globalThis.fetch = async (url, options = {}) => {
    const pathname = String(url).split("?")[0];
    const response = (v, status = 200) =>
      new Response(JSON.stringify(v), {
        status,
        headers: { "Content-Type": "application/json" },
      });
    if (pathname === "/api/videos") return response([video]);
    if (pathname === "/api/jobs") return response([]);
    if (pathname.endsWith("/playback"))
      return response({ status: "missing", url: null });
    if (pathname.endsWith("/timestamps"))
      return response(Array.from({ length: 10 }, (_, i) => i * 0.04));
    if (pathname.endsWith("/annotations")) {
      if (options.method === "PUT") {
        const body = JSON.parse(options.body);
        bodies.push(body);
        putCount++;
        if (putCount === 1) {
          saveStarted();
          await gate;
          persisted = { ...body, revision: 3 };
          return response(persisted);
        }
        return response(
          {
            detail:
              "Annotations changed in another window. Reload before saving.",
          },
          409,
        );
      }
      return response(persisted);
    }
    return response(video);
  };
  try {
    const controller = createEditorController();
    await controller.select("v");
    controller.edit((d) => ({
      ...d,
      players: d.players.map((p) => ({ ...p, name: "Earlier" })),
    }));
    const saving = controller.save();
    await started;
    controller.edit((d) => ({
      ...d,
      players: d.players.map((p) => ({ ...p, name: "Newer" })),
    }));
    releaseSave();
    await saving;
    assert.equal(persisted.players[0].name, "Earlier");
    assert.equal(
      controller.drafts.getSnapshot().value.players[0].name,
      "Newer",
    );
    assert.equal(controller.drafts.getSnapshot().revision, 3);
    assert.equal(controller.drafts.getSnapshot().dirty, true);
    await controller.save();
    assert.equal(bodies[1].revision, 3);
    assert.equal(
      controller.drafts.getSnapshot().value.players[0].name,
      "Newer",
    );
    assert.equal(controller.drafts.getSnapshot().dirty, true);
    assert.equal(controller.drafts.getSnapshot().saving, false);
    assert.match(controller.snapshot().notice, /another window/);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("editor ignores late selected resource success and preserves newer video geometry and draft", async () => {
  const { createEditorController } =
    await import("../.test-build/editor/controller.js");
  const previousFetch = globalThis.fetch;
  let release, entered;
  const gate = new Promise((resolve) => {
      release = resolve;
    }),
    started = new Promise((resolve) => {
      entered = resolve;
    });
  const video = (id) => ({
    id,
    name: id,
    mode: "singles",
    duration_s: 0.4,
    frame_count: 10,
    width: id === "a" ? 64 : 128,
    height: id === "a" ? 128 : 64,
    fps: 25,
  });
  globalThis.fetch = async (url) => {
    const p = String(url).split("?")[0],
      reply = (v) => new Response(JSON.stringify(v));
    if (p === "/api/videos") return reply([video("a"), video("b")]);
    if (p === "/api/jobs") return reply([]);
    const id = p.includes("/videos/a") ? "a" : "b";
    if (p.endsWith("/annotations")) {
      if (id === "a") {
        entered();
        await gate;
      }
      return reply(doc());
    }
    if (p.endsWith("/timestamps"))
      return reply(Array.from({ length: 10 }, (_, i) => i * 0.04));
    if (p.endsWith("/playback")) return reply({ status: "missing", url: null });
    return reply(video(id));
  };
  try {
    const controller = createEditorController();
    const first = controller.select("a");
    await started;
    await controller.select("b");
    release();
    await first;
    assert.equal(controller.snapshot().video.id, "b");
    assert.equal(controller.snapshot().video.width, 128);
    assert.equal(controller.drafts.getSnapshot().owner.id, "b");
    assert.deepEqual(controller.snapshot().runs, {});
  } finally {
    globalThis.fetch = previousFetch;
  }
});

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}
async function eventually(predicate, message) {
  const deadline = Date.now() + 2000;
  while (!predicate()) {
    if (Date.now() > deadline) assert.fail(message);
    await new Promise((resolve) => setTimeout(resolve, 1));
  }
}

test("review view changes fence delayed analysis, run and playback responses and errors", async (t) => {
  const { createEditorController } =
    await import("../.test-build/editor/controller.js");
  for (const boundary of ["analysis", "run", "playback"])
    for (const action of ["review", "cross-core", "leave", "track"])
      for (const staleFailure of [false, true])
        await t.test(
          `${action} during ${boundary}: stale ${staleFailure ? "error" : "success"}`,
          async () => {
            const previousFetch = globalThis.fetch;
            const annotation = parseDocument({
              mode: "singles",
              players: [{ id: "P1", name: "Player", team: "T1" }],
              revision: 0,
            });
            const video = {
              id: "v",
              name: "view-owned",
              mode: "singles",
              duration_s: 1,
              frame_count: 10,
              width: 64,
              height: 32,
              fps: 10,
            };
            const analysisJob = {
              id: "analysis",
              video_id: "v",
              kind: "analysis",
              status: "completed",
              progress: 1,
            };
            let generation = "old",
              armed = false,
              used = false;
            const started = deferred(),
              release = deferred();
            const playerId = (part) => `players-${part}-${generation}`;
            const job = (part) => ({
              id: playerId(part),
              video_id: "v",
              kind: "players",
              status: "completed",
              progress: 1,
              analysis_key: part === "manual" ? null : "analysis",
              summary: {
                start_frame: part === 1 ? 5 : 0,
                end_frame: part === 0 ? 5 : 10,
              },
            });
            const plan = () => ({
              job: analysisJob,
              state: "completed",
              requires_processing_rerun: false,
              recipe: {
                context_signature: contextSignature(annotation, 0, 10),
              },
              parts: [0, 1].map((index) => ({
                window: {
                  index,
                  core_start_frame: index * 5,
                  core_end_frame: (index + 1) * 5,
                },
                stages: { players: { run_id: playerId(index) } },
              })),
            });
            globalThis.fetch = async (url, options = {}) => {
              const p = String(url).split("?")[0];
              const delayed =
                boundary === "analysis"
                  ? p.endsWith("/analysis/analysis")
                  : boundary === "run"
                    ? p.includes("/runs/")
                    : p.endsWith("/playback");
              if (armed && !used && delayed && options.method !== "POST") {
                used = true;
                started.resolve();
                // Deliberately ignore AbortSignal so publication, not transport cooperation, is tested.
                await release.promise;
                if (staleFailure) throw Error(`obsolete ${boundary} failure`);
              }
              let value;
              if (options.method === "POST")
                value = { id: "new-window-tracking" };
              else if (p === "/api/videos") value = [video];
              else if (p === "/api/jobs")
                value = [analysisJob, job(0), job(1), job("manual")];
              else if (p.endsWith("/annotations")) value = annotation;
              else if (p.endsWith("/timestamps"))
                value = Array.from({ length: 10 }, (_, i) => i / 10);
              else if (p.endsWith("/analysis/analysis")) value = plan();
              else if (p.includes("/runs/")) {
                const manual = p.includes("manual"),
                  part = p.includes("players-1") ? 1 : 0;
                value = {
                  start_frame: manual ? 0 : part * 5,
                  end_frame: manual ? 10 : (part + 1) * 5,
                  frames: [],
                };
              } else if (p.endsWith("/playback"))
                value = { status: "missing", url: null };
              else value = video;
              return new Response(JSON.stringify(value));
            };
            try {
              const c = createEditorController();
              await c.select("v");
              assert.equal(c.snapshot().partIndex, 0);
              generation = "next";
              armed = true;
              const pending = c.refresh();
              await started.promise;
              const manual = action === "leave" || action === "track",
                expectedPart = manual ? null : 1;
              const history = [];
              const unsubscribe = c.subscribe(() =>
                history.push(structuredClone(c.snapshot())),
              );
              if (action === "review") c.reviewPart(1);
              else if (action === "cross-core") c.setFrame(6);
              else if (action === "leave") c.leave();
              else
                c.track("players", { duration: 1, model: "small", auto: true });
              c.notice("Current view notice");
              // Current-view loading must finish while the obsolete transport
              // remains stalled and deliberately ignores cancellation.
              await eventually(
                () =>
                  c.snapshot().runs.players?.id ===
                  playerId(manual ? "manual" : 1),
                "The obsolete request blocked the current review view",
              );
              release.resolve();
              await pending;
              await eventually(
                () =>
                  c.snapshot().runs.players?.id ===
                  playerId(manual ? "manual" : 1),
                "Fresh poll did not load the current view's player run",
              );
              unsubscribe();
              assert.equal(c.snapshot().partIndex, expectedPart);
              assert.equal(c.snapshot().analysisEnabled, !manual);
              assert.equal(c.snapshot().error, false);
              assert.doesNotMatch(c.snapshot().notice, /obsolete/);
              for (const s of history) {
                assert.equal(
                  s.partIndex,
                  expectedPart,
                  "No transient stale window may be published",
                );
                assert.equal(
                  s.analysisEnabled,
                  !manual,
                  "No transient stale mode may be published",
                );
                if (s.runs.players)
                  assert.equal(
                    s.runs.players.id,
                    playerId(manual ? "manual" : 1),
                    "Runs must belong to the current review view",
                  );
                assert.equal(
                  s.error,
                  false,
                  "Late errors must not replace current-view feedback",
                );
              }
              if (!manual)
                assert.equal(
                  c.playback.getSnapshot().sourceFrame,
                  action === "review" ? 5 : 6,
                );
            } finally {
              release.resolve();
              globalThis.fetch = previousFetch;
            }
          },
        );
});
