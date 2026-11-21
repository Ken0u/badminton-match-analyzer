// Angles in radians. The forearm rolls about its long axis; the hand hinges
// and tilts at the wrist. Grip changes turn the handle inside the hand.
const pose = (sx, sz, ex, rx, tw, roll, tilt) => ({ sx, sz, ex, rx, tw, roll, tilt });
export const READY = pose(-0.98, -0.26, -1.17, -0.67, 0, 0, 0);
const key = (time, ...angles) => [time, pose(...angles)];
const stroke = (start, keys, end) => [[start, READY], ...keys, [end, READY]];

// Overheads show a similar threat until the elbow leads and the head drops.
// The clear extends up and out; the smash turns over and finishes down;
// the drop keeps its reach but takes pace off with a checked finish.
const overheadSet = key(-0.19, -2.00,-1.02,-2.02,-0.80,0.65,-0.66,-0.18);
const swings = {
  clear: stroke(-0.51, [overheadSet, key(-0.075,-2.83,-0.64,-1.25,-0.89,0.33,-0.71,-0.19),
    key(0,-2.97,-0.17,-0.18,-0.16,-0.06,0.46,0.02), key(0.17,-1.65,0.28,-0.49,0.15,-0.34,1.16,0.14)], 0.54),
  smash: stroke(-0.54, [overheadSet, key(-0.066,-2.80,-0.74,-1.40,-0.99,0.40,-0.84,-0.24),
    key(0,-2.82,-0.18,-0.17,-0.10,-0.12,0.57,0.06), key(0.14,-0.83,0.46,-0.49,0.35,-0.50,1.35,0.23)], 0.62),
  drop: stroke(-0.48, [overheadSet, key(-0.08,-2.73,-0.63,-1.16,-0.66,0.28,-0.45,-0.14),
    key(0,-2.81,-0.21,-0.29,-0.22,-0.04,-0.05,0.02), key(0.11,-2.43,0.03,-0.44,-0.08,-0.19,0.27,0.09)], 0.43),
  net_kill: stroke(-0.27, [key(-0.065,-2.00,-0.48,-0.99,-0.68,0.16,-0.36,-0.17),
    key(0,-2.09,-0.23,-0.31,-0.11,-0.02,0.17,0.04), key(0.08,-1.48,-0.08,-0.42,0.18,-0.13,0.62,0.16)], 0.31),
  drive: stroke(-0.34, [key(-0.095,-1.39,-0.96,-1.28,-0.62,0.34,-0.55,-0.15),
    key(0,-1.55,-0.26,-0.31,-0.18,0.02,0.09,0.02), key(0.11,-1.46,0.31,-0.51,0.12,-0.29,0.66,0.12)], 0.37),
  backhand_drive: stroke(-0.29, [key(-0.08,-1.13,0.16,-1.04,-0.41,-0.16,-0.58,-0.18),
    key(0,-1.44,0.12,-0.56,-0.16,0.04,0.05,0.02), key(0.08,-1.52,0.17,-0.40,-0.08,0.12,0.57,0.12)], 0.31),
  // Lead the push with the hand. As the elbow opens the upper arm rises,
  // keeping the head on a shallow forward path rather than chopping down.
  push: stroke(-0.34, [key(-0.14,-0.79,-0.37,-1.28,-0.19,0.08,-0.10,-0.04),
    key(0,-1.22,-0.34,-0.70,-0.18,0.01,0.01,0), key(0.095,-1.37,-0.32,-0.51,-0.17,-0.03,0.09,0.03)], 0.34),
  backhand_push: stroke(-0.32, [key(-0.13,-0.85,0.10,-1.35,-0.15,-0.06,-0.12,-0.06),
    key(0,-1.28,0.12,-0.76,-0.15,0.01,0.02,0), key(0.085,-1.42,0.13,-0.54,-0.14,0.06,0.12,0.04)], 0.32),
  // Lower the head in front during preparation; meet the shuttle with a
  // short lift of the hand, then let the elbow yield to the incoming pace.
  block: stroke(-0.40, [key(-0.19,-0.57,-0.28,-0.67,0.33,0.05,-0.18,-0.10),
    key(-0.075,-0.68,-0.26,-0.64,0.26,0.03,-0.15,-0.09),
    key(0,-1.03,-0.24,-0.62,0.08,0,-0.04,-0.02), key(0.09,-1.04,-0.22,-0.81,0.12,-0.03,0.03,0.02)], 0.32),
  lift: stroke(-0.40, [key(-0.13,0.28,-0.49,-0.56,0.46,0.29,-0.62,-0.20),
    key(0,-0.91,-0.26,-0.28,-0.34,0,-0.09,0.02), key(0.17,-1.94,0.09,-0.76,-0.57,-0.25,0.72,0.18)], 0.51),
  net: stroke(-0.30, [key(-0.09,-0.82,-0.31,-0.74,-0.29,0.10,-0.17,-0.06),
    key(0,-1.04,-0.27,-0.40,-0.31,0,-0.09,0), key(0.10,-1.13,-0.23,-0.43,-0.35,-0.03,0.09,0.07)], 0.31),
  serve_short: stroke(-0.34, [key(-0.10,-0.67,-0.24,-0.84,0.45,0.04,-0.14,-0.06),
    key(0,-0.74,-0.22,-0.65,0.38,0,-0.04,0), key(0.09,-0.79,-0.20,-0.60,0.31,-0.03,0.12,0.04)], 0.32),
  serve_long: stroke(-0.48, [key(-0.16,0.36,-0.55,-0.64,0.51,0.36,-0.53,-0.17),
    key(0,-0.77,-0.28,-0.36,-0.21,0.03,0.02,0.03), key(0.23,-1.86,0.17,-0.83,-0.55,-0.24,0.59,0.14)], 0.60),
  serve: stroke(-0.35, [key(-0.11,-0.36,-0.30,-0.88,0.32,0.12,-0.24,-0.09),
    key(0,-0.78,-0.25,-0.59,0.16,0,0,0), key(0.14,-1.04,-0.18,-0.57,-0.10,-0.07,0.24,0.06)], 0.38),
  neutral: stroke(-0.32, [key(-0.10,-1.12,-0.46,-1.13,-0.53,0.18,-0.22,-0.08),
    key(0,-1.40,-0.24,-0.58,-0.23,0,0,0), key(0.13,-1.33,0.02,-0.61,-0.13,-0.13,0.27,0.07)], 0.37),
};
export const strokeKeys = (label, backhand) => (backhand && swings[`backhand_${label}`]) || swings[label] || swings.neutral;

