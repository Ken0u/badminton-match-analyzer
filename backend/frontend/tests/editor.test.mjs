import test from "node:test";
import assert from "node:assert/strict";
import {
  frameAt,
  parseDocument,
  parseRun,
  parseTimes,
  parseVideo,
  displayCalibrations,
  displayShuttle,
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

const shuttlePoint = (frame) => ({ x: frame * 7 + 3, y: frame * 5 + 2 });
function shuttleFixture(metadata = {}, annotations = {}) {
  return {
    labels: { ...doc(), ...annotations },
    run: {
      start_frame: 0,
      end_frame: 20,
      frames: Array.from({ length: 20 }, (_, frame) => ({
        frame,
        shuttle: { visible: true, ...shuttlePoint(frame) },
      })),
      ...metadata,
    },
    times: Array.from({ length: 20 }, (_, frame) => frame / 25),
  };
}
const trace = (fixture, frame = 5) =>
  displayShuttle(fixture.labels, fixture.run, fixture.times, 25, frame);
const points = (start, end) =>
  Array.from({ length: end - start }, (_, i) => shuttlePoint(start + i));

for (const [name, metadata, annotations] of [
  ["automatic cut", { cut_frames: [3] }, {}],
  ["raw cut", { raw_cut_frames: [3], cut_frames: [] }, {}],
  ["reviewed cut", {}, { camera_corrections: [{ frame: 3, is_cut: true }] }],
  ["preceding cut", { known_preceding_cut_frames: [3] }, {}],
  ["legacy preceding cut", { preceding_reviewed_cut_frame: 3 }, {}],
  [
    "gap metadata",
    { boundaries: [{ frame: 3, reason: "timestamp_discontinuity" }] },
    {},
  ],
  ["preceding gap", { known_preceding_timestamp_gaps: [3] }, {}],
  [
    "scene start",
    {},
    { scene_ranges: [{ start_frame: 3, end_frame: 8, scene: "replay" }] },
  ],
  [
    "scene end",
    {},
    { scene_ranges: [{ start_frame: 0, end_frame: 3, scene: "unknown" }] },
  ],
]) {
  test(`shuttle display removes all earlier-view history at ${name}`, () => {
    const fixture = shuttleFixture(metadata, annotations);
    const before = structuredClone(fixture);
    assert.deepEqual(trace(fixture), {
      segments: [points(3, 6)],
      current: shuttlePoint(5),
    });
    assert.deepEqual(fixture, before);
  });
}
test("shuttle display honors cut removals and ignores future boundaries", () => {
  const fixture = shuttleFixture(
    { raw_cut_frames: [3, 8], cut_frames: [3, 8] },
    { camera_corrections: [{ frame: 3, is_cut: false }] },
  );
  assert.deepEqual(trace(fixture).segments, [points(0, 6)]);
  fixture.labels.camera_corrections.push({ frame: 4, is_cut: true });
  assert.deepEqual(trace(fixture).segments, [points(4, 6)]);
});
test("shuttle display cannot remove native time gaps with a camera correction", () => {
  const fixture = shuttleFixture(
    {},
    {
      camera_corrections: [{ frame: 3, is_cut: false }],
    },
  );
  fixture.times = fixture.times.map(
    (time, frame) => time + (frame >= 3 ? 1 : 0),
  );
  assert.deepEqual(trace(fixture).segments, [points(3, 6)]);
  assert.equal(
    displayCalibrations(
      fixture.labels,
      fixture.run,
      fixture.times,
      25,
      false,
    )[0].end_frame,
    3,
  );
});
test("shuttle display keeps VFR and legacy continuous paths in source pixels", () => {
  const fixture = shuttleFixture();
  fixture.times = [
    0,
    0.02,
    0.07,
    0.1,
    0.15,
    0.21,
    ...fixture.times.slice(6).map((t) => t + 0.1),
  ];
  assert.deepEqual(trace(fixture), {
    segments: [points(0, 6)],
    current: shuttlePoint(5),
  });
  assert.deepEqual(trace(shuttleFixture(), 19).segments, [points(7, 20)]);
});
test("a boundary without an observation still removes prior-view history", () => {
  const fixture = shuttleFixture({ cut_frames: [3] });
  fixture.run.frames = fixture.run.frames.filter((row) => row.frame !== 3);
  assert.deepEqual(trace(fixture).segments, [points(4, 6)]);
  assert.deepEqual(trace(fixture, 3), { segments: [], current: null });
});
for (const [name, value] of [
  ["missing", undefined],
  ["invisible", { visible: false, x: null, y: null }],
  ["null", { visible: true, x: null, y: 12 }],
  ["nonfinite", { visible: true, x: NaN, y: 12 }],
  ["infinite", { visible: true, x: 12, y: Infinity }],
  ["nonnumeric", { visible: true, x: "12", y: 12 }],
]) {
  test(`shuttle display breaks at ${name} observations without invented coordinates`, () => {
    const fixture = shuttleFixture();
    fixture.run.frames[3].shuttle = value;
    assert.deepEqual(trace(fixture).segments, [points(0, 3), points(4, 6)]);
    assert.deepEqual(trace(fixture, 3), {
      segments: [points(0, 3)],
      current: null,
    });
  });
}
test("shuttle display respects source and run edges", () => {
  const fixture = shuttleFixture();
  assert.deepEqual(trace(fixture, 0), {
    segments: [[shuttlePoint(0)]],
    current: shuttlePoint(0),
  });
  fixture.run.start_frame = 3;
  fixture.run.end_frame = 8;
  assert.deepEqual(trace(fixture).segments, [points(3, 6)]);
  for (const frame of [-1, 2, 8, 20, 1.5, NaN])
    assert.deepEqual(trace(fixture, frame), { segments: [], current: null });
  fixture.run = null;
  assert.deepEqual(trace(fixture), { segments: [], current: null });
});
async function actorFixture() {
  const { createEditorController } =
    await import("../.test-build/editor/controller.js");
  const previousFetch = globalThis.fetch;
  const annotation = parseDocument({
    mode: "singles",
    revision: 0,
    players: [{ id: "p", name: "Generated", team: "T1" }],
    track_assignments: [
      {
        run_id: "players",
        track_id: 1,
        player_id: "p",
        start_frame: 0,
        end_frame: 10,
      },
    ],
  });
  let source = "v",
    manifest = "old",
    identities = { run_id: "actors-old" },
    stale = false,
    hold = null;
  const requests = [];
  const video = (id) => ({
    id,
    name: "generated",
    mode: "singles",
    duration_s: 1,
    frame_count: 10,
    width: 64,
    height: 32,
    fps: 10,
  });
  const job = (id, kind, video_id = source) => ({
    id,
    video_id,
    kind,
    status: "completed",
    progress: 1,
    analysis_key: kind === "analysis" ? null : manifest,
  });
  const actor = (label) => ({
    run_id: "players",
    track_id: 1,
    label,
    linked_across_windows: true,
    observation_ranges: [[0, 10]],
  });
  globalThis.fetch = async (url, options = {}) => {
    const path = String(url).split("?")[0];
    requests.push({ path, method: options.method ?? "GET" });
    const id = path.split("/")[3];
    let value;
    if (path === "/api/videos") value = [video("v"), video("w")];
    else if (path === "/api/jobs")
      value = [job(manifest, "analysis"), job("players", "players")];
    else if (path.endsWith("/annotations")) value = annotation;
    else if (path.endsWith("/timestamps"))
      value = Array.from({ length: 10 }, (_, i) => i / 10);
    else if (path.includes("/analysis/"))
      value = {
        job: job(manifest, "analysis", id),
        state: "completed",
        requires_processing_rerun: false,
        recipe: { context_signature: contextSignature(annotation, 0, 10) },
        parts: [0, 1].map((index) => ({
          window: {
            index,
            core_start_frame: index * 5,
            core_end_frame: (index + 1) * 5,
          },
          stages: { players: { run_id: "players" } },
        })),
        ...(identities === undefined ? {} : { identities }),
      };
    else if (path.includes("/runs/actors-")) {
      value = {
        requires_context_rerun: stale,
        tracks: [actor(path.endsWith("actors-new") ? "Actor B" : "Actor A")],
      };
      if (hold) {
        const pending = hold;
        hold = null;
        pending.entered.resolve();
        await pending.release.promise;
        if (pending.fail) throw Error("Obsolete actor read failed");
      }
    } else if (path.endsWith("/runs/players"))
      value = {
        start_frame: 0,
        end_frame: 10,
        frames: [
          {
            frame: 0,
            players: [{ track_id: 1, box: [1, 1, 20, 20], confidence: 0.9 }],
          },
        ],
      };
    else if (path.endsWith("/playback"))
      value = { status: "missing", url: null };
    else value = video(id);
    return new Response(JSON.stringify(value));
  };
  const c = createEditorController();
  await c.select(source);
  return {
    c,
    annotation,
    requests,
    replace(next, options = {}) {
      identities = next;
      manifest = options.manifest ?? "replacement";
      stale = options.stale ?? false;
    },
    source(id) {
      source = id;
    },
    pending(fail = false) {
      hold = { entered: deferred(), release: deferred(), fail };
      return hold;
    },
    close() {
      globalThis.fetch = previousFetch;
    },
  };
}

test("actor hints clear when the current manifest has no usable identity result", async (t) => {
  for (const [name, identities, stale] of [
    ["absent", undefined],
    ["null", null],
    ["empty", {}],
    ["missing run ID", { linked_actor_count: 1 }],
    ["empty run ID", { run_id: "" }],
    ["stale identity context", { run_id: "actors-old" }, true],
  ])
    await t.test(name, async () => {
      const f = await actorFixture();
      try {
        assert.equal(f.c.snapshot().actors[0].label, "Actor A");
        const saved = structuredClone(f.c.drafts.getSnapshot().value);
        f.replace(identities, { stale });
        await f.c.refresh();
        const s = f.c.snapshot();
        assert.equal(s.plan.job.id, "replacement");
        assert.equal(s.analysisEnabled, true);
        assert.equal(
          s.runs.players.id,
          "players",
          "Player stages may be reused across manifests",
        );
        assert.deepEqual(
          s.actors,
          [],
          "The old actor label must no longer be eligible for the overlay",
        );
        assert.deepEqual(
          f.c.drafts.getSnapshot().value,
          saved,
          "Reviewed assignments and saved truth survive",
        );
        assert.equal(f.c.drafts.getSnapshot().dirty, false);
        assert.ok(
          f.requests.every((r) => r.method.toUpperCase() === "GET"),
          "Refreshing must never recompute links",
        );
      } finally {
        f.close();
      }
    });
});

test("current actor hints survive stable polls and change only to the current identity result", async () => {
  const f = await actorFixture();
  try {
    const actors = f.c.snapshot().actors;
    await f.c.refresh();
    assert.deepEqual(f.c.snapshot().actors, actors);
    f.replace({ run_id: "actors-new" });
    await f.c.refresh();
    assert.equal(f.c.snapshot().actors[0].label, "Actor B");
    await f.c.refresh();
    assert.equal(f.c.snapshot().actors[0].label, "Actor B");
  } finally {
    f.close();
  }
});

test("obsolete actor success and errors cannot cross view or source ownership", async (t) => {
  for (const action of ["view", "source"])
    for (const fail of [false, true])
      await t.test(
        `${action}: late ${fail ? "error" : "success"}`,
        async () => {
          const f = await actorFixture(),
            held = f.pending(fail);
          try {
            const pending = f.c.refresh();
            await held.entered.promise;
            f.replace(undefined);
            if (action === "source") {
              f.source("w");
              await f.c.select("w");
            } else {
              f.c.reviewPart(1);
              await eventually(
                () => f.c.snapshot().plan?.job.id === "replacement",
                "Current view did not finish independently of the obsolete actor read",
              );
            }
            assert.deepEqual(f.c.snapshot().actors, []);
            held.release.resolve();
            await pending;
            assert.deepEqual(f.c.snapshot().actors, []);
            assert.equal(f.c.snapshot().error, false);
            assert.doesNotMatch(f.c.snapshot().notice, /Obsolete actor/);
            assert.equal(
              f.c.snapshot().video.id,
              action === "source" ? "w" : "v",
            );
          } finally {
            held.release.resolve();
            f.close();
          }
        },
      );
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

test("first analysis publication follows seeks while initial derived reads are pending", async (t) => {
  const { createEditorController } =
    await import("../.test-build/editor/controller.js");
  for (const boundary of ["run", "playback"])
    for (const sequence of [[6], [6, 1, 8], [6, 1]])
      for (const staleFailure of [false, true]) {
        // A failure for a core that is still current is a real current error.
        if (staleFailure && sequence.at(-1) < 5) continue;
        await t.test(
          `${boundary}: seek ${sequence.join(" → ")}, late ${staleFailure ? "error" : "success"}`,
          async () => {
            const previousFetch = globalThis.fetch;
            const annotation = parseDocument({
              mode: "singles",
              players: [{ id: "p", name: "Player", team: "T1" }],
              revision: 0,
            });
            const video = {
              id: "v",
              name: "initial-load",
              mode: "singles",
              duration_s: 1,
              frame_count: 10,
              width: 64,
              height: 32,
              fps: 10,
            };
            const analysis = {
              id: "analysis",
              video_id: "v",
              kind: "analysis",
              status: "completed",
              progress: 1,
            };
            const jobs = [
              analysis,
              ...[0, 1].map((index) => ({
                id: `players${index}`,
                video_id: "v",
                kind: "players",
                status: "completed",
                progress: 1,
                analysis_key: "analysis",
              })),
            ];
            const plan = {
              job: analysis,
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
                stages: { players: { run_id: `players${index}` } },
              })),
            };
            const entered = deferred(),
              release = deferred();
            let held = false;
            globalThis.fetch = async (url) => {
              const p = String(url).split("?")[0];
              if (
                !held &&
                (boundary === "run"
                  ? p.includes("/runs/")
                  : p.endsWith("/playback"))
              ) {
                held = true;
                entered.resolve();
                await release.promise;
                if (staleFailure) throw Error("Obsolete initial core failed");
              }
              let value;
              if (p === "/api/videos") value = [video];
              else if (p === "/api/jobs") value = jobs;
              else if (p.endsWith("/annotations")) value = annotation;
              else if (p.endsWith("/timestamps"))
                value = Array.from({ length: 10 }, (_, i) => i / 10);
              else if (p.endsWith("/analysis/analysis")) value = plan;
              else if (p.includes("/runs/")) {
                const index = p.endsWith("players1") ? 1 : 0;
                value = {
                  start_frame: index * 5,
                  end_frame: (index + 1) * 5,
                  frames: [],
                };
              } else if (p.endsWith("/playback"))
                value = { status: "missing", url: null };
              else value = video;
              return new Response(JSON.stringify(value));
            };
            try {
              const c = createEditorController(),
                selecting = c.select("v");
              await entered.promise;
              assert.equal(
                c.snapshot().plan,
                null,
                "Regression must begin before the first plan is installed",
              );
              for (const frame of sequence) c.setFrame(frame);
              c.notice("Current source review");
              const frame = sequence.at(-1),
                expected = frame < 5 ? 0 : 1,
                history = [];
              const unsubscribe = c.subscribe(() =>
                history.push(structuredClone(c.snapshot())),
              );
              release.resolve();
              await selecting;
              await eventually(
                () => c.snapshot().runs.players?.id === `players${expected}`,
                "Initial derived results did not converge on the current native core",
              );
              await c.refresh();
              unsubscribe();
              assert.equal(c.playback.getSnapshot().sourceFrame, frame);
              assert.equal(c.snapshot().partIndex, expected);
              assert.equal(c.snapshot().error, false);
              assert.doesNotMatch(c.snapshot().notice, /Obsolete/);
              for (const state of history)
                if (state.runs.players) {
                  assert.equal(
                    state.partIndex,
                    expected,
                    "No first-load old core may be published",
                  );
                  assert.equal(
                    state.runs.players.id,
                    `players${expected}`,
                    "Initial run belongs to another source core",
                  );
                }
            } finally {
              release.resolve();
              globalThis.fetch = previousFetch;
            }
          },
        );
      }
});

