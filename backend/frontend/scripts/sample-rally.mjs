// Derive the landing hero's bundled sample rally from a MatchAnalysis document.
//
//   node backend/frontend/scripts/sample-rally.mjs [analysis.json] [output.json]
//
// Defaults: the doubles sample the Floodlit prototype uses (local, git-ignored)
// and src/floodlit/sample-rally.json. The output is one rally with the tracks,
// shots, court view and names it needs, rebased so that time 0 is a second
// before the rally, so a fresh install has something to replay.
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const source =
  process.argv[2] ??
  here("../../../design/prototypes/data/doubles/analysis.json");
const output = process.argv[3] ?? here("../src/floodlit/sample-rally.json");
const doc = JSON.parse(await readFile(source, "utf8"));

// The same choice as the hero's own pickRally: long, well tracked, ends on a
// landing, with some fast strokes.
let rally = null;
let best = -1;
for (const r of doc.rallies) {
  const shots = r.shots;
  if (shots.length < 6 || !shots.at(-1).landing?.position) continue;
  const cover = shots.filter((s) => s.hitter_position).length / shots.length;
  const fast = shots.filter((s) =>
    ["smash", "net_kill"].includes(s.family),
  ).length;
  const score = cover * 10 + Math.min(shots.length, 24) + fast * 0.8;
  if (score > best) [best, rally] = [score, r];
}
if (!rally) throw new Error("No rally with six shots and a landing");

const { fps } = doc.video;
const rate = doc.tracks.rate_hz;
if (fps !== 25 || rate !== 10)
  throw new Error("Expected 25 fps and 10 Hz tracks");
// Rebase on a 0.2 s boundary so that frames (25 fps) and track samples (10 Hz)
// both shift by whole steps.
const k0 = Math.max(0, Math.floor(((rally.start_s - 1) * rate) / 2) * 2);
const t0 = k0 / rate;
const f0 = Math.round(t0 * fps);
const lastLanding = rally.shots.at(-1).landing?.time_s ?? 0;
const tEnd = Math.max(rally.end_s, lastLanding) + 3;
const k1 = Math.ceil(tEnd * rate);
const f1 = Math.min(doc.video.frame_count, Math.round(tEnd * fps));
const r2 = (v, d) => (v == null ? null : Number(v.toFixed(d)));
const time = (s) => r2(s - t0, 2);
const frame = (f) => f - f0;
const point = (p) => (p ? { x: r2(p.x, 2), y: r2(p.y, 2) } : null);

const shots = rally.shots.map((s) => ({
  id: s.id,
  frame: frame(s.frame),
  time_s: time(s.time_s),
  kind: s.kind,
  hitter_id: s.hitter_id,
  family: s.family,
  side: s.side,
  serve_type: s.serve_type,
  hitter_position: point(s.hitter_position),
  players: [],
  shuttle: s.shuttle ? { x: r2(s.shuttle.x, 4), y: r2(s.shuttle.y, 4) } : null,
  landing: s.landing
    ? {
        frame: frame(s.landing.frame),
        time_s: time(s.landing.time_s),
        image: { x: r2(s.landing.image.x, 4), y: r2(s.landing.image.y, 4) },
        position: point(s.landing.position),
        in_court: s.landing.in_court,
        kind: s.landing.kind,
        source: s.landing.source,
      }
    : null,
  flight: s.flight
    ? {
        initial_speed_kmh: r2(s.flight.initial_speed_kmh, 1),
        speed_settled_kmh: r2(s.flight.speed_settled_kmh, 1),
        apex_m: r2(s.flight.apex_m, 2),
        quality: s.flight.quality,
        rms: s.flight.rms,
        points: s.flight.points,
        inliers: s.flight.inliers,
      }
    : null,
}));
const views = doc.court.views
  .filter((v) => v.start_frame < f1 && v.end_frame > f0)
  .map((v) => ({
    start_frame: Math.max(0, v.start_frame - f0),
    end_frame: Math.min(f1, v.end_frame) - f0,
    corners: v.corners,
    homography: v.homography,
    source: v.source,
  }));
const sample = {
  note: `Rally ${rally.id} of the doubles sample, rebased to start ${t0} s earlier; derived by scripts/sample-rally.mjs.`,
  video: {
    id: "sample",
    name: "Sample rally",
    mode: doc.video.mode,
    fps,
    frame_count: f1 - f0,
    duration_s: r2((f1 - f0) / fps, 2),
    width: doc.video.width,
    height: doc.video.height,
  },
  players: doc.players.map((p) => ({ id: p.id, name: p.name, team: p.team })),
  rally_number: Number(rally.id.replace("rally-", "")),
  rallies: [
    {
      id: rally.id,
      start_frame: frame(rally.start_frame),
      end_frame: frame(rally.end_frame),
      start_s: time(rally.start_s),
      end_s: time(rally.end_s),
      server_id: rally.server_id,
      outcome: rally.outcome,
      shots,
    },
  ],
  court: { views },
  tracks: {
    rate_hz: rate,
    persons: doc.tracks.persons.map((p) => ({
      person_id: p.person_id,
      x: p.x.slice(k0, k1).map((v) => r2(v, 2)),
      y: p.y.slice(k0, k1).map((v) => r2(v, 2)),
    })),
    shuttle: {
      x: doc.tracks.shuttle.x.slice(f0, f1).map((v) => r2(v, 4)),
      y: doc.tracks.shuttle.y.slice(f0, f1).map((v) => r2(v, 4)),
    },
  },
};
await writeFile(output, `${JSON.stringify(sample)}\n`);
console.log(
  `${rally.id}: ${shots.length} shots, ${f1 - f0} frames -> ${output}`,
);
