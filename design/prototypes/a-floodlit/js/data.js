// Data access and small geometry helpers shared by every screen.

export const params = new URLSearchParams(location.search);
export const MATCH = params.get('match') === 'singles' ? 'singles' : 'doubles';
export const FUTURE = params.get('future') === '1';
export const BASE = `../data/${MATCH}/`;
export const asset = (p) => BASE + p;
export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Sample sizes below this are held back from the Analysis page. */
export const MIN_N = 5;

let loading;
export function loadMatch() {
  if (!loading) {
    loading = Promise.all([
      fetch(asset('analysis.json')).then((r) => r.json()),
      fetch(asset('stats.json')).then((r) => r.json()),
    ]).then(([analysis, stats]) => prepare(analysis, stats));
  }
  return loading;
}

function prepare(analysis, stats) {
  const trackIndex = new Map(analysis.tracks.persons.map((p) => [p.person_id, p]));
  const views = analysis.court.views.map((v) => ({ ...v, inverse: inv3(v.homography) }));
  return { analysis, stats, trackIndex, views };
}

/* ---------- names (kept in session so upload and confirmation carry through) ---------- */
const KEY = `floodlit:${MATCH}`;
export function getState() {
  try { return JSON.parse(sessionStorage.getItem(KEY)) || {}; } catch { return {}; }
}
export function setState(patch) {
  const next = { ...getState(), ...patch };
  try { sessionStorage.setItem(KEY, JSON.stringify(next)); } catch { /* private mode */ }
  return next;
}
export function nameOf(match, id) {
  if (!id) return 'Unknown player';
  const s = getState();
  return (s.names && s.names[id]) || match.analysis.players.find((p) => p.id === id)?.name || id;
}
/** First name, unless two players share it; then the full name. */
export function firstName(match, id) {
  const full = nameOf(match, id);
  const first = full.split(' ')[0];
  const clash = match.analysis.players.some((p) => p.id !== id && nameOf(match, p.id).split(' ')[0] === first);
  return clash ? full : first;
}
export function teamOf(match, id) { return match.analysis.players.find((p) => p.id === id)?.team; }
export function teamPlayers(match, team) { return match.analysis.players.filter((p) => p.team === team); }
export function teamName(match, team) {
  return teamPlayers(match, team).map((p) => firstName(match, p.id)).join(' & ');
}
export const sideNumber = (team) => (team === 'T1' ? 1 : 2);

/* ---------- labels ---------- */
const LABELS = {
  clear: 'Clear', drive: 'Drive', smash: 'Smash', net: 'Net shot', drop: 'Drop', lift: 'Lift',
  block: 'Block', push: 'Push', net_kill: 'Net kill', other: 'Other shot',
  serve_short: 'Short serve', serve_long: 'Long serve', serve: 'Serve', unknown: 'Unknown shot',
};
export const labelText = (l) => LABELS[l] || l;
export function shotLabel(shot) {
  if (shot.kind === 'serve') return shot.serve_type ? `serve_${shot.serve_type}` : 'serve';
  return shot.family || 'unknown';
}
export function speedOf(shot) {
  const f = shot && shot.flight;
  if (!f) return null;
  if (f.quality === 'good' && f.launch_supported !== false) {
    const speed = f.launch_supported === true ? f.early_speed_kmh : f.initial_speed_kmh;
    if (Number.isFinite(speed)) return { kmh: Math.round(speed) };
  }
  if (f.quality === 'speed_bound' || f.quality === 'good') {
    if (f.settled_supported === true && Number.isFinite(f.speed_settled_kmh))
      return { kmh: Math.round(f.speed_settled_kmh), settled: true };
    return { bound: true };
  }
  return null;
}
export function outcomeText(rally) {
  const o = rally.outcome;
  if (!o || !o.winner_team) return 'Result unknown';
  if (o.reason === 'winner') return 'Winner';
  if (o.detail === 'net') return 'Error into the net';
  if (o.detail === 'out') return 'Error, out';
  return 'Error';
}

/* ---------- time ---------- */
export function clock(s) {
  if (s == null || !isFinite(s)) return '0:00';
  s = Math.max(0, s);
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
}

/* ---------- homography ---------- */
export function inv3(m) {
  const [[a, b, c], [d, e, f], [g, h, i]] = m;
  const A = e * i - f * h, B = -(d * i - f * g), C = d * h - e * g;
  const det = a * A + b * B + c * C;
  return [
    [A / det, -(b * i - c * h) / det, (b * f - c * e) / det],
    [B / det, (a * i - c * g) / det, -(a * f - c * d) / det],
    [C / det, -(a * h - b * g) / det, (a * e - b * d) / det],
  ];
}
export function applyH(H, x, y) {
  const X = H[0][0] * x + H[0][1] * y + H[0][2];
  const Y = H[1][0] * x + H[1][1] * y + H[1][2];
  const W = H[2][0] * x + H[2][1] * y + H[2][2];
  return [X / W, Y / W];
}
export function viewAt(match, frame) {
  return match.views.find((v) => frame >= v.start_frame && frame < v.end_frame) || null;
}

/* ---------- tracks ---------- */
/** Court position of a person at time t (seconds), interpolated from the 10 Hz track. */
export function positionAt(match, id, t, reach = 8) {
  const tr = match.trackIndex.get(id);
  if (!tr) return null;
  const rate = match.analysis.tracks.rate_hz;
  const k = t * rate;
  const k0 = Math.floor(k);
  const f = k - k0;
  const x0 = tr.x[k0], y0 = tr.y[k0], x1 = tr.x[k0 + 1], y1 = tr.y[k0 + 1];
  if (x0 != null && x1 != null) return { x: x0 + (x1 - x0) * f, y: y0 + (y1 - y0) * f };
  for (let d = 0; d <= reach; d++) {
    for (const j of [k0 - d, k0 + 1 + d]) {
      if (tr.x[j] != null) return { x: tr.x[j], y: tr.y[j] };
    }
  }
  return null;
}

