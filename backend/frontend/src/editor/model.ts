import type { components } from "../api/client.js";
import {
  parseVideo as parseLibraryVideo,
  parseJob as parseLibraryJob,
} from "../library/model.js";
export type Schema = components["schemas"];
export type Event = Schema["Event"];
export type Point = Schema["Point"];
export type Calibration = Schema["Calibration"] & { automatic?: boolean };
export type Document = Required<Schema["Annotations"]>;
export type ObjectData = Record<string, unknown>;
export function object(v: unknown, name = "resource"): ObjectData {
  if (!v || typeof v !== "object" || Array.isArray(v))
    throw Error(`Invalid ${name} response`);
  return v as ObjectData;
}
export function array(v: unknown): unknown[] {
  return Array.isArray(v) ? v : [];
}
export function objects(v: unknown): ObjectData[] {
  return array(v).map((x) => object(x));
}
export function num(v: unknown, fallback = 0): number {
  return typeof v === "number" && Number.isFinite(v) ? v : fallback;
}
export function str(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}
export function integer(v: unknown, name: string): number {
  if (typeof v !== "number" || !Number.isSafeInteger(v) || v < 0)
    throw Error(`Invalid ${name}`);
  return v;
}
function member<T extends string>(
  v: unknown,
  values: readonly T[],
  name: string,
): T {
  if (typeof v !== "string" || !values.includes(v as T))
    throw Error(`Invalid ${name}`);
  return v as T;
}
export interface Video {
  id: string;
  name: string;
  mode: string;
  duration_s: number;
  frame_count: number;
  width: number;
  height: number;
  fps: number;
  review_start_frame: number;
}
export function parseVideo(v: unknown): Video {
  const source = object(v),
    base = parseLibraryVideo(v);
  const width = integer(source.width, "width"),
    height = integer(source.height, "height"),
    fps = num(source.fps);
  if (!width || !height || fps <= 0 || !base.frame_count)
    throw Error("Invalid source geometry or clock");
  return {
    ...base,
    width,
    height,
    fps,
    review_start_frame: integer(source.review_start_frame ?? 0, "review start"),
  };
}
export function parseTimes(v: unknown, count: number): number[] {
  if (
    !Array.isArray(v) ||
    v.length !== count ||
    v.some(
      (x, i) =>
        typeof x !== "number" ||
        !Number.isFinite(x) ||
        x < 0 ||
        (i > 0 && x < v[i - 1]),
    )
  )
    throw Error("Invalid source timestamp table");
  return v as number[];
}
export function parseDocument(v: unknown): Document {
  const d = object(v, "annotations");
  member(d.mode, ["singles", "doubles"], "mode");
  integer(d.revision ?? 0, "revision");
  if (d.schema_version !== undefined && d.schema_version !== 1)
    throw Error("Unsupported annotation schema");
  if (!Array.isArray(d.players)) throw Error("Invalid players");
  for (const p of objects(d.players)) {
    if (!str(p.id) || typeof p.name !== "string") throw Error("Invalid player");
    member(p.team, ["T1", "T2"], "team");
    member(
      p.handedness ?? "unknown",
      ["left", "right", "unknown"],
      "handedness",
    );
  }
  for (const key of [
    "events",
    "calibrations",
    "camera_corrections",
    "scene_ranges",
    "review_windows",
    "shuttle_points",
    "track_assignments",
  ])
    if (d[key] !== undefined && !Array.isArray(d[key]))
      throw Error(`Invalid ${key}`);
  for (const e of objects(d.events)) {
    if (!str(e.id) || !str(e.rally_id)) throw Error("Invalid event identity");
    integer(e.frame, "event frame");
    member(e.kind, ["serve", "shot", "rally_end"], "event kind");
    if (e.family != null)
      member(
        e.family,
        ["clear", "lift", "net", "drop", "smash", "drive", "other", "unknown"],
        "family",
      );
    if (e.side != null)
      member(e.side, ["forehand", "backhand", "unknown"], "side");
  }
  for (const key of [
    "calibrations",
    "scene_ranges",
    "review_windows",
    "track_assignments",
  ])
    for (const r of objects(d[key])) {
      integer(r.start_frame, "range start");
      if (integer(r.end_frame, "range end") <= num(r.start_frame))
        throw Error("Invalid range");
    }
  for (const c of objects(d.calibrations)) {
    if (!Array.isArray(c.corners) || c.corners.length !== 4)
      throw Error("Invalid court");
    for (const p of objects(c.corners))
      if (
        typeof p.x !== "number" ||
        typeof p.y !== "number" ||
        !Number.isFinite(p.x) ||
        !Number.isFinite(p.y)
      )
        throw Error("Invalid court point");
  }
  for (const e of objects(d.events)) {
    for (const key of [
      "contact_start_frame",
      "contact_end_frame",
      "terminal_start_frame",
      "terminal_end_frame",
    ])
      if (e[key] != null) integer(e[key], key);
    for (const key of ["confidence", "family_score", "time_s"])
      if (
        e[key] != null &&
        (typeof e[key] !== "number" || !Number.isFinite(e[key]))
      )
        throw Error(`Invalid event ${key}`);
    if (e.status !== undefined)
      member(e.status, ["predicted", "reviewed", "corrected"], "event status");
    for (const key of [
      "player_id",
      "source_run_id",
      "candidate_id",
      "classification_run_id",
      "classification_candidate_id",
    ])
      if (e[key] != null && typeof e[key] !== "string")
        throw Error(`Invalid event ${key}`);
  }
  for (const c of objects(d.camera_corrections)) {
    integer(c.frame, "camera frame");
    if (typeof c.is_cut !== "boolean") throw Error("Invalid camera correction");
  }
  for (const r of objects(d.scene_ranges)) {
    if (!str(r.id)) throw Error("Invalid scene id");
    member(r.scene, ["live", "replay", "non_play", "unknown"], "scene");
  }
  for (const r of objects(d.review_windows)) {
    if (!str(r.id)) throw Error("Invalid reviewed clip id");
    member(r.scene ?? "unknown", ["live", "replay", "unknown"], "review scene");
    if (
      r.contacts_complete !== undefined &&
      typeof r.contacts_complete !== "boolean"
    )
      throw Error("Invalid contact coverage");
  }
  for (const a of objects(d.track_assignments)) {
    if (!str(a.run_id) || !str(a.player_id)) throw Error("Invalid assignment");
    integer(a.track_id, "track id");
  }
  for (const p of objects(d.shuttle_points)) {
    integer(p.frame, "shuttle frame");
    if (typeof p.visible !== "boolean")
      throw Error("Invalid shuttle visibility");
    if (
      p.visible &&
      [p.x, p.y].some(
        (v) => typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > 1,
      )
    )
      throw Error("Invalid manual shuttle point");
  }
  for (const records of [
    d.players,
    d.events,
    d.scene_ranges,
    d.review_windows,
  ]) {
    const ids = objects(records).map((r) => str(r.id));
    if (new Set(ids).size !== ids.length)
      throw Error("Duplicate annotation identity");
  }
  for (const collection of [
    d.events,
    d.calibrations,
    d.camera_corrections,
    d.scene_ranges,
    d.review_windows,
    d.shuttle_points,
    d.track_assignments,
  ])
    for (const r of objects(collection))
      if (r.notes !== undefined && typeof r.notes !== "string")
        throw Error("Invalid annotation notes");
  // Preserve all original fields, labels and model provenance; normalize only absent collections.
  return structuredClone({
    ...d,
    schema_version: d.schema_version ?? 1,
    revision: d.revision ?? 0,
    events: d.events ?? [],
    calibrations: d.calibrations ?? [],
    camera_corrections: d.camera_corrections ?? [],
    scene_ranges: d.scene_ranges ?? [],
    review_windows: d.review_windows ?? [],
    shuttle_points: d.shuttle_points ?? [],
    track_assignments: d.track_assignments ?? [],
  }) as Document;
}
export interface Job extends ReturnType<typeof parseLibraryJob> {
  summary: ObjectData;
  analysis_key: string | null;
}
export function parseJobs(v: unknown): Job[] {
  if (!Array.isArray(v)) throw Error("Invalid jobs response");
  return v.map((x) => {
    const j = object(x);
    return {
      ...parseLibraryJob(x),
      summary: j.summary ? object(j.summary) : {},
      analysis_key: typeof j.analysis_key === "string" ? j.analysis_key : null,
    };
  });
}
export interface Run extends ObjectData {
  start_frame: number;
  end_frame: number;
  frames: ObjectData[];
  candidates: ObjectData[];
}
export function parseRun(v: unknown): Run {
  const r = object(v, "run");
  for (const key of [
    "frames",
    "candidates",
    "boundaries",
    "automatic_calibrations",
  ])
    if (r[key] !== undefined && !Array.isArray(r[key]))
      throw Error(`Invalid run ${key}`);
  for (const c of objects(r.automatic_calibrations)) {
    integer(c.start_frame, "automatic court start");
    integer(c.end_frame, "automatic court end");
    if (!Array.isArray(c.corners) || c.corners.length !== 4)
      throw Error("Invalid automatic court");
    for (const p of objects(c.corners))
      if ([p.x, p.y].some((v) => typeof v !== "number" || !Number.isFinite(v)))
        throw Error("Invalid automatic court point");
  }
  for (const f of objects(r.frames)) {
    integer(f.frame, "native frame");
    if (f.players !== undefined && !Array.isArray(f.players))
      throw Error("Invalid tracked players");
    for (const p of objects(f.players)) {
      if (
        !Array.isArray(p.box) ||
        p.box.length !== 4 ||
        p.box.some((v) => typeof v !== "number" || !Number.isFinite(v))
      )
        throw Error("Invalid player box");
      if (
        p.keypoints !== undefined &&
        (!Array.isArray(p.keypoints) ||
          p.keypoints.some(
            (row) =>
              !Array.isArray(row) ||
              row.some((v) => typeof v !== "number" || !Number.isFinite(v)),
          ))
      )
        throw Error("Invalid pose");
    }
    if (f.shuttle) {
      const p = object(f.shuttle);
      if (typeof p.visible !== "boolean")
        throw Error("Invalid tracked shuttle visibility");
      if (
        p.visible &&
        [p.x, p.y].some((v) => typeof v !== "number" || !Number.isFinite(v))
      )
        throw Error("Invalid tracked shuttle position");
    }
  }
  for (const c of objects(r.candidates)) {
    if (!str(c.id)) throw Error("Invalid candidate id");
    integer(c.frame, "candidate frame");
    for (const key of [
      "start_frame",
      "end_frame",
      "contact_start_frame",
      "contact_end_frame",
      "context_start_frame",
      "context_end_frame",
      "clip_start_frame",
      "clip_end_frame",
    ])
      if (c[key] != null) integer(c[key], key);
    if (c.kind != null)
      member(c.kind, ["serve", "shot", "rally_end"], "candidate kind");
    if (c.side != null)
      member(c.side, ["forehand", "backhand", "unknown"], "candidate side");
  }
  return {
    ...r,
    start_frame: integer(r.start_frame ?? 0, "run start"),
    end_frame: integer(r.end_frame ?? 0, "run end"),
    frames: objects(r.frames),
    candidates: objects(r.candidates),
  };
}
export function frameAt(times: readonly number[], time: number): number {
  let lo = 0,
    hi = times.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if ((times[m] ?? Infinity) <= time + 0.00001) lo = m + 1;
    else hi = m;
  }
  return Math.max(0, lo - 1);
}
export function bounds(start: string, end: string, count: number) {
  const a = Number(start),
    b = Number(end);
  if (
    start === "" ||
    end === "" ||
    !Number.isInteger(a) ||
    !Number.isInteger(b) ||
    a < 0 ||
    b <= a ||
    b > count
  )
    throw Error("Enter a valid source-frame range. The end frame is excluded.");
  return { start_frame: a, end_frame: b };
}
export function cameraSignature(doc: Document, start: number, end: number) {
  return [...doc.camera_corrections]
    .filter((c) => c.frame < end && (c.frame >= start || c.is_cut))
    .sort((a, b) => a.frame - b.frame)
    .map((c) => [c.frame, c.is_cut]);
}
export function effectiveCalibrations(
  doc: Document,
  run: ObjectData | null,
): Calibration[] {
  const cuts = array(run?.cut_frames).map((x) => num(x));
  if (run?.preceding_reviewed_cut_frame != null)
    cuts.push(num(run.preceding_reviewed_cut_frame));
  const manual = doc.calibrations.map((c) => ({
    ...c,
    end_frame:
      run?.court_context_version === 1
        ? Math.min(
            c.end_frame,
            ...cuts.filter((f) => c.start_frame < f && f < c.end_frame),
          )
        : c.end_frame,
  }));
  const derived: Calibration[] = [];
  for (const raw of objects(run?.automatic_calibrations)) {
    const c = raw as Calibration;
    let cursor = c.start_frame;
    for (const m of [...manual].sort((a, b) => a.start_frame - b.start_frame)) {
      if (m.end_frame <= cursor || m.start_frame >= c.end_frame) continue;
      if (m.start_frame > cursor)
        derived.push({
          ...c,
          start_frame: cursor,
          end_frame: m.start_frame,
          automatic: true,
        });
      cursor = Math.max(cursor, m.end_frame);
    }
    if (cursor < c.end_frame)
      derived.push({ ...c, start_frame: cursor, automatic: true });
  }
  return [...manual, ...derived].sort((a, b) => a.start_frame - b.start_frame);
}
export function courtSignature(
  doc: Document,
  run: ObjectData | null,
  start: number,
  end: number,
) {
  return effectiveCalibrations(doc, run)
    .filter((c) => c.start_frame < end && start < c.end_frame)
    .map((c) => [c.start_frame, c.end_frame, c.corners.map((p) => [p.x, p.y])]);
}
export function cameraChanged(doc: Document, run: Run) {
  const current = doc.camera_corrections
    .filter((c) => run.start_frame <= c.frame && c.frame < run.end_frame)
    .sort((a, b) => a.frame - b.frame)
    .map((c) => [c.frame, c.is_cut]);
  const saved = objects(run.applied_camera_corrections)
    .map((c) => [c.frame, c.is_cut])
    .sort((a, b) => num(a[0]) - num(b[0]));
  const previous = new Set(
    array(run.known_preceding_cut_frames).map((x) => num(x)),
  );
  for (const c of doc.camera_corrections) {
    if (c.frame >= run.start_frame) continue;
    if (c.is_cut) previous.add(c.frame);
    else if (!array(run.known_preceding_timestamp_gaps).includes(c.frame))
      previous.delete(c.frame);
  }
  return (
    JSON.stringify(current) !== JSON.stringify(saved) ||
    Math.max(-1, ...previous) !== num(run.preceding_reviewed_cut_frame, -1)
  );
}
export function courtChanged(doc: Document, run: Run) {
  if (!run.court_context) return false;
  const c = object(run.court_context);
  return (
    JSON.stringify(
      courtSignature(doc, c, num(c.start_frame), num(c.end_frame)),
    ) !== JSON.stringify(run.calibration_signature) ||
    (c.known_preceding_cut_frames != null && cameraChanged(doc, parseRun(c)))
  );
}
export function displayCalibrations(
  doc: Document,
  run: Run | null,
  times: number[],
  fps: number,
  automaticValid: boolean,
) {
  const gaps = new Set(
    array(run?.known_preceding_timestamp_gaps).map((x) => num(x)),
  );
  for (const b of objects(run?.boundaries))
    if (b.reason === "timestamp_discontinuity") gaps.add(num(b.frame));
  for (let f = 1; f < times.length; f++)
    if ((times[f] ?? 0) - (times[f - 1] ?? 0) > Math.max(0.1, 2.5 / fps) + 1e-8)
      gaps.add(f);
  const cuts = new Set(
    [
      ...array(run?.raw_cut_frames ?? run?.cut_frames),
      ...array(
        run?.known_preceding_cut_frames ??
          (run?.preceding_reviewed_cut_frame != null
            ? [run.preceding_reviewed_cut_frame]
            : []),
      ),
      ...gaps,
    ].map((x) => num(x)),
  );
  for (const c of doc.camera_corrections) {
    if (c.is_cut) cuts.add(c.frame);
    else if (!gaps.has(c.frame)) cuts.delete(c.frame);
  }
  return effectiveCalibrations(doc, {
    court_context_version: 1,
    cut_frames: [...cuts],
    automatic_calibrations: automaticValid ? run?.automatic_calibrations : [],
  });
}
export function ownedCandidates(run: Run | null) {
  return (run?.candidates ?? []).filter(
    (c) =>
      run?.analysis_core_start_frame == null ||
      (num(run.analysis_core_start_frame) <= num(c.frame) &&
        num(c.frame) < num(run.analysis_core_end_frame)),
  );
}
export function contextSignature(
  doc: Document,
  start: number,
  end: number,
  run: ObjectData | null = null,
) {
  return {
    camera: cameraSignature(doc, start, end),
    scenes: [...doc.scene_ranges]
      .filter((r) => r.start_frame < end && start < r.end_frame)
      .sort((a, b) => a.start_frame - b.start_frame)
      .map((r) => [r.start_frame, r.end_frame, r.scene]),
    court: courtSignature(doc, run, start, end),
  };
}
export function clock(t: number) {
  return `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, "0")}`;
}
export function pretty(v: unknown) {
  return str(v, "Unknown").replaceAll("_", " ");
}
