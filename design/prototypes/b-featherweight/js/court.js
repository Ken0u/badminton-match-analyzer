// Hairline top-down court diagrams in SVG. SVG units are court metres:
// x across (0..6.1), y along (0..13.4, far baseline at 0), net at y = 6.7.

export const W = 6.1;
export const L = 13.4;
export const NET = 6.7;

export function courtLines({ half = null } = {}) {
  const y0 = half === 'near' ? NET : 0;
  const y1 = half === 'far' ? NET : L;
  const seg = (x1, ya, x2, yb, cls = '') =>
    `<line class="cl ${cls}" x1="${x1}" y1="${ya}" x2="${x2}" y2="${yb}" vector-effect="non-scaling-stroke"/>`;
  const out = [];
  out.push(`<rect class="cl-floor" x="0" y="${y0}" width="${W}" height="${y1 - y0}"/>`);
  out.push(seg(0, y0, 0, y1), seg(W, y0, W, y1), seg(0.46, y0, 0.46, y1), seg(5.64, y0, 5.64, y1));
  if (half !== 'near') {
    out.push(seg(0, 0, W, 0), seg(0, 0.76, W, 0.76), seg(0, 4.72, W, 4.72), seg(3.05, 0, 3.05, 4.72));
  }
  if (half !== 'far') {
    out.push(seg(0, L, W, L), seg(0, 12.64, W, 12.64), seg(0, 8.68, W, 8.68), seg(3.05, 8.68, 3.05, L));
  }
  out.push(seg(-0.25, NET, W + 0.25, NET, 'net'));
  return out.join('');
}

/** A court SVG element string. `inner` is drawn on top of the lines, in metres. */
export function courtSVG({ half = null, inner = '', pad = 0.45, cls = '', label = '' } = {}) {
  const y0 = half === 'near' ? NET - 0.3 : -pad;
  const h = half ? L / 2 + 0.3 + pad : L + pad * 2;
  return `<svg class="court ${cls}" viewBox="${-pad} ${y0} ${W + pad * 2} ${h}" role="img" aria-label="${label}">
    ${courtLines({ half })}${inner}</svg>`;
}

/** Turn a point so the given end is the near end (y from 6.7 to 13.4). */
export function toNear(p) {
  if (p.y >= NET) return p;
  return { ...p, x: W - p.x, y: L - p.y };
}