// All inputs below are generated. Deferred transports deliberately ignore abort
// so response ownership must hold even when cancellation cannot stop a reply.
async function evaluationFixture({ analysis = false } = {}) {
  const { createEditorController } =
    await import("../.test-build/editor/controller.js");
  const previousFetch = globalThis.fetch,
    previousWindow = globalThis.window;
  const annotation = parseDocument({
    mode: "singles",
    revision: 2,
    players: [{ id: "P1", name: "Generated", team: "T1" }],
  });
  const stages = [
    "players",
    "shuttle",
    "contacts",
    "recognition",
    "rallies",
    "segments",
  ];
  const versions = Object.fromEntries(stages.map((stage) => [stage, 0]));
  const missing = new Set(),
    queued = [],
    requests = [];
  let playbackReady = false;
  const runId = (stage, part = "manual") =>
    `${stage}-${versions[stage]}-${part}`;
  const video = (id) => ({
    id,
    name: id,
    mode: "singles",
    duration_s: 1,
    frame_count: 10,
    width: 64,
    height: 32,
    fps: 10,
  });
  const analysisJob = (id) => ({
    id: `analysis-${id}`,
    video_id: id,
    kind: "analysis",
    status: "completed",
    progress: 1,
  });
  const jobs = (id) => [
    ...(analysis ? [analysisJob(id)] : []),
    ...["manual", ...(analysis ? [0, 1] : [])].flatMap((part) =>
      stages
        .filter((stage) => !missing.has(stage))
        .map((stage) => ({
          id: runId(stage, part),
          video_id: id,
          kind: stage,
          status: "completed",
          progress: 1,
          analysis_key: part === "manual" ? null : `analysis-${id}`,
          summary: {
            player_run_id: runId("players", part),
            shuttle_run_id: runId("shuttle", part),
          },
        })),
    ),
  ];
  globalThis.window = {
    confirm: () => true,
    setInterval: () => 1,
    clearInterval() {},
  };
  globalThis.fetch = async (url, options = {}) => {
    const p = String(url).split("?")[0],
      id = p.match(/\/api\/videos\/([^/]+)/)?.[1] ?? "generated";
    let value;
    if (p.endsWith("/evaluate")) {
      const body = JSON.parse(options.body),
        number = requests.length + 1;
      requests.push({ id, body });
      value = {
        video_id: id,
        video_sha256: "a".repeat(64),
        annotation_revision: annotation.revision,
        measurement: number,
      };
      for (const stage of ["contacts", "shuttle", "recognition", "rallies"])
        if (body[`${stage}_run_id`])
          value[stage] = {
            run_id: body[`${stage}_run_id`],
            metrics: { f1: 0.9 },
          };
      const next = queued.shift();
      if (next) {
        next.entered.resolve();
        await next.release.promise;
        if (next.failure) throw Error("Obsolete evaluation transport failed");
        if (next.mutate) value = next.mutate(value);
      }
    } else if (p === "/api/videos")
      value = [video("generated"), video("other")];
    else if (p === "/api/jobs")
      value = [...jobs("generated"), ...jobs("other")];
    else if (p.endsWith("/annotations")) {
      if (options.method === "PUT")
        Object.assign(annotation, JSON.parse(options.body), {
          revision: annotation.revision + 1,
        });
      value = annotation;
    } else if (p.endsWith("/timestamps"))
      value = Array.from({ length: 10 }, (_, i) => i / 10);
    else if (p.includes("/analysis/"))
      value = {
        job: analysisJob(id),
        state: "completed",
        requires_processing_rerun: false,
        recipe: { context_signature: contextSignature(annotation, 0, 10) },
        parts: [0, 1].map((index) => ({
          window: {
            index,
            core_start_frame: index * 5,
            core_end_frame: (index + 1) * 5,
          },
          stages: Object.fromEntries(
            stages.map((stage) => [stage, { run_id: runId(stage, index) }]),
          ),
        })),
      };
    else if (p.includes("/runs/"))
      value = { start_frame: 0, end_frame: 10, frames: [] };
    else if (p.endsWith("/playback"))
      value = playbackReady
        ? { status: "ready", url: `/api/videos/${id}/playback/media` }
        : { status: "missing", url: null };
    else if (options.method === "POST") value = { id: "generated-command" };
    else value = video(id);
    return new Response(JSON.stringify(value));
  };
  const c = createEditorController(),
    stop = c.start();
  await c.select("generated");
  return {
    c,
    versions,
    missing,
    requests,
    runId,
    playbackReady() {
      playbackReady = true;
    },
    pending(options = {}) {
      const item = { entered: deferred(), release: deferred(), ...options };
      queued.push(item);
      return item;
    },
    dispose: stop,
    close() {
      for (const item of queued) item.release.resolve();
      stop();
      globalThis.fetch = previousFetch;
      if (previousWindow === undefined) delete globalThis.window;
      else globalThis.window = previousWindow;
    },
  };
}

