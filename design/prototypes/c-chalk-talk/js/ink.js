// Marker-stroke helpers. The wobble lives in the strokes only; every endpoint
// passed in is drawn exactly where the data puts it.

export function rng(seed = 1) {
  let s = (Math.abs(Math.floor(seed)) % 2147483646) + 1;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}

const f = (n) => Math.round(n * 10) / 10;

// A hand-drawn loop: a little more than one turn, start and end overlapping.
export function loopPath(cx, cy, rx, ry, seed = 3, turns = 1.12) {
  const r = rng(seed);
  const start = r() * Math.PI * 2;
  const steps = 40;
  const wob = 0.06;
  let d = '';
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const a = start + t * turns * Math.PI * 2;
    const k = 1 + (r() - 0.5) * wob + t * 0.07;
    const x = cx + Math.cos(a) * rx * k;
    const y = cy + Math.sin(a) * ry * k;
    d += (i ? 'L' : 'M') + f(x) + ' ' + f(y);
  }
  return d;
}

// Closed polyline through projected points, drawn as a marker loop.
export function polyLoop(points, overshoot = 4) {
  if (!points.length) return '';
  const pts = points.concat(points.slice(0, overshoot));
  return pts.map((p, i) => (i ? 'L' : 'M') + f(p.x) + ' ' + f(p.y)).join('');
}

// A slightly bowed stroke from a to b with an arrowhead at b.
export function arrowPath(x1, y1, x2, y2, bow = 0.12, head = 10) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy) || 1;
  const nx = -dy / len;
  const ny = dx / len;
  const mx = (x1 + x2) / 2 + nx * len * bow;
  const my = (y1 + y2) / 2 + ny * len * bow;
  const body = `M${f(x1)} ${f(y1)}Q${f(mx)} ${f(my)} ${f(x2)} ${f(y2)}`;
  // tangent at the end of a quadratic: (end - control)
  const tx = x2 - mx;
  const ty = y2 - my;
  const tl = Math.hypot(tx, ty) || 1;
  const ux = tx / tl;
  const uy = ty / tl;
  const h = Math.min(head, len * 0.45);
  const a1 = `M${f(x2 - ux * h - uy * h * 0.55)} ${f(y2 - uy * h + ux * h * 0.55)}L${f(x2)} ${f(y2)}L${f(x2 - ux * h + uy * h * 0.55)} ${f(y2 - uy * h - ux * h * 0.55)}`;
  return { body, head: a1, mid: { x: mx * 0.5 + (x1 + x2) * 0.25, y: my * 0.5 + (y1 + y2) * 0.25 } };
}

export function crossPath(x, y, s) {
  return `M${f(x - s)} ${f(y - s)}L${f(x + s)} ${f(y + s)}M${f(x + s * 0.9)} ${f(y - s * 1.05)}L${f(x - s * 1.05)} ${f(y + s * 0.9)}`;
}

export function ringPath(x, y, s, seed = 7) {
  return loopPath(x, y, s, s, seed, 1.15);
}

// A hand-drawn underline under a label.
export function underlinePath(x1, x2, y, seed = 11) {
  const r = rng(seed);
  const m = (x1 + x2) / 2;
  return `M${f(x1)} ${f(y + (r() - 0.5) * 2)}Q${f(m)} ${f(y + 3 + r() * 2)} ${f(x2)} ${f(y - 1 - r() * 2)}`;
}

// Animate the drawing of SVG paths (stroke-dashoffset), honouring reduced motion.
export function drawOn(paths, { duration = 420, delay = 0 } = {}) {
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  for (const p of paths) {
    if (!p || !p.getTotalLength) continue;
    if (reduce) continue;
    let L = 0;
    try {
      L = p.getTotalLength();
    } catch {
      continue;
    }
    if (!L) continue;
    p.style.strokeDasharray = `${L} ${L}`;
    p.style.strokeDashoffset = `${L}`;
    p.animate([{ strokeDashoffset: L }, { strokeDashoffset: 0 }], {
      duration,
      delay,
      easing: 'cubic-bezier(.3,.1,.2,1)',
      fill: 'forwards',
    });
  }
}

export const SVGNS = 'http://www.w3.org/2000/svg';
export function svgEl(tag, attrs = {}, parent) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  if (parent) parent.appendChild(el);
  return el;
}
