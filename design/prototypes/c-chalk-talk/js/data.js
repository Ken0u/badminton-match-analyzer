// Data access, session state and geometry helpers shared by every screen.

const params = new URLSearchParams(location.search);
export const FUTURE = params.get('future') === '1';
export const THIN = 5; // below this sample size a number is not shown

const STORE_KEY = 'chalk-talk-session';

export function readSession() {
  try {
    return JSON.parse(sessionStorage.getItem(STORE_KEY) || 'null') || {};
  } catch {
    return {};
  }
}

export function writeSession(patch) {
  const next = { ...readSession(), ...patch };
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(next));
  } catch {
    /* private mode: state lives for this page only */
  }
  memorySession = next;
  return next;
}

let memorySession = null;
export function session() {
  return memorySession || (memorySession = readSession());
}

export function matchKey() {
  const fromUrl = params.get('match');
  if (fromUrl === 'singles' || fromUrl === 'doubles') return fromUrl;
  const s = session();
  return s.mode === 'singles' ? 'singles' : 'doubles';
}

export const dataBase = (key = matchKey()) => `../data/${key}`;

const cache = new Map();
export function loadMatch(key = matchKey()) {
  if (!cache.has(key)) {
    cache.set(
      key,
      Promise.all([
        fetch(`${dataBase(key)}/analysis.json`).then((r) => {
          if (!r.ok) throw new Error(`analysis.json: ${r.status}`);
          return r.json();
        }),
        fetch(`${dataBase(key)}/stats.json`).then((r) => {
          if (!r.ok) throw new Error(`stats.json: ${r.status}`);
          return r.json();
        }),
      ]).then(([analysis, stats]) => ({ key, analysis, stats }))
    );
  }
  return cache.get(key);
}

// Display names: the names typed at upload, as assigned on the confirmation
// screen, fall back to the document's own names.
export function displayNames(analysis) {
  const s = session();
  const out = {};
  for (const p of analysis.players) {
    out[p.id] = (s.key === matchKey() && s.assigned && s.assigned[p.id]) || p.name || p.id;
  }
  return out;
}

export function teamName(analysis, team, names = displayNames(analysis)) {
  const ids = analysis.players.filter((p) => p.team === team).map((p) => p.id);
  if (ids.length === 1) return names[ids[0]];
  const all = Object.values(names).map(firstName);
  const firstsUnique = new Set(all).size === all.length;
  return ids.map((id) => (firstsUnique ? firstName(names[id]) : names[id])).join(' & ');
}

export function firstName(n) {
  return String(n).split(/\s+/)[0];
}

export function initials(n) {
  const parts = String(n).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return '?';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export const TEAM_COLOR = { T1: 'var(--blue)', T2: 'var(--red)' };
export const TEAM_HEX = { T1: '#1F57C3', T2: '#D3362D' };

export function teamOf(analysis, pid) {
  const p = analysis.players.find((q) => q.id === pid);
  return p ? p.team : null;
}

// ---- labels ---------------------------------------------------------------

const LABELS = {
  clear: 'clear',
  drive: 'drive',
  smash: 'smash',
  net: 'net shot',
  drop: 'drop',
  lift: 'lift',
  block: 'block',
  push: 'push',
  net_kill: 'net kill',
  other: 'other shot',
  serve_short: 'short serve',
  serve_long: 'long serve',
  serve: 'serve',
  unknown: 'unknown',
};
export const label = (k) => LABELS[k] || String(k).replace(/_/g, ' ');
export const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function shotLabel(shot) {
  if (!shot) return '';
  if (shot.kind === 'serve') return shot.serve_type ? `${shot.serve_type} serve` : 'serve';
  if (shot.family) return label(shot.family);
  return 'shot';
}

// ---- geometry -------------------------------------------------------------

export function invert3(m) {
  const [a, b, c] = m[0];
  const [d, e, f] = m[1];
  const [g, h, i] = m[2];
  const A = e * i - f * h;
  const B = -(d * i - f * g);
  const C = d * h - e * g;
  const det = a * A + b * B + c * C;
  if (Math.abs(det) < 1e-12) return null;
  const k = 1 / det;
  return [
    [A * k, -(b * i - c * h) * k, (b * f - c * e) * k],
    [B * k, (a * i - c * g) * k, -(a * f - c * d) * k],
    [C * k, -(a * h - b * g) * k, (a * e - b * d) * k],
  ];
}

export function apply3(m, x, y) {
  const X = m[0][0] * x + m[0][1] * y + m[0][2];
  const Y = m[1][0] * x + m[1][1] * y + m[1][2];
  const Z = m[2][0] * x + m[2][1] * y + m[2][2];
  if (Math.abs(Z) < 1e-9) return null;
  return { x: X / Z, y: Y / Z };
}

// Court view for a frame (half-open ranges); inverse homography cached.
export function viewForFrame(analysis, frame) {
  for (const v of analysis.court.views) {
    if (frame >= v.start_frame && frame < v.end_frame) {
      if (!v._inv) v._inv = invert3(v.homography);
      return v;
    }
  }
  return null;
}

// Person court position at time t from the 10 Hz tracks (linear between samples).
export function positionAt(analysis, pid, t) {
  const tr = analysis.tracks;
  const p = tr.persons.find((q) => q.person_id === pid);
  if (!p) return null;
  const k = t * tr.rate_hz;
  const k0 = Math.floor(k);
  const f = k - k0;
  const a = sample(p, k0);
  const b = sample(p, k0 + 1);
  if (a && b) return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f };
  return a || b;
}

function sample(p, k) {
  if (k < 0 || k >= p.x.length) return null;
  const x = p.x[k];
  const y = p.y[k];
  return x == null || y == null ? null : { x, y };
}

// Last known position at or before t, within `within` seconds.
export function lastKnownPosition(analysis, pid, t, within = 1.5) {
  const tr = analysis.tracks;
  const p = tr.persons.find((q) => q.person_id === pid);
  if (!p) return null;
  const direct = positionAt(analysis, pid, t);
  if (direct) return direct;
  const k = Math.floor(t * tr.rate_hz);
  for (let j = k; j >= Math.max(0, k - within * tr.rate_hz); j--) {
    const s = sample(p, j);
    if (s) return s;
  }
  return null;
}

// ---- formatting -----------------------------------------------------------

export const pct = (share) => (share == null ? '–' : `${Math.round(share * 100)}%`);
export function clock(s) {
  if (!isFinite(s)) return '0:00';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${String(r).padStart(2, '0')}`;
}
export const secs = (s) => `${s.toFixed(1)} s`;

export function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
}

export const prefersReducedMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
