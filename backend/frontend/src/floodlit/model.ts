// Data access and small geometry helpers shared by every Floodlit screen.
// Ported from the approved prototype (design/prototypes/a-floodlit/js/data.js);
// everything here is pure so it can be tested without a browser.
import type { components } from "../api/client.js";

type Schemas = components["schemas"];
export type Analysis = Schemas["MatchAnalysis"];
export type Stats = Schemas["ClipStats"];
export type Rally = Schemas["Rally"];
export type Shot = Schemas["Shot"];
export type Person = Schemas["Person"];
export type PersonTrack = Schemas["PersonTrack"];
export type CourtView = Schemas["CourtView"];
export type PersonId = Person["id"];
export type Team = Person["team"];
export type MatchStatus = Schemas["MatchStatus"];
export type MatchState = MatchStatus["state"];
export type MatchPlayers = Schemas["MatchPlayers"];
export type MatchSummary = Schemas["MatchSummary"];
export type Mode = MatchStatus["mode"];
export type Flight = Schemas["ShotFlight"];
export type Matrix = number[][];
export type View = CourtView & { inverse: Matrix };
export interface Point {
  x: number;
  y: number;
}

/** What every screen needs about one match: the document plus lookups. */
export interface Match {
  id: string;
  analysis: Analysis;
  stats: Stats | null;
  trackIndex: Map<string, PersonTrack>;
  views: View[];
  /** Picture URL per person id, or null when there is none. */
  photos: Record<string, string | null>;
}

/** Sample sizes below this are held back from the Analysis page. */
export const MIN_N = 5;

export function prepareMatch(
  id: string,
  analysis: Analysis,
  stats: Stats | null,
  photos: Record<string, string | null> = {},
): Match {
  const trackIndex = new Map(
    analysis.tracks.persons.map((p) => [p.person_id, p] as const),
  );
  const views = (analysis.court.views ?? []).map((v) => ({
    ...v,
    inverse: inv3(v.homography),
  }));
  return { id, analysis, stats, trackIndex, views, photos };
}