test("evaluation reports follow each evaluated run replacement and removal without another POST", async (t) => {
  for (const stage of ["contacts", "shuttle", "recognition", "rallies"])
    for (const change of ["replace", "remove"])
      await t.test(`${stage}: ${change}`, async () => {
        const f = await evaluationFixture();
        try {
          await f.c.evaluate();
          assert.equal(f.c.snapshot().report[stage].run_id, f.runId(stage));
          if (change === "replace") f.versions[stage]++;
          else f.missing.add(stage);
          await f.c.refresh();
          assert.equal(f.c.snapshot().report, null);
          assert.equal(
            f.requests.length,
            1,
            "Input changes must never trigger an evaluation POST",
          );
        } finally {
          f.close();
        }
      });
});

test("evaluation survives identical polling, same-core frame ticks and unrelated results", async () => {
  const f = await evaluationFixture({ analysis: true });
  try {
    await f.c.evaluate();
    const report = f.c.snapshot().report;
    f.c.setFrame(2);
    await f.c.refresh();
    assert.equal(f.c.snapshot().report, report);
    for (const stage of ["players", "segments"]) f.versions[stage]++;
    f.playbackReady();
    await f.c.refresh();
    assert.equal(f.c.snapshot().report, report);
    assert.equal(
      f.c.snapshot().playbackUrl,
      "/api/videos/generated/playback/media",
    );
    assert.equal(f.requests.length, 1);
  } finally {
    f.close();
  }
});

