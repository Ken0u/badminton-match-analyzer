// Court drawn in SVG, in metres. x 0..6.1 across, y 0..13.4 from the far baseline.
export const W = 6.1,
  L = 13.4;

type Segment = [[number, number], [number, number]];

/** Court line segments in metres, for drawing and projecting into the video. */
export function courtSegments(): Segment[] {
  return [
    [
      [0, 0],
      [W, 0],
    ],
    [
      [W, 0],
      [W, L],
    ],
    [
      [W, L],
      [0, L],
    ],
    [
      [0, L],
      [0, 0],
    ],
    [
      [0.46, 0],
      [0.46, L],
    ],
    [
      [5.64, 0],
      [5.64, L],
    ],
    [
      [0, 0.76],
      [W, 0.76],
    ],
    [
      [0, 12.64],
      [W, 12.64],
    ],
    [
      [0, 4.72],
      [W, 4.72],
    ],
    [
      [0, 8.68],
      [W, 8.68],
    ],
    [
      [W / 2, 0],
      [W / 2, 4.72],
    ],
    [
      [W / 2, 8.68],
      [W / 2, L],
    ],
  ];
}

export function CourtLines({ width = 0.05 }: { width?: number }) {
  return (
    <>
      <g
        className="court-lines"
        stroke="var(--line)"
        strokeWidth={width}
        fill="none"
      >
        <rect x={0} y={0} width={W} height={L} fill="none" />
        {courtSegments()
          .slice(4)
          .map(([a, b], i) => (
            <line key={i} x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} />
          ))}
      </g>
      <g className="court-net">
        <line x1={-0.35} y1={6.7} x2={W + 0.35} y2={6.7} />
        <circle cx={-0.35} cy={6.7} r={0.09} />
        <circle cx={W + 0.35} cy={6.7} r={0.09} />
      </g>
    </>
  );
}