/* ---------- names ---------- */
/** Anything with a player list: a match, or the hero's sample rally. */
export interface Named {
  analysis: {
    players: { id: string; name?: string | undefined; team: Team }[];
  };
}
export function nameOf(match: Named, id?: string | null) {
  if (!id) return "Unknown player";
  const person = match.analysis.players.find((p) => p.id === id);
  return person?.name || id;
}
/** First name, unless two players share it; then the full name. */
export function firstName(match: Named, id?: string | null) {
  const full = nameOf(match, id);
  const first = full.split(" ")[0] ?? full;
  const clash = match.analysis.players.some(
    (p) => p.id !== id && nameOf(match, p.id).split(" ")[0] === first,
  );
  return clash ? full : first;
}
export function teamOf(match: Named, id?: string | null) {
  return match.analysis.players.find((p) => p.id === id)?.team;
}
export function teamPlayers(match: Named, team: Team) {
  return match.analysis.players.filter((p) => p.team === team);
}
export function teamName(match: Named, team: Team) {
  return teamPlayers(match, team)
    .map((p) => firstName(match, p.id))
    .join(" & ");
}
export const sideNumber = (team?: string | null) => (team === "T1" ? 1 : 2);
export function initials(name: string) {
  return name
    .split(/\s+/)
    .map((w) => w[0] ?? "")
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

/* ---------- labels ---------- */
const LABELS: Record<string, string> = {
  clear: "Clear",
  drive: "Drive",
  smash: "Smash",
  net: "Net shot",
  drop: "Drop",
  lift: "Lift",
  block: "Block",
  push: "Push",
  net_kill: "Net kill",
  other: "Other shot",
  serve_short: "Short serve",
  serve_long: "Long serve",
  serve: "Serve",
  unknown: "Unknown shot",
};
export const labelText = (l: string) => LABELS[l] ?? l;
export function shotLabel(shot: Pick<Shot, "kind" | "serve_type" | "family">) {
  if (shot.kind === "serve")
    return shot.serve_type ? `serve_${shot.serve_type}` : "serve";
  return shot.family || "unknown";
}
export interface Speed {
  kmh?: number;
  bound?: boolean;
}
/** The speed to show for a shot: the fitted launch speed of a good fit,
 * "too fast to measure" at the fit's speed bound, else none. The flight's
 * launch-support diagnostics never hide or replace the number. */
export function speedOf(
  shot?: { flight?: Flight | null } | null,
): Speed | null {
  const f = shot?.flight;
  if (!f) return null;
  if (f.quality === "good" && Number.isFinite(f.initial_speed_kmh))
    return { kmh: Math.round(f.initial_speed_kmh) };
  if (f.quality === "speed_bound") return { bound: true };
  return null;
}
export function outcomeText(rally: Pick<Rally, "outcome">) {
  const o = rally.outcome;
  if (!o || !o.winner_team) return "Result unknown";
  if (o.reason === "winner") return "Winner";
  if (o.detail === "net") return "Error into the net";
  if (o.detail === "out") return "Error, out";
  return "Error";
}

/* ---------- time ---------- */
export function clock(s?: number | null) {
  if (s == null || !isFinite(s)) return "0:00";
  s = Math.max(0, s);
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, "0")}`;
}

/* ---------- homography ---------- */
export function inv3(m: Matrix): Matrix {
  const [[a, b, c], [d, e, f], [g, h, i]] = m as [
    [number, number, number],
    [number, number, number],
    [number, number, number],
  ];
  const A = e * i - f * h,
    B = -(d * i - f * g),
    C = d * h - e * g;
  const det = a * A + b * B + c * C;
  return [
    [A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
    [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
    [C / det, -(a * h - b * g) / det, (a * e - b * d) / det],
  ];
}
export function applyH(H: Matrix, x: number, y: number): [number, number] {
  const r = H as [
    [number, number, number],
    [number, number, number],
    [number, number, number],
  ];
  const X = r[0][0] * x + r[0][1] * y + r[0][2];
  const Y = r[1][0] * x + r[1][1] * y + r[1][2];
  const W = r[2][0] * x + r[2][1] * y + r[2][2];
  return [X / W, Y / W];
}
export function viewAt(match: Pick<Match, "views">, frame: number) {
  return (
    match.views.find((v) => frame >= v.start_frame && frame < v.end_frame) ??
    null
  );
}

/* ---------- tracks ---------- */
/** Court position of a person at time t (seconds), interpolated from the 10 Hz track. */
export function positionAt(
  match: Pick<Match, "trackIndex" | "analysis">,
  id: string | null | undefined,
  t: number,
  reach = 8,
): Point | null {
  const tr = id ? match.trackIndex.get(id) : undefined;
  if (!tr) return null;
  const rate = match.analysis.tracks.rate_hz;
  const k = t * rate;
  const k0 = Math.floor(k);
  const f = k - k0;
  const x0 = tr.x[k0],
    y0 = tr.y[k0],
    x1 = tr.x[k0 + 1],
    y1 = tr.y[k0 + 1];
  if (x0 != null && x1 != null && y0 != null && y1 != null)
    return { x: x0 + (x1 - x0) * f, y: y0 + (y1 - y0) * f };
  for (let d = 0; d <= reach; d++) {
    for (const j of [k0 - d, k0 + 1 + d]) {
      const x = tr.x[j],
        y = tr.y[j];
      if (x != null && y != null) return { x, y };
    }
  }
  return null;
}
export function rallyEnd(r: Pick<Rally, "end_s" | "shots">) {
  const last = r.shots[r.shots.length - 1];
  return Math.max(r.end_s, last?.landing?.time_s ?? 0);
}
export function rallyNumber(r: Pick<Rally, "id">) {
  return Number(r.id.replace("rally-", ""));
}
/** Rallies won by each side, counted from the outcomes. */
export function ralliesWon(rallies: Pick<Rally, "outcome">[]) {
  const won = { T1: 0, T2: 0 };
  for (const r of rallies) {
    const w = r.outcome?.winner_team;
    if (w) won[w]++;
  }
  return won;
}
/** The swap overrides that cover a rally, newest last. */
export function rallySwaps(
  analysis: Pick<Analysis, "overrides">,
  rally: Pick<Rally, "start_frame" | "end_frame" | "id">,
) {
  return (analysis.overrides ?? []).filter(
    (o) =>
      o.rally_id === rally.id ||
      (o.start_frame <= rally.end_frame && o.end_frame >= rally.start_frame),
  );
}

/* ---------- stats helpers ---------- */
export const pct = (share?: number | null) =>
  share == null ? "–" : `${Math.round(share * 100)}%`;
export const enough = (n?: number | null, min = MIN_N) => n != null && n >= min;
export function fmt(v?: number | null, d = 0) {
  return v == null ? "–" : Number(v).toFixed(d);
}

/* ---------- match states ---------- */
export const STATE_TEXT: Record<MatchState, string> = {
  queued: "Waiting to start",
  running: "Analysing",
  needs_names: "Check the names",
  ready: "Ready",
  failed: "Stopped with a problem",
  paused: "Paused",
};
/** Where a match with this status should open. */
export function matchHome(id: string, state: MatchState) {
  if (state === "ready") return `#/match/${id}/watch`;
  if (state === "needs_names") return `#/match/${id}/names`;
  return `#/match/${id}/processing`;
}