test("changed inputs and ABA replacements fence late evaluation successes and errors", async (t) => {
  for (const stage of ["contacts", "shuttle", "recognition", "rallies"])
    for (const failure of [false, true])
      await t.test(
        `${stage}: late ${failure ? "error" : "success"}`,
        async () => {
          const f = await evaluationFixture();
          const held = f.pending({ failure });
          try {
            const evaluating = f.c.evaluate();
            await held.entered.promise;
            f.versions[stage]++;
            await f.c.refresh();
            f.versions[stage]--;
            await f.c.refresh();
            f.c.notice("Current input feedback");
            held.release.resolve();
            await evaluating;
            assert.equal(f.c.snapshot().report, null);
            assert.equal(f.c.snapshot().notice, "Current input feedback");
            assert.equal(f.c.snapshot().error, false);
            assert.equal(f.requests.length, 1);
          } finally {
            held.release.resolve();
            f.close();
          }
        },
      );
});

test("review core, manual mode and processing transitions remove completed evaluation reports", async (t) => {
  for (const action of ["review", "cross-core", "leave", "track", "process"])
    await t.test(action, async () => {
      const f = await evaluationFixture({ analysis: true });
      try {
        await f.c.evaluate();
        assert.ok(f.c.snapshot().report);
        if (action === "review") f.c.reviewPart(1);
        else if (action === "cross-core") f.c.setFrame(6);
        else if (action === "leave") f.c.leave();
        else if (action === "track")
          f.c.track("players", { duration: 1, model: "small", auto: true });
        else
          f.c.process({
            player_model: "small",
            auto_calibrate: true,
            recognize: true,
          });
        assert.equal(
          f.c.snapshot().report,
          null,
          "No stale report may remain during current-view loading",
        );
        await f.c.refresh();
        assert.equal(f.c.snapshot().report, null);
        assert.equal(f.requests.length, 1);
      } finally {
        f.close();
      }
    });
});

