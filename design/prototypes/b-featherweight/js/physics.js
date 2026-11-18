// Shuttle flight with gravity and quadratic air drag.
// A feather shuttle's terminal velocity is about 6.8 m/s, which sets the drag
// constant: a 400 km/h smash is down near 120 km/h a tenth of a second later,
// matching the fitted `speed_settled_kmh` values in the data.
export const G = 9.81;
export const VT = 6.8;
export const K = G / (VT * VT);

/** Simulate a flight in a vertical plane. x is horizontal distance (m), y height (m). */
export function simulate(v0, thetaDeg, h0, { maxX = 40, dt = 0.0005, tmax = 6 } = {}) {
  const th = (thetaDeg * Math.PI) / 180;
  let vx = v0 * Math.cos(th);
  let vy = v0 * Math.sin(th);
  let x = 0;
  let y = h0;
  let t = 0;
  const pts = [{ t, x, y, v: v0 }];
  while (t < tmax) {
    const v = Math.hypot(vx, vy);
    vx += -K * v * vx * dt;
    vy += (-G - K * v * vy) * dt;
    x += vx * dt;
    y += vy * dt;
    t += dt;
    pts.push({ t, x, y, v: Math.hypot(vx, vy) });
    if (y <= 0 || x >= maxX) break;
  }
  return pts;
}

/** Height when the flight first reaches horizontal distance D, or null. */
function heightAt(pts, D) {
  for (let i = 1; i < pts.length; i++) {
    if (pts[i].x >= D) {
      const a = pts[i - 1];
      const b = pts[i];
      const f = (D - a.x) / (b.x - a.x || 1);
      return { y: a.y + (b.y - a.y) * f, i };
    }
  }
  return null;
}

/**
 * Pick a launch angle so the flight from height h0 reaches distance D at about
 * hEnd metres high, preferring the angle whose apex is near the measured apex.
 * Returns the flight trimmed at D.
 */
export function solveToTarget(v0, h0, D, { hEnd = 1.0, apex = null } = {}) {
  let best = null;
  for (let th = -50; th <= 80; th += 0.5) {
    const pts = simulate(v0, th, h0, { maxX: D + 0.01, dt: 0.0008 });
    const hit = heightAt(pts, D);
    const top = Math.max(...pts.map((p) => p.y));
    const err = hit ? Math.abs(hit.y - hEnd) : 50 + (D - pts[pts.length - 1].x);
    const score = err + (apex != null ? 0.25 * Math.abs(top - Math.max(apex, h0)) : 0);
    if (!best || score < best.score) best = { th, score, hit };
  }
  const pts = simulate(v0, best.th, h0, { maxX: D, dt: 0.0005 });
  return { theta: best.th, pts };
}

/** Pick a launch angle whose apex matches `apex`; downward shots get a fixed dip. */
export function solveForApex(v0, h0, apex, maxX = 13.4) {
  let theta = -9;
  if (apex != null && apex > h0 + 0.08) {
    let lo = 0;
    let hi = 85;
    for (let k = 0; k < 28; k++) {
      const mid = (lo + hi) / 2;
      const top = Math.max(...simulate(v0, mid, h0, { maxX, dt: 0.002 }).map((p) => p.y));
      if (top < apex) lo = mid;
      else hi = mid;
    }
    theta = (lo + hi) / 2;
  }
  return { theta, pts: simulate(v0, theta, h0, { maxX, dt: 0.001 }) };
}

export const kmh = (ms) => ms * 3.6;
export const ms = (kmh) => kmh / 3.6;