/* ---------- shot pace and bow from the image track (hero only) ---------- */
interface PaceShot {
  frame: number;
  time_s: number;
  hitter_position?: Point | null;
  shuttle?: Point | null;
}
interface PaceMatch {
  analysis: {
    video: { frame_count: number; fps: number; width: number; height: number };
    tracks: { shuttle?: { x: (number | null)[]; y: (number | null)[] } };
  };
  views: { start_frame: number; end_frame: number; inverse: Matrix }[];
}

// Fit one smooth progress curve, never individual noisy detections. Use the
// lateral image coordinate: image height conflates depth and shuttle height.
// Perspective weights are approximated at the players' floor positions. For
// straight-on shots this cue is unobservable, so keep the stroke prior.
export function estimatePace(
  match: PaceMatch,
  a: PaceShot,
  b: PaceShot | undefined,
  prior: number,
): number | null {
  const video = match.analysis.video,
    xs = match.analysis.tracks?.shuttle?.x;
  if (
    !b ||
    !xs ||
    xs.length !== video.frame_count ||
    !a.hitter_position ||
    !b.hitter_position
  )
    return null;
  const view = match.views?.find(
    (v) => v.start_frame <= a.frame && b.frame < v.end_frame,
  );
  const row = view?.inverse?.[2];
  if (
    !row ||
    !a.shuttle ||
    !b.shuttle ||
    !Number.isFinite(a.shuttle.x) ||
    !Number.isFinite(b.shuttle.x)
  )
    return null;
  const as = a.shuttle;
  const span = b.frame - a.frame,
    dx = b.shuttle.x - as.x;
  if (
    span < 9 ||
    span > 3 * video.fps ||
    Math.abs(span / video.fps - (b.time_s - a.time_s)) > 0.5 / video.fps ||
    Math.abs(dx) * video.width < 40
  )
    return null;
  const depth = (p: Point) =>
    (row[0] ?? 0) * p.x + (row[1] ?? 0) * p.y + (row[2] ?? 0);
  const ratio = depth(b.hitter_position) / depth(a.hitter_position);
  if (!(ratio > 0.4 && ratio < 2.5)) return null;
  const samples: [number, number][] = [];
  for (let k = 1; k < span; k++) {
    const x = xs[a.frame + k]; // native frame, not the 10 Hz player-track index
    if (x != null && Number.isFinite(x)) samples.push([k / span, x]);
  }
  if (
    samples.length < 8 ||
    (samples[1]?.[0] ?? 1) > 0.35 ||
    (samples.at(-2)?.[0] ?? 0) < 0.65
  )
    return null;
  const train = samples.filter((_, i) => !(i % 2)),
    check = samples.filter((_, i) => i % 2);
  function error(d: number, points: [number, number][]) {
    const residuals = points
      .map(([t, x]) => {
        const u = Math.expm1(-d * t) / Math.expm1(-d);
        const v = (u * ratio) / (1 - u + u * ratio);
        return Math.abs(as.x + dx * v - x) * video.width;
      })
      .sort((p, q) => p - q);
    return residuals[Math.floor(residuals.length / 2)] ?? Infinity;
  }
  let best = prior,
    score = error(prior, train);
  for (let k = 1; k <= 24; k++) {
    const d = k / 5,
      candidate = error(d, train);
    if (candidate < score) {
      best = d;
      score = candidate;
    }
  }
  const validation = error(best, check);
  return validation < 8 && validation + 1 < error(prior, check) ? best : null;
}