test("new edits and saved revisions fence prior evaluations without losing the draft", async () => {
  const f = await evaluationFixture();
  const held = f.pending();
  try {
    const evaluating = f.c.evaluate();
    await held.entered.promise;
    f.c.edit((d) => ({
      ...d,
      players: d.players.map((p) => ({ ...p, name: "Newest edit" })),
    }));
    assert.equal(f.c.snapshot().report, null);
    await f.c.save();
    assert.equal(f.c.drafts.getSnapshot().revision, 3);
    assert.equal(f.c.drafts.getSnapshot().value.players[0].name, "Newest edit");
    assert.equal(f.c.drafts.getSnapshot().dirty, false);
    held.release.resolve();
    await evaluating;
    assert.equal(f.c.snapshot().report, null);
    await f.c.evaluate();
    assert.equal(f.c.snapshot().report.annotation_revision, 3);
    f.c.edit((d) => ({
      ...d,
      players: d.players.map((p) => ({ ...p, name: "Later edit" })),
    }));
    assert.equal(f.c.snapshot().report, null);
    assert.equal(f.requests.length, 2);
  } finally {
    held.release.resolve();
    f.close();
  }
});

test("only the newest explicit evaluation can publish a report or an error", async (t) => {
  for (const failure of [false, true])
    await t.test(failure ? "old error" : "old success", async () => {
      const f = await evaluationFixture(),
        held = f.pending({ failure });
      try {
        const first = f.c.evaluate();
        await held.entered.promise;
        await f.c.evaluate();
        assert.equal(f.c.snapshot().report.measurement, 2);
        f.c.notice("Newest explicit evaluation");
        held.release.resolve();
        await first;
        assert.equal(f.c.snapshot().report.measurement, 2);
        assert.equal(f.c.snapshot().notice, "Newest explicit evaluation");
        assert.equal(f.c.snapshot().error, false);
        assert.equal(f.requests.length, 2);
      } finally {
        held.release.resolve();
        f.close();
      }
    });
});

