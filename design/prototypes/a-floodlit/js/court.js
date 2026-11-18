// Court drawn in SVG, in metres. x 0..6.1 across, y 0..13.4 from the far baseline.
export const W = 6.1, L = 13.4;

export function courtLines({ stroke = 'var(--line)', width = 0.05, singles = false } = {}) {
  const l = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}"/>`;
  const parts = [
    `<rect x="0" y="0" width="${W}" height="${L}" fill="none"/>`,
    l(0.46, 0, 0.46, L), l(5.64, 0, 5.64, L),
    l(0, 0.76, W, 0.76), l(0, 12.64, W, 12.64),
    l(0, 4.72, W, 4.72), l(0, 8.68, W, 8.68),
    l(W / 2, 0, W / 2, 4.72), l(W / 2, 8.68, W / 2, L),
  ];
  return `<g class="court-lines" stroke="${stroke}" stroke-width="${width}" fill="none" ${singles ? 'data-singles' : ''}>${parts.join('')}</g>
    <g class="court-net"><line x1="-0.35" y1="6.7" x2="${W + 0.35}" y2="6.7"/><circle cx="-0.35" cy="6.7" r="0.09"/><circle cx="${W + 0.35}" cy="6.7" r="0.09"/></g>`;
}

/** A full court SVG with a margin of `m` metres; `inner` is drawn on top of the lines. */
export function courtSVG({ m = 1, inner = '', under = '', cls = '', label = '' } = {}) {
  return `<svg class="court ${cls}" viewBox="${-m} ${-m} ${W + 2 * m} ${L + 2 * m}" role="img" aria-label="${label}">
    <rect class="court-mat" x="${-m}" y="${-m}" width="${W + 2 * m}" height="${L + 2 * m}" rx="0.15"/>
    ${under}${courtLines()}${inner}</svg>`;
}

/** Court line segments in metres, for projecting into the video. */
export function courtSegments() {
  return [
    [[0, 0], [W, 0]], [[W, 0], [W, L]], [[W, L], [0, L]], [[0, L], [0, 0]],
    [[0.46, 0], [0.46, L]], [[5.64, 0], [5.64, L]],
    [[0, 0.76], [W, 0.76]], [[0, 12.64], [W, 12.64]],
    [[0, 4.72], [W, 4.72]], [[0, 8.68], [W, 8.68]],
    [[W / 2, 0], [W / 2, 4.72]], [[W / 2, 8.68], [W / 2, L]],
  ];
}