export function rallyAt(match, t) {
  return match.analysis.rallies.find((r) => t >= r.start_s - 0.3 && t <= rallyEnd(r) + 0.6) || null;
}
export function rallyEnd(r) {
  const last = r.shots[r.shots.length - 1];
  return Math.max(r.end_s, last?.landing?.time_s ?? 0);
}
export function rallyNumber(r) { return Number(r.id.replace('rally-', '')); }

/* ---------- stats helpers ---------- */
export const pct = (share) => (share == null ? '–' : `${Math.round(share * 100)}%`);
export const enough = (n, min = MIN_N) => n != null && n >= min;
export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

// Fit one smooth progress curve, never individual noisy detections. Use the
// lateral image coordinate: image height conflates depth and shuttle height.
// Perspective weights are approximated at the players' floor positions. For
// straight-on shots this cue is unobservable, so keep the stroke prior.
export function estimatePace(match, a, b, prior) {
  const video = match.analysis.video, xs = match.analysis.tracks?.shuttle?.x;
  if (!b || !xs || xs.length !== video.frame_count || !a.hitter_position || !b.hitter_position) return null;
  const view = match.views?.find(v => v.start_frame <= a.frame && b.frame < v.end_frame);
  const row = view?.inverse?.[2];
  if (!row || !Number.isFinite(a.shuttle?.x) || !Number.isFinite(b.shuttle?.x)) return null;
  const span = b.frame-a.frame, dx = b.shuttle.x-a.shuttle.x;
  if (span < 9 || span > 3*video.fps || Math.abs(span/video.fps-(b.time_s-a.time_s)) > 0.5/video.fps || Math.abs(dx)*video.width < 40) return null;
  const depth = p => row[0]*p.x + row[1]*p.y + row[2];
  const ratio = depth(b.hitter_position)/depth(a.hitter_position);
  if (!(ratio > 0.4 && ratio < 2.5)) return null;
  const samples = [];
  for (let k=1;k<span;k++) {
    const x = xs[a.frame+k]; // native frame, not the 10 Hz player-track index
    if (Number.isFinite(x)) samples.push([k/span,x]);
  }
  if (samples.length < 8 || samples[1][0] > 0.35 || samples.at(-2)[0] < 0.65) return null;
  const train = samples.filter((_,i) => !(i%2)), check = samples.filter((_,i) => i%2);
  function error(d, points) {
    const residuals = points.map(([t,x]) => {
      const u = Math.expm1(-d*t)/Math.expm1(-d);
      const v = u*ratio/(1-u+u*ratio);
      return Math.abs(a.shuttle.x+dx*v-x)*video.width;
    }).sort((x,y)=>x-y);
    return residuals[Math.floor(residuals.length/2)];
  }
  let best=prior, score=error(prior,train);
  for(let k=1;k<=24;k++) {
    const d=k/5, candidate=error(d,train);
    if(candidate<score) {best=d; score=candidate;}
  }
  const validation=error(best,check);
  return validation < 8 && validation+1 < error(prior,check) ? best : null;
}

// Estimate the height above the straight racket-to-racket chord. At each
// depth use the projected width of a court metre as the local image scale.
// This is a broadcast-view approximation, not a recovered world height.
export function estimateBow(match, a, b, drag, prior) {
  const video=match.analysis.video, ys=match.analysis.tracks?.shuttle?.y;
  if (!b || ys?.length!==video.frame_count || !a.hitter_position || !b.hitter_position ||
      !Number.isFinite(a.shuttle?.y) || !Number.isFinite(b.shuttle?.y)) return prior;
  const H=match.views?.find(v=>v.start_frame<=a.frame && b.frame<v.end_frame)?.inverse;
  const span=b.frame-a.frame;
  if (!H || span<9 || span>3*video.fps || Math.abs(span/video.fps-(b.time_s-a.time_s))>0.5/video.fps) return prior;
  const depth=p=>H[2][0]*p.x+H[2][1]*p.y+H[2][2];
  const A=a.hitter_position, B=b.hitter_position, ratio=depth(B)/depth(A);
  if (!(ratio>0.4 && ratio<2.5)) return prior;
  const points=[];
  for (let k=1;k<span;k++) {
    if (!Number.isFinite(ys[a.frame+k])) continue;
    const u=Math.expm1(-drag*k/span)/Math.expm1(-drag), v=u*ratio/(1-u+u*ratio);
    if (u<0.08 || u>0.92) continue;
    const x=A.x+(B.x-A.x)*u,y=A.y+(B.y-A.y)*u;
    const scale=Math.abs(applyH(H,x+1,y)[0]-applyH(H,x,y)[0])*video.width;
    if (!(scale>8 && scale<video.height/2)) continue;
    const rise=(a.shuttle.y+(b.shuttle.y-a.shuttle.y)*v-ys[a.frame+k])*video.height;
    points.push({k, rise, weight:scale*u*(1-u)});
  }
  if (points.length<8 || points[1].k/span>0.35 || points.at(-2).k/span<0.5) return prior;
  const median=arr=>arr.sort((a,b)=>a-b)[Math.floor(arr.length/2)];
  const bow=median(points.filter((_,i)=>!(i%2)).map(p=>p.rise/p.weight));
  if (!(bow>=0 && bow<=24)) return prior;
  const check=points.filter((_,i)=>i%2), err=c=>median(check.map(p=>Math.abs(p.rise-c*p.weight)));
  return err(bow)<8 && err(bow)+1<err(prior) ? bow : prior;
}