test("source selection and disposal fence late evaluation replies", async (t) => {
  for (const action of ["select", "dispose"])
    for (const failure of [false, true])
      await t.test(`${action}: ${failure ? "error" : "success"}`, async () => {
        const f = await evaluationFixture(),
          held = f.pending({ failure });
        try {
          const evaluating = f.c.evaluate();
          await held.entered.promise;
          if (action === "select") {
            await f.c.select("other");
            f.c.notice("Current source feedback");
          } else f.dispose();
          const current = f.c.snapshot();
          held.release.resolve();
          await evaluating;
          assert.deepEqual(f.c.snapshot(), current);
          assert.equal(f.c.snapshot().report, null);
          assert.equal(f.requests.length, 1);
        } finally {
          held.release.resolve();
          f.close();
        }
      });
});

test("evaluation responses fail closed for mismatched source, revision and requested runs", async (t) => {
  const changes = [
    ["source", (r) => ({ ...r, video_id: "other" })],
    [
      "revision",
      (r) => ({ ...r, annotation_revision: r.annotation_revision + 1 }),
    ],
    ...["contacts", "shuttle", "recognition", "rallies"].map((stage) => [
      stage,
      (r) => ({ ...r, [stage]: { ...r[stage], run_id: "unrequested" } }),
    ]),
    [
      "missing requested result",
      (r) => {
        delete r.shuttle;
        return r;
      },
    ],
  ];
  for (const [name, mutate] of changes)
    await t.test(name, async () => {
      const f = await evaluationFixture(),
        held = f.pending({ mutate });
      try {
        const evaluating = f.c.evaluate();
        await held.entered.promise;
        held.release.resolve();
        await evaluating;
        assert.equal(f.c.snapshot().report, null);
        assert.equal(f.c.snapshot().error, true);
        assert.equal(f.requests.length, 1);
      } finally {
        held.release.resolve();
        f.close();
      }
    });
  await t.test("unexpected result category", async () => {
    const f = await evaluationFixture();
    f.missing.add("recognition");
    await f.c.refresh();
    const held = f.pending({
      mutate: (r) => ({ ...r, recognition: { run_id: "unrequested" } }),
    });
    try {
      const evaluating = f.c.evaluate();
      await held.entered.promise;
      held.release.resolve();
      await evaluating;
      assert.equal(f.c.snapshot().report, null);
      assert.equal(f.c.snapshot().error, true);
    } finally {
      held.release.resolve();
      f.close();
    }
  });
});

