// Data loading, app state and small helpers shared by every screen.

const params = new URLSearchParams(location.search);

export const state = {
  match: params.get('match') === 'singles' ? 'singles' : 'doubles',
  future: params.get('future') === '1',
  // Upload form, kept while moving through the flow.
  upload: { file: null, mode: null, names: { T1: ['', ''], T2: ['', ''] } },
  // Names the person confirmed, by person id. Null until confirmed in this session.
  confirmed: null,
  // Rally swaps made on the Watch tab: rallyId -> [personA, personB].
  swaps: {},
};

export function setMatch(match) {
  state.match = match === 'singles' ? 'singles' : 'doubles';
  const p = new URLSearchParams(location.search);
  if (state.match === 'doubles') p.delete('match');
  else p.set('match', state.match);
  const qs = p.toString();
  history.replaceState(null, '', `${location.pathname}${qs ? `?${qs}` : ''}${location.hash}`);
}

export const base = () => `../data/${state.match}/`;

const cache = {};
export async function load(match = state.match) {
  if (!cache[match]) {
    cache[match] = Promise.all([
      fetch(`../data/${match}/analysis.json`).then((r) => {
        if (!r.ok) throw new Error(`analysis.json: ${r.status}`);
        return r.json();
      }),
      fetch(`../data/${match}/stats.json`).then((r) => {
        if (!r.ok) throw new Error(`stats.json: ${r.status}`);
        return r.json();
      }),
    ]).then(([analysis, stats]) => ({ analysis, stats, base: `../data/${match}/` }));
  }
  return cache[match];
}

/** Display name for a person: confirmed in this session, else the document's. */
export function nameOf(analysis, id) {
  if (!id) return 'Unknown player';
  if (state.confirmed && state.confirmed[id]) return state.confirmed[id];
  const p = analysis.players.find((q) => q.id === id);
  return (p && p.name) || id;
}

export function teamOf(analysis, id) {
  const p = analysis.players.find((q) => q.id === id);
  return p ? p.team : null;
}

export function teamMembers(analysis, team) {
  return analysis.players.filter((p) => p.team === team).map((p) => p.id);
}

export function teamName(analysis, team) {
  return teamMembers(analysis, team).map((id) => nameOf(analysis, id)).join(' & ');
}

/**
 * A believable fast shot for the hero. Single flight fits can be well off and
 * the fastest "good" fits sit near the fit's bound, so take the fastest good
 * smash at or below the clip's 90th percentile of good smash speeds (and no
 * more than 300 km/h). Falls back to any good shot under the same rule.
 */
export function fastestShot(analysis) {
  const all = [];
  analysis.rallies.forEach((rally) => {
    rally.shots.forEach((shot, i) => {
      const f = shot.flight;
      if (!f || f.quality !== 'good' || f.initial_speed_kmh == null || !shot.hitter_position) return;
      all.push({ shot, rally, next: rally.shots[i + 1] || null, v: f.initial_speed_kmh });
    });
  });
  const pick = (list) => {
    if (!list.length) return null;
    const sorted = list.map((c) => c.v).sort((a, b) => a - b);
    const p90 = sorted[Math.min(sorted.length - 1, Math.floor(0.9 * (sorted.length - 1)))];
    const cap = Math.min(p90, 300);
    return list.filter((c) => c.v <= cap).sort((a, b) => b.v - a.v)[0] || null;
  };
  return pick(all.filter((c) => c.shot.family === 'smash')) || pick(all);
}

// ---------- geometry ----------

export function invert3(m) {
  const [a, b, c] = m[0];
  const [d, e, f] = m[1];
  const [g, h, i] = m[2];
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-12) return null;
  const s = 1 / det;
  return [
    [A * s, -(b * i - c * h) * s, (b * f - c * e) * s],
    [B * s, (a * i - c * g) * s, -(a * f - c * d) * s],
    [C * s, -(a * h - b * g) * s, (a * e - b * d) * s],
  ];
}

export function apply3(m, x, y) {
  const X = m[0][0] * x + m[0][1] * y + m[0][2];
  const Y = m[1][0] * x + m[1][1] * y + m[1][2];
  const W = m[2][0] * x + m[2][1] * y + m[2][2];
  if (Math.abs(W) < 1e-9) return null;
  return [X / W, Y / W];
}

// ---------- formatting ----------

export function clock(s) {
  if (s == null || !isFinite(s)) return '0:00';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
}

export const pct = (share) => (share == null ? '–' : `${Math.round(share * 100)}%`);

const LABELS = {
  clear: 'Clear',
  drive: 'Drive',
  smash: 'Smash',
  net: 'Net shot',
  drop: 'Drop',
  lift: 'Lift',
  block: 'Block',
  push: 'Push',
  net_kill: 'Net kill',
  other: 'Other',
  serve_short: 'Short serve',
  serve_long: 'Long serve',
  serve: 'Serve',
  unknown: 'Unknown',
};
export const label = (k) => LABELS[k] || (k ? k[0].toUpperCase() + k.slice(1).replace('_', ' ') : 'Unknown');
export const lower = (k) => label(k).toLowerCase();

export function shotLabel(shot) {
  if (!shot) return null;
  if (shot.kind === 'serve') return shot.serve_type ? `serve_${shot.serve_type}` : 'serve';
  return shot.family || 'unknown';
}

export function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

export const reducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