// Axial orientation of the string bed relative to the palm (not an arm
// rotation). Carry the edge forward like a knife; settle onto the chosen
// bevel before acceleration, then release back to the neutral carry.
const EDGE = 1.40, V_GRIP = 0.94, THUMB_GRIP = -0.13;
function ease(a, b, t) {
  const u = Math.min(1, Math.max(0, (t - a) / (b - a)));
  return u*u*(3-2*u);
}
export function gripAt(label, side, t) {
  if (!Number.isFinite(t)) return { angle: EDGE, thumb: 0 };
  const keys = strokeKeys(label, side === 'backhand');
  const start = keys[0][0], end = keys.at(-1)[0];
  const held = ease(start, keys[1][0], t) * (1 - ease(keys.at(-2)[0], end, t));
  // Defend thumb-first; only change bevel late if the recorded block is
  // explicitly forehand. This staging default is not a new shot label.
  const thumb = label === 'block' ? (side === 'forehand' ? 1-ease(-0.15,-0.035,t) : 1)
    : side === 'backhand' ? 1 : 0;
  return { angle: EDGE + held*(V_GRIP + thumb*(THUMB_GRIP-V_GRIP) - EDGE), thumb: held*thumb };
}

// Shape-preserving cubic interpolation. A joint moving through impact keeps
// its velocity there; a joint checking or reversing its swing eases to a stop.
function tangent(keys, i, joint) {
  if (!i || i === keys.length - 1) return 0;
  const [t, p] = keys[i], [a, prev] = keys[i-1], [b, next] = keys[i+1];
  const left = (p[joint]-prev[joint])/(t-a), right = (next[joint]-p[joint])/(b-t);
  return left * right > 0 ? 2 * left * right / (left + right) : 0;
}
export function swingPose(label, backhand, t) {
  const keys = strokeKeys(label, backhand);
  if (!(t > keys[0][0] && t < keys.at(-1)[0])) return READY;
  const i = keys.findIndex(([time]) => time >= t) - 1;
  const [a, p] = keys[i], [b, q] = keys[i+1], span = b-a, u = (t-a)/span, v = 1-u;
  const result = {};
  for (const joint in READY) {
    result[joint] = v*v*(1+2*u)*p[joint] + u*u*(3-2*u)*q[joint]
      + span*u*v*(v*tangent(keys,i,joint) - u*tangent(keys,i+1,joint));
  }
  return result;
}