test("review coverage parsing preserves independent boundary declarations and rejects malformed flags", () => {
  const source = doc();
  source.review_windows = [
    {
      id: "boundary",
      start_frame: 0,
      end_frame: 10,
      scene: "live",
      contacts_complete: false,
      serves_complete: true,
      rally_ends_complete: false,
    },
  ];
  const parsed = parseDocument(source);
  assert.equal(parsed.review_windows[0].contacts_complete, false);
  assert.equal(parsed.review_windows[0].serves_complete, true);
  assert.equal(parsed.review_windows[0].rally_ends_complete, false);
  for (const serves of [false, true])
    for (const endings of [false, true]) {
      const changed = structuredClone(source);
      changed.review_windows[0].serves_complete = serves;
      changed.review_windows[0].rally_ends_complete = endings;
      const result = parseDocument(changed).review_windows[0];
      assert.equal(result.serves_complete, serves);
      assert.equal(result.rally_ends_complete, endings);
      assert.equal(result.contacts_complete, false);
    }
  const legacy = structuredClone(source);
  delete legacy.review_windows[0].serves_complete;
  delete legacy.review_windows[0].rally_ends_complete;
  const oldWindow = parseDocument(legacy).review_windows[0];
  assert.equal(oldWindow.serves_complete, undefined);
  assert.equal(oldWindow.rally_ends_complete, undefined);
  for (const flag of [
    "contacts_complete",
    "serves_complete",
    "rally_ends_complete",
  ])
    for (const invalid of [null, 0, 1, "true", {}]) {
      const changed = structuredClone(source);
      changed.review_windows[0][flag] = invalid;
      assert.throws(() => parseDocument(changed));
    }
});