// Estimate the height above the straight racket-to-racket chord. At each
// depth use the projected width of a court metre as the local image scale.
// This is a broadcast-view approximation, not a recovered world height.
export function estimateBow(
  match: PaceMatch,
  a: PaceShot,
  b: PaceShot | undefined,
  drag: number,
  prior: number,
): number {
  const video = match.analysis.video,
    ys = match.analysis.tracks?.shuttle?.y;
  if (
    !b ||
    ys?.length !== video.frame_count ||
    !a.hitter_position ||
    !b.hitter_position ||
    !a.shuttle ||
    !b.shuttle ||
    !Number.isFinite(a.shuttle.y) ||
    !Number.isFinite(b.shuttle.y)
  )
    return prior;
  const H = match.views?.find(
    (v) => v.start_frame <= a.frame && b.frame < v.end_frame,
  )?.inverse;
  const span = b.frame - a.frame;
  if (
    !H ||
    span < 9 ||
    span > 3 * video.fps ||
    Math.abs(span / video.fps - (b.time_s - a.time_s)) > 0.5 / video.fps
  )
    return prior;
  const h2 = H[2] ?? [0, 0, 0];
  const depth = (p: Point) =>
    (h2[0] ?? 0) * p.x + (h2[1] ?? 0) * p.y + (h2[2] ?? 0);
  const A = a.hitter_position,
    B = b.hitter_position,
    ratio = depth(B) / depth(A);
  if (!(ratio > 0.4 && ratio < 2.5)) return prior;
  const as = a.shuttle,
    bs = b.shuttle;
  const points: { k: number; rise: number; weight: number }[] = [];
  for (let k = 1; k < span; k++) {
    const yk = ys[a.frame + k];
    if (yk == null || !Number.isFinite(yk)) continue;
    const u = Math.expm1((-drag * k) / span) / Math.expm1(-drag),
      v = (u * ratio) / (1 - u + u * ratio);
    if (u < 0.08 || u > 0.92) continue;
    const x = A.x + (B.x - A.x) * u,
      y = A.y + (B.y - A.y) * u;
    const scale =
      Math.abs(applyH(H, x + 1, y)[0] - applyH(H, x, y)[0]) * video.width;
    if (!(scale > 8 && scale < video.height / 2)) continue;
    const rise = (as.y + (bs.y - as.y) * v - yk) * video.height;
    points.push({ k, rise, weight: scale * u * (1 - u) });
  }
  if (
    points.length < 8 ||
    (points[1]?.k ?? span) / span > 0.35 ||
    (points.at(-2)?.k ?? 0) / span < 0.5
  )
    return prior;
  const median = (arr: number[]) =>
    arr.sort((p, q) => p - q)[Math.floor(arr.length / 2)] ?? NaN;
  const bow = median(
    points.filter((_, i) => !(i % 2)).map((p) => p.rise / p.weight),
  );
  if (!(bow >= 0 && bow <= 24)) return prior;
  const check = points.filter((_, i) => i % 2),
    err = (c: number) =>
      median(check.map((p) => Math.abs(p.rise - c * p.weight)));
  return err(bow) < 8 && err(bow) + 1 < err(prior) ? bow : prior;
}
