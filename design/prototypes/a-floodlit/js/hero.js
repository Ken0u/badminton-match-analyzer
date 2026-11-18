// The landing hero: one real rally replayed on a court in a floodlit hall.
import * as THREE from 'three';
import { positionAt, shotLabel, labelText, speedOf, teamOf, estimatePace, estimateBow } from './data.js';

const COURT_W = 6.1, COURT_L = 13.4;
const NET_TOP = 1.55;
const TEAM_COLOR = { T1: 0xf2b23e, T2: 0x86c9f2 };
const FLOOD = 0xffe6b0;
// Court metres to scene: x across, z along (far baseline negative), y up.
const toScene = (p, h = 0) => new THREE.Vector3(p.x - COURT_W / 2, h, p.y - COURT_L / 2);

/** Racket height at contact by stroke, in metres. */
const CONTACT_H = { smash: 2.55, clear: 2.4, drop: 2.3, net_kill: 1.9, drive: 1.35, push: 1.0, block: 0.8,
  lift: 0.6, net: 0.65, other: 1.3, serve_short: 1.0, serve_long: 1.0, serve: 1.0, unknown: 1.2 };
const HIGH = new Set(['lift', 'clear', 'serve_long']);

export function pickRally(match) {
  const want = new URLSearchParams(location.search).get('rally');
  const rallies = match.analysis.rallies;
  if (want) { const r = rallies.find((x) => x.id === `rally-${want}`); if (r) return r; }
  let best = null, score = -1;
  for (const r of rallies) {
    const shots = r.shots;
    if (shots.length < 6 || !shots[shots.length - 1].landing?.position) continue;
    const cover = shots.filter((s) => s.hitter_position).length / shots.length;
    const fast = shots.filter((s) => ['smash', 'net_kill'].includes(s.family)).length;
    const s = cover * 10 + Math.min(shots.length, 24) + fast * 0.8;
    if (s > score) { score = s; best = r; }
  }
  return best || rallies[0];
}

/** Build the shuttle's flight plan between contacts. */
function buildFlights(match, rally) {
  const shots = rally.shots;
  const contactPoint = (shot) => {
    let p = shot.hitter_position || positionAt(match, shot.hitter_id, shot.time_s);
    if (!p) p = { x: COURT_W / 2, y: COURT_L / 2 };
    // the racket meets the shuttle a little in front of the feet, toward the net
    const toNet = p.y < COURT_L / 2 ? 0.45 : -0.45;
    const label = shotLabel(shot);
    return { pos: toScene({ x: p.x + 0.25, y: p.y + toNet }, CONTACT_H[label] ?? 1.2), label };
  };
  const flights = [];
  for (let i = 0; i < shots.length; i++) {
    const s = shots[i];
    const a = contactPoint(s);
    let b, t1;
    if (i + 1 < shots.length) {
      b = contactPoint(shots[i + 1]).pos; t1 = shots[i + 1].time_s;
    } else if (s.landing?.position) {
      b = toScene(s.landing.position, 0.04); t1 = Math.max(s.landing.time_s, s.time_s + 0.4);
    } else {
      const dir = a.pos.z < 0 ? 1 : -1;
      b = new THREE.Vector3(a.pos.x, 0.04, dir * 5.5); t1 = s.time_s + 1.1;
    }
    const h0 = a.pos.y, h1 = b.y;
    let apex = s.flight?.apex_m;
    if (apex == null || s.flight?.quality === 'poor_fit') apex = HIGH.has(a.label) ? Math.max(h0, h1) + 3 : Math.max(h0, h1) + 0.3;
    apex = Math.min(Math.max(apex, Math.max(h0, h1)), 9);
    const drag = HIGH.has(a.label) ? 2.2 : 1.3;
    const measuredDrag = estimatePace(match, s, shots[i+1], drag);
    flights.push({ shot: s, label: a.label, from: a.pos, to: b, t0: s.time_s, t1, apex, netFault: i === shots.length - 1 && rally.outcome?.detail === 'net', drag: measuredDrag ?? drag });
  }
  return flights;
}

// Fit the displayed shuttle, not just its cork centre, after both racket
// endpoints are final. Only change curvature when a real crossing needs it.
function fitNet(f, scale, match, nextShot) {
  const h = f.from.y, dy = f.to.y - h, D = Math.max(f.apex, h, f.to.y) - h;
  const q = 2*D - dy;
  f.curve = D <= 0.001 ? 0 : q + Math.sqrt(Math.max(q*q - dy*dy, 0));
  if (match && nextShot) f.curve = estimateBow(match, f.shot, nextShot, f.drag, f.curve);
  if (f.netFault) {
    // The reported landing can be on the other side even on a labelled
    // fault. Stage a mesh impact, then drop on the hitter's side; do not
    // rewrite the recorded location or extend the rally clock.
    const side = Math.sign(f.from.z) || 1;
    const z = side * Math.min(0.055, Math.abs(f.from.z));
    const u = clamp(Math.abs(f.from.z)/(Math.abs(f.from.z)+Math.abs(f.to.z)+0.001), 0, 1);
    f.meshHit = new THREE.Vector3(lerp(f.from.x,f.to.x,u), NET_TOP-0.14, z);
    f.meshHit.x = clamp(f.meshHit.x, -COURT_W/2+0.07, COURT_W/2-0.07);
    f.fall = new THREE.Vector3(f.meshHit.x, 0.04, z + side*0.30);
    return;
  }
  f.netArc = null;
  const dz = f.to.z - f.from.z;
  if (f.from.z * f.to.z >= 0 || Math.abs(dz) < 1e-6) return;
  const cross = -f.from.z/dz;
  if (Math.abs(lerp(f.from.x,f.to.x,cross)) > COURT_W/2 + 0.087*scale) return;
  // Endpoints and drag timing stay fixed. Add only concave curvature:
  // the skewed arch peaks near the net even on asymmetric short shots,
  // but cannot create a second lift or a shelf at the tape.
  const endZ = f.to.y < 0.05 ? Math.sign(f.to.z)*Math.max(Math.abs(f.to.z),0.087*scale+0.12) : f.to.z;
  const span = endZ - f.from.z, at = clamp(-f.from.z/span, 0.001, 0.999);
  const arc = f.netArc = { endZ, left: at*at, right: (1-at)**2, lift: 0 };
  const reach = 0.087 * scale + 0.008;
  const lo = clamp(at-reach/Math.abs(span),0,1), hi = clamp(at+reach/Math.abs(span),0,1);
  const dx = f.to.x-f.from.x;
  function clears(lift) {
    arc.lift = lift;
    for (let i=0; i<=128; i++) {
      const u = lerp(lo,hi,i/128), denom = lerp(arc.left,arc.right,u);
      const rise = dy + f.curve*(1-2*u) + lift*(arc.left*(1-u)**2-arc.right*u*u)/(denom*denom);
      const len = Math.hypot(dx,rise,span), ny=rise/len, nz=span/len;
      const z = f.from.z+span*u;
      // Cork at the origin; the rim is 78 mm aft and 34 mm wide in
      // radius. Project its envelope along the actual flight tangent.
      const rimZ = z - scale*0.078*nz, rz = scale*0.034*Math.sqrt(Math.max(0,1-nz*nz));
      if (Math.min(z-scale*0.016,rimZ-rz)>0.009 || Math.max(z+scale*0.016,rimZ+rz)<-0.009) continue;
      const bottom = scale*Math.max(0.016, 0.078*ny+0.034*Math.sqrt(Math.max(0,1-ny*ny)));
      if (h+dy*u+f.curve*u*(1-u)+lift*u*(1-u)/denom-bottom < NET_TOP+0.025) return false;
    }
    return true;
  }
  if (clears(0)) return;
  let low=0, high=0.125;
  while (!clears(high) && high<16) high*=2;
  for (let i=0;i<15;i++) {const mid=(low+high)/2; if(clears(mid)) high=mid; else low=mid;}
  arc.lift=high;
}

function flightPoint(f, t, out) {
  const tt = clamp((t - f.t0) / Math.max(f.t1 - f.t0, 0.001), 0, 1);
  if (f.meshHit) {
    const duration = f.t1-f.t0;
    const at = clamp(1 - 0.49/Math.max(duration,0.001), 0.50, 0.86);
    if (tt >= at) {
      const v = (tt-at)/(1-at);
      out.lerpVectors(f.meshHit,f.fall,v);
      out.y = lerp(f.meshHit.y, f.fall.y, v*v);
      return out;
    }
    const u = (1-Math.exp(-f.drag*tt/at))/(1-Math.exp(-f.drag));
    out.lerpVectors(f.from,f.meshHit,u); out.y += 4*u*(1-u)*0.16;
    return out;
  }
  const u = (1 - Math.exp(-f.drag * tt)) / (1 - Math.exp(-f.drag));
  out.lerpVectors(f.from, f.to, u); out.y += f.curve*u*(1-u);
  if (f.netArc) {
    const {left,right,lift,endZ} = f.netArc;
    out.y += lift*u*(1-u)/lerp(left,right,u); out.z = lerp(f.from.z,endZ,u);
  }
  return out;
}

/* ---------- textures drawn on canvases ---------- */
function courtTexture() {
  const W = 1024, H = 2048, M = 0.9; // metres of mat beyond the outer lines
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const g = c.getContext('2d');
  const sx = W / (COURT_W + 2 * M), sy = H / (COURT_L + 2 * M);
  g.fillStyle = '#1e6a50'; g.fillRect(0, 0, W, H);
  // faint mat grain
  for (let i = 0; i < 2600; i++) {
    g.fillStyle = `rgba(${Math.random() < 0.5 ? '0,0,0' : '255,255,255'},${Math.random() * 0.035})`;
    g.fillRect(Math.random() * W, Math.random() * H, 2 + Math.random() * 6, 1);
  }
  g.fillStyle = '#eef2ea';
  const lw = 0.04;
  const X = (x) => (x + M) * sx, Y = (y) => (y + M) * sy;
  const hline = (y, x0 = 0, x1 = COURT_W) => g.fillRect(X(x0), Y(y) - (lw * sy) / 2, (x1 - x0) * sx, lw * sy);
  const vline = (x, y0 = 0, y1 = COURT_L) => g.fillRect(X(x) - (lw * sx) / 2, Y(y0), lw * sx, (y1 - y0) * sy);
  [0, COURT_L, 0.76, 12.64, 4.72, 8.68].forEach((y) => hline(y));
  [0, COURT_W, 0.46, 5.64].forEach((x) => vline(x));
  vline(COURT_W / 2, 0, 4.72); vline(COURT_W / 2, 8.68, COURT_L);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
  return { tex, w: COURT_W + 2 * M, l: COURT_L + 2 * M };
}
function floorTexture() {
  const c = document.createElement('canvas'); c.width = 512; c.height = 512;
  const g = c.getContext('2d');
  g.fillStyle = '#5a3f2a'; g.fillRect(0, 0, 512, 512);
  for (let x = 0; x < 512; x += 32) {
    for (let y = -64; y < 512; y += 128 + ((x * 7) % 64)) {
      const v = 70 + ((x * 13 + y * 3) % 30);
      g.fillStyle = `rgb(${v + 20},${v - 5},${v - 30})`;
      g.fillRect(x + 1, y + ((x / 32) % 3) * 40, 30, 126);
    }
  }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping; tex.repeat.set(10, 10);
  tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 4;
  return tex;
}
function netTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 64;
  const g = c.getContext('2d');
  g.strokeStyle = 'rgba(20,20,20,0.9)'; g.lineWidth = 1.4;
  for (let x = 0; x <= 256; x += 6) { g.beginPath(); g.moveTo(x, 0); g.lineTo(x, 64); g.stroke(); }
  for (let y = 0; y <= 64; y += 6) { g.beginPath(); g.moveTo(0, y); g.lineTo(256, y); g.stroke(); }
  const tex = new THREE.CanvasTexture(c);
  tex.wrapS = THREE.RepeatWrapping; tex.repeat.set(6, 1);
  return tex;
}
function radialTexture(inner = 'rgba(0,0,0,0.55)', outer = 'rgba(0,0,0,0)') {
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, inner); grd.addColorStop(1, outer);
  g.fillStyle = grd; g.fillRect(0, 0, 128, 128);
  return new THREE.CanvasTexture(c);
}
function labelSprite(main, sub, color) {
  const c = document.createElement('canvas'); c.width = 768; c.height = 384;
  const g = c.getContext('2d');
  g.textAlign = 'center'; g.textBaseline = 'alphabetic';
  if ('fontStretch' in g) g.fontStretch = 'condensed';
  g.shadowColor = 'rgba(0,0,0,0.7)'; g.shadowBlur = 22;
  g.fillStyle = color;
  let size = 150;
  g.font = `800 ${size}px Anybody, "Arial Narrow", sans-serif`;
  const wid = g.measureText(main).width;
  if (wid > 720) { size = Math.floor(size * 720 / wid); g.font = `800 ${size}px Anybody, "Arial Narrow", sans-serif`; }
  g.fillText(main, 384, 220);
  g.font = '600 60px Archivo, sans-serif'; g.fillStyle = 'rgba(238,242,234,0.92)';
  g.fillText(sub, 384, 310);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false, depthTest: false }));
  s.scale.set(2.6, 1.3, 1);
  s.renderOrder = 10;
  return s;
}

/** Rallies won before and after a rally, counted from outcomes (the same count as the match page). */
export function ralliesWon(match, rally) {
  const before = { T1: 0, T2: 0 };
  for (const r of match.analysis.rallies) {
    if (r === rally) break;
    if (r.outcome?.winner_team) before[r.outcome.winner_team]++;
  }
  const after = { ...before };
  if (rally.outcome?.winner_team) after[rally.outcome.winner_team]++;
  return { before, after };
}

function scoreboard() {
  const c = document.createElement('canvas'); c.width = 1040; c.height = 360;
  const g = c.getContext('2d');
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  let last = '';
  function draw(sc) {
    const key = `${sc.T1}:${sc.T2}`;
    if (key === last) return; last = key;
    g.fillStyle = '#0b1016'; g.fillRect(0, 0, 1040, 360);
    g.strokeStyle = '#2a3644'; g.lineWidth = 6; g.strokeRect(3, 3, 1034, 354);
    if ('fontStretch' in g) g.fontStretch = 'condensed';
    g.textAlign = 'center';
    g.font = '800 210px Anybody, sans-serif';
    g.fillStyle = '#f2b23e'; g.fillText(String(sc.T1), 300, 230);
    g.fillStyle = '#86c9f2'; g.fillText(String(sc.T2), 740, 230);
    g.fillStyle = '#ffe6b0'; g.fillRect(512, 110, 16, 16); g.fillRect(512, 180, 16, 16);
    if ('fontStretch' in g) g.fontStretch = 'normal';
    g.font = '600 44px Archivo, sans-serif'; g.fillStyle = 'rgba(238,242,234,0.7)';
    g.fillText('rallies won', 520, 320);
    tex.needsUpdate = true;
  }
  return { tex, draw };
}

function featherTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 64;
  const g = c.getContext('2d');
  g.fillStyle = 'rgba(255,255,255,0.78)'; g.fillRect(0, 0, 256, 64);
  g.fillStyle = 'rgba(255,255,255,1)';
  for (let i = 0; i < 16; i++) g.fillRect(i * 16 + 7, 0, 2, 64); // the quills
  g.fillStyle = 'rgba(0,0,0,0)';
  const grd = g.createLinearGradient(0, 0, 0, 64); // feathers thin out toward the rim
  grd.addColorStop(0, 'rgba(255,255,255,0)'); grd.addColorStop(1, 'rgba(255,255,255,0.35)');
  g.globalCompositeOperation = 'destination-out'; g.fillStyle = grd; g.fillRect(0, 0, 256, 64);
  return new THREE.CanvasTexture(c);
}

/* ---------- light cones ---------- */
function coneMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { color: { value: new THREE.Color(FLOOD) }, strength: { value: 0 } },
    vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ vUv=uv; vec4 mv=modelViewMatrix*vec4(position,1.0); vN=normalize(normalMatrix*normal); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 color; uniform float strength; varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ float edge=pow(abs(dot(vN,vV)),2.2); float a=strength*edge*(0.25+0.75*pow(vUv.y,1.2)); gl_FragColor=vec4(color*a,a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
}

/* ---------- athletes ---------- */
const smooth = (x) => x * x * (3 - 2 * x);
const lerp = (a, b, k) => a + (b - a) * k;
/** Arm poses: shoulder pitch and roll, elbow bend, wrist cock, trunk twist. */
const READY = { sx: -0.98, sz: -0.26, ex: -1.17, rx: -0.67, tw: 0 };
const SWINGS = {
  over: [ // smash, clear, drop: racket drops behind the head, then up and through
    [-0.5, READY], [-0.19, { sx: -1.99, sz: -1.08, ex: -2.05, rx: -0.81, tw: 0.68 }],
    [-0.085, { sx: -2.88, sz: -0.62, ex: -1.47, rx: -0.83, tw: 0.36 }],
    [0, { sx: -2.85, sz: -0.15, ex: -0.15, rx: -0.1, tw: -0.1 }], [0.2, { sx: -0.7, sz: 0.35, ex: -0.35, rx: 0.3, tw: -0.45 }], [0.65, READY]],
  side: [ // drive, push, block: a flat swing across the body
    [-0.4, READY], [-0.12, { sx: -1.45, sz: -1.3, ex: -1.3, rx: -0.6, tw: 0.45 }],
    [0, { sx: -1.55, sz: -0.25, ex: -0.25, rx: -0.2, tw: 0 }], [0.18, { sx: -1.35, sz: 0.55, ex: -0.7, rx: 0.1, tw: -0.4 }], [0.55, READY]],
  under: [ // lift, net, serve: from low behind to up in front
    [-0.4, READY], [-0.14, { sx: 0.35, sz: -0.5, ex: -0.5, rx: 0.5, tw: 0.3 }],
    [0, { sx: -0.9, sz: -0.25, ex: -0.25, rx: -0.4, tw: 0 }], [0.2, { sx: -2.0, sz: 0.1, ex: -0.9, rx: -0.6, tw: -0.25 }], [0.6, READY]],
};
// Short strokes should not borrow a full lift/drive backswing. Each meets
// the shuttle out front and recovers without throwing the arm past the chest.
const TOUCH = {
  serve_short: [[-0.32, READY], [-0.09, { sx:-0.67, sz:-0.24, ex:-0.83, rx:0.44, tw:0.04 }],
    [0, { sx:-0.73, sz:-0.22, ex:-0.64, rx:0.38, tw:0 }], [0.10, { sx:-0.78, sz:-0.20, ex:-0.61, rx:0.33, tw:-0.03 }], [0.32, READY]],
  block: [[-0.24, READY], [-0.075, { sx:-1.16, sz:-0.37, ex:-1.12, rx:-0.53, tw:0.07 }],
    [0, { sx:-1.38, sz:-0.32, ex:-0.63, rx:-0.35, tw:0 }], [0.11, { sx:-1.41, sz:-0.26, ex:-0.72, rx:-0.31, tw:-0.05 }], [0.30, READY]],
  net: [[-0.31, READY], [-0.09, { sx:-0.78, sz:-0.31, ex:-0.73, rx:-0.28, tw:0.10 }],
    [0, { sx:-1.03, sz:-0.27, ex:-0.39, rx:-0.30, tw:0 }], [0.11, { sx:-1.11, sz:-0.24, ex:-0.46, rx:-0.34, tw:-0.03 }], [0.31, READY]],
};
function swingKind(label) {
  if (['smash', 'clear', 'drop', 'net_kill'].includes(label)) return 'over';
  if (['drive', 'push', 'block', 'other', 'unknown'].includes(label)) return 'side';
  return 'under';
}
// Elbow stays in front; open the forearm into a short extension, then rebound.
const BACKHAND_DRIVE = [[-0.32, READY],
  [-0.10, { sx:-1.12, sz:0.16, ex:-1.03, rx:-0.34, tw:-0.16 }],
  [0, { sx:-1.43, sz:0.12, ex:-0.57, rx:-0.16, tw:0.04 }],
  [0.075, { sx:-1.51, sz:0.17, ex:-0.41, rx:-0.08, tw:0.12 }], [0.32, READY]];
const strokeKeys = (kind, label, backhand) => label === 'drive' && backhand ? BACKHAND_DRIVE : TOUCH[label] || SWINGS[kind];
function swingPose(kind, dt, label, backhand) {
  const keys = strokeKeys(kind, label, backhand);
  if (dt <= keys[0][0] || dt >= keys[keys.length - 1][0]) return null;
  for (let i = 0; i < keys.length - 1; i++) {
    const [t0, a] = keys[i], [t1, b] = keys[i + 1];
    if (dt >= t0 && dt <= t1) {
      // Accelerate into impact and carry speed through it instead of pausing there.
      const u = (dt - t0) / (t1 - t0);
      const k = t1 === 0 ? u * u : t0 === 0 ? 1 - (1 - u) ** 2 : smooth(u);
      // Lead with the turn and upper arm. Elbow opens next; the racket
      // releases last. All joints still reach their contact keys together.
      const hit = t1 === 0, trunk = hit ? u * (2 - u) : k;
      const shoulder = hit ? u : k, elbow = hit ? u ** 1.65 : k;
      const wrist = hit ? u ** 2.75 : k;
      return { sx: lerp(a.sx, b.sx, shoulder), sz: lerp(a.sz, b.sz, shoulder), ex: lerp(a.ex, b.ex, elbow), rx: lerp(a.rx, b.rx, wrist), tw: lerp(a.tw, b.tw, trunk) };
    }
  }
  return null;
}

function makeAthlete(color) {
  const flat = (c, extra = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.7, flatShading: true, ...extra });
  const kit = flat(color, { emissive: color, emissiveIntensity: 0.1, roughness: 0.55 });
  const skin = flat(0xc99a78);
  const dark = flat(0x18212b);
  const shoe = flat(0xf0f0ea);
  const grip = flat(0x2a2f36);
  const frame = new THREE.MeshStandardMaterial({ color: 0x2b3138, roughness: 0.3, metalness: 0.7 });
  const cyl = (rt, rb, h, m, seg = 7) => new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg), m);
  const at = (mesh, y, x = 0, z = 0) => { mesh.position.set(x, y, z); return mesh; };

  const root = new THREE.Group();
  const body = new THREE.Group(); root.add(body);
  const pelvis = new THREE.Group(); pelvis.position.y = 0.86; body.add(pelvis);
  pelvis.add(at(cyl(0.155, 0.17, 0.22, dark, 8), 0.0));
  const legs = [1, -1].map((s) => {
    const hip = new THREE.Group(); hip.position.set(0.095 * s, -0.04, 0); hip.rotation.z = 0.2 * s; pelvis.add(hip);
    hip.add(at(cyl(0.085, 0.075, 0.2, dark), -0.08));
    hip.add(at(cyl(0.07, 0.055, 0.44, skin), -0.22));
    const knee = new THREE.Group(); knee.position.y = -0.44; hip.add(knee);
    knee.add(at(cyl(0.055, 0.04, 0.42, skin), -0.21));
    const foot = new THREE.Group(); foot.position.y = -0.42; knee.add(foot);
    foot.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.1, 0.07, 0.27), shoe), -0.02, 0, 0.05));
    return { hip, knee, foot, s };
  });
  const spine = new THREE.Group(); spine.position.y = 0.08; pelvis.add(spine);
  const torso = at(cyl(0.2, 0.15, 0.5, kit, 8), 0.25); torso.scale.z = 0.72; spine.add(torso);
  spine.add(at(cyl(0.05, 0.055, 0.1, skin), 0.54));
  const neck = new THREE.Group(); neck.position.y = 0.55; spine.add(neck);
  neck.add(at(new THREE.Mesh(new THREE.IcosahedronGeometry(0.105, 1), skin), 0.11));
  const hair = at(new THREE.Mesh(new THREE.SphereGeometry(0.11, 10, 6, 0, Math.PI * 2, 0, Math.PI * 0.5), dark), 0.125); hair.rotation.x = -0.25; neck.add(hair);
  neck.add(at(new THREE.Mesh(new THREE.IcosahedronGeometry(0.025, 0), skin), 0.103, 0, 0.093));
  // Asymmetric kit markings make shoulder and back turns readable at hero scale.
  spine.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.065, 0.026, 0.014), shoe), 0.39, 0.087, 0.113));
  spine.add(at(new THREE.Mesh(new THREE.BoxGeometry(0.19, 0.036, 0.014), shoe), 0.40, 0, -0.128));
  const arm = (side, racket) => {
    const shoulder = new THREE.Group(); shoulder.position.set(0.215 * side, 0.46, 0); spine.add(shoulder);
    shoulder.add(at(cyl(0.065, 0.058, 0.13, kit), -0.05));
    shoulder.add(at(cyl(0.048, 0.042, 0.29, skin), -0.15));
    const elbow = new THREE.Group(); elbow.position.y = -0.29; shoulder.add(elbow);
    elbow.add(at(cyl(0.04, 0.033, 0.26, skin), -0.13));
    elbow.add(at(new THREE.Mesh(new THREE.IcosahedronGeometry(0.04, 0), skin), -0.28));
    let wrist = null;
    if (racket) {
      wrist = new THREE.Group(); wrist.position.y = -0.28; elbow.add(wrist);
      // Grip sits diagonally through the palm, with a visible butt cap below it.
      wrist.add(at(cyl(0.015, 0.018, 0.19, grip, 8), -0.035));
      wrist.add(at(cyl(0.022, 0.018, 0.018, shoe, 8), 0.059));
      const palm = at(new THREE.Mesh(new THREE.IcosahedronGeometry(0.043, 1), skin), -0.014);
      palm.scale.set(0.81, 1.18, 0.78); palm.rotation.z = 0.28; wrist.add(palm);
      wrist.add(at(cyl(0.006, 0.006, 0.24, frame, 5), -0.28));
      const hoop = at(new THREE.Mesh(new THREE.TorusGeometry(0.105, 0.009, 5, 22), frame), -0.53); hoop.scale.y = 1.28; wrist.add(hoop);
      const bed = at(new THREE.Mesh(new THREE.CircleGeometry(0.1, 18), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.16, side: THREE.DoubleSide, depthWrite: false })), -0.53);
      bed.scale.y = 1.28; wrist.add(bed);
    }
    return { shoulder, elbow, wrist };
  };
  const rArm = arm(-1, true); // racket in the right hand (handedness is unknown in the data)
  const lArm = arm(1, false);
  lArm.shoulder.rotation.set(-0.7, 0, 0.35); lArm.elbow.rotation.x = -1.1;
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.4, 0.47, 40),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.32, depthWrite: false, blending: THREE.AdditiveBlending }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = 0.012; root.add(ring);
  return { root, pelvis, spine, neck, legs, rArm, lArm, ring, pos: root.position, flash: 0 };
}

const clamp = THREE.MathUtils.clamp;
const pulse = (delta, before, after) => smooth(clamp(1 - Math.abs(delta) / (delta < 0 ? before : after), 0, 1));

// Display-only replay curves. Sampling either curve is a pure function of
// match time: seeking, still frames, foot plants and racket contact agree.
function curveIndex(t, start, hz, last) {
  const f = clamp((t - start) * hz, 0, last);
  const i = Math.min(Math.floor(f), last - 1);
  return [i, f - i];
}
function presentationTrack(match, id, start, end, fallback) {
  const hz = match.analysis.tracks.rate_hz, tr = match.trackIndex.get(id);
  const first = Math.floor(start * hz), last = Math.max(first + 1, Math.ceil(end * hz));
  const points = []; let prev;
  for (let k = first; k <= last; k++) {
    if (!Number.isFinite(tr?.x[k]) || !Number.isFinite(tr?.y[k])) continue;
    const point = toScene({ x: tr.x[k], y: tr.y[k] });
    // Bridge actual neighbours. Never visit the start-of-rally fallback
    // in the middle of an occlusion just because a sample is missing.
    for (let j = points.length; j <= k - first; j++) points.push(prev
      ? prev.point.clone().lerp(point, (j + first - prev.k) / (k - prev.k)) : point.clone());
    prev = { point, k };
  }
  while (points.length <= last - first) points.push(prev ? prev.point.clone() : toScene(fallback));
  // Limit implausible reacquisitions in both directions, without making
  // the whole replay trail the recorded movement by a filter delay.
  const pass = (dir) => {
    const out = points.map(p => p.clone());
    for (let i = dir > 0 ? 1 : out.length - 2; i >= 0 && i < out.length; i += dir) {
      const anchor = out[i-dir]; out[i].sub(anchor).clampLength(0, 7 / hz).add(anchor);
    }
    return out;
  };
  const forward = pass(1), backward = pass(-1);
  const path = forward.map((p,i) => p.lerp(backward[i], 0.5));
  return t => {
    const [i,u] = curveIndex(t, first / hz, hz, path.length - 1);
    // Quadratic B-spline: velocity stays continuous at track sample boundaries.
    const center = u < 0.5 ? i : i + 1, v = u < 0.5 ? u + 0.5 : u - 0.5;
    return path[center].clone().multiplyScalar(0.5 + v - v*v)
      .addScaledVector(path[Math.max(0, center-1)], 0.5*(1-v)**2)
      .addScaledVector(path[Math.min(path.length-1, center+1)], 0.5*v*v);
  };
}
function presentationFacing(a, start, end) {
  const hz = 60, n = Math.max(2, Math.ceil((end-start)*hz)+1);
  const raw = Array.from({ length:n }, (_,i) => { const t=start+i/hz; return turning(a,t,a.track(t)).hip; });
  // Short symmetric window damps jitter while preserving the shoulder-led
  // swing. Cap pivot rate independently of render frame rate.
  const yaw = raw.map((_,i) => {
    let sum=0; for(let j=-4;j<=4;j++) sum += (5-Math.abs(j))*raw[clamp(i+j,0,n-1)];
    return sum/25;
  });
  for(let i=1;i<n;i++) yaw[i]=clamp(yaw[i],yaw[i-1]-7/hz,yaw[i-1]+7/hz);
  return t => { const [i,u]=curveIndex(t,start,hz,n-1); return lerp(yaw[i],yaw[i+1],u); };
}

// All turns are offsets from the player's net-facing axis. This avoids a
// discontinuity at +/-pi for the near team and keeps a retreat from looking
// like a sprint with the player's back to the rally.
function turning(a, t, base) {
  let contact, dt = Infinity;
  for (const c of a.contacts) if (Math.abs(t - c.t) < Math.abs(dt)) { contact = c; dt = t - c.t; }
  if (contact && dt !== 0) dt *= dt < 0 ? contact.before : contact.after;
  const kind = contact?.kind, label = contact?.label, sign = contact?.backhand ? -1 : 1;
  // Ease attention between opposing contact locations, not the outgoing
  // shuttle at the racket (which would make the player spin at impact).
  let gaze = 0;
  if (a.targets.length) {
    let j = a.targets.findIndex(c => c.t >= t);
    if (j < 0) j = a.targets.length - 1;
    const b = a.targets[j], prev = a.targets[Math.max(0, j - 1)];
    const k = smooth(clamp((t - prev.t) / Math.max(b.t - prev.t, 0.01), 0, 1));
    gaze = clamp(Math.atan2((lerp(prev.x, b.x, k) - base.x) * a.forward,
      Math.max(1.5, (lerp(prev.z, b.z, k) - base.z) * a.forward)), -0.78, 0.78);
  }
  const prev = a.track(t - 0.11), next = a.track(t + 0.11);
  const vx = (next.x - prev.x) * a.forward / 0.22, vz = (next.z - prev.z) * a.forward / 0.22;
  const speed = Math.hypot(vx, vz), travel = clamp(vx / 3.4, -1, 1);
  const lateral = smooth(clamp((Math.abs(vx) / Math.max(speed, 0.01) - 0.48) / 0.38, 0, 1));
  // Net-relative depth matters: a fast retreat is NOT a forward run. Open
  // the racket hip to place the racket foot down the direction of retreat.
  const rearSpeed = Math.max(0, -vz);
  const retreat = smooth(clamp((rearSpeed - 0.12) / 0.63, 0, 1))
    * smooth(clamp((rearSpeed / Math.max(speed, 0.01) - 0.20) / 0.40, 0, 1));
  const run = (1 - retreat) * smooth(clamp((speed - 0.86) / 1.65, 0, 1)) * (1 - lateral * 0.88);
  const chase = clamp(Math.atan2(vx, Math.max(0.55, Math.abs(vz))), -1.05, 1.05) * run;
  const power = TOUCH[label] ? 0.12 : kind === 'over' ? 1 : label === 'drive' ? 0.64 : kind === 'under' ? 0.46 : 0.35;
  const wind = pulse(dt + 0.19, 0.29, 0.18), release = pulse(dt - 0.065, 0.13, 0.32);
  // Only the receiver prepares during the incoming high flight. Hold the
  // side-on stance through a pause in the track, then unwind into the hit.
  const lob = a.lobs?.find(f => t >= f.start && t <= f.end);
  const set = lob ? smooth(clamp((t - lob.start) / 0.25, 0, 1)) * smooth(clamp((lob.end - t) / 0.18, 0, 1)) : 0;
  const sideOn = Math.max(retreat, set * 0.93);
  const readyHip = gaze * (0.67 - run * 0.36) + travel * 0.34 + chase;
  const quarterTurn = clamp(Math.atan2(-Math.max(0.55, rearSpeed), -vx), -2.18, -0.90);
  const hip = a.facingAt?.(t) ?? lerp(readyHip, quarterTurn, sideOn) + sign * power * (-0.94 * wind * (1 - sideOn) + 0.59 * release);

  return { contact, dt, kind, label, gaze, travel, hip, sign, power, speed, lateral, run, vx, vz, retreat, set, untilLob: lob ? lob.end - t : Infinity };
}

// Bake alternating, non-overlapping steps from the actual court travel. At a
// fresh lateral push the outside foot opens first; under sustained travel the
// other shoe gathers. Idle players do not march against an invisible treadmill.
function planSteps(a, start, end) {
  const target = (t, side) => {
    const p = a.track(t), m = turning(a, t, p), yaw = a.heading + m.hip;
    const still = 1 - smooth(clamp(m.speed / 1.15, 0, 1));
    const role = a.roleAt?.(t) || 0;
    const w = side * (0.23 + (0.06 - 0.058 * role) * still + m.lateral * 0.035 - m.run * 0.115), z = -side * (0.055 + (0.065 + 0.048 * role) * still);
    return { x: p.x + w * Math.cos(yaw) + z * Math.sin(yaw), z: p.z - w * Math.sin(yaw) + z * Math.cos(yaw), yaw };
  };
  const states = a.legs.map(leg => {
    const foot = target(start, leg.s); leg.steps = [{ start, end: start, from: foot, to: foot, height: 0, run: 0 }];
    return foot;
  });
  a.bounds = [];
  let last = -1, free = start, wasRetreat = false;
  for (let t = start; t < end; t += 1 / 60) {
    if (t < free) continue;
    const m = turning(a, t, a.track(t));
    const opening = last < 0 || t-free > 0.12;
    const intercept = opening && m.vz >= 0 ? Math.max(0, a.roleAt?.(t) || 0) : 0;
    const duration = clamp(0.23 - 0.022 * m.speed - 0.052 * intercept, 0.115, 0.23);
    const goals = a.legs.map(leg => target(t + duration * 1.25, leg.s));
    // After a scissor landing, gather the trailing shoe toward play on the
    // next step instead of returning both feet to the old ready stance.
    if (m.contact?.elevation) {
      const afterLanding = t - m.contact.t - 0.46 * Math.sqrt(8*m.contact.elevation/9.81);
      if (afterLanding >= 0 && afterLanding < 0.30) {
        goals[a.legs.findIndex(l => l.s === 1)].z += a.forward * 0.19 * pulse(afterLanding-0.10, 0.10, 0.20);
      }
    }
    const gaps = goals.map((g, i) => Math.hypot(g.x - states[i].x, g.z - states[i].z) + 0.09 * Math.abs(g.yaw - states[i].yaw));
    let i = last < 0 || t - free > 0.12 ? (gaps[1] > gaps[0] ? 1 : 0) : 1 - last;
    let openingSide = 0;
    // A wider set stance can make the trailing foot farther from its
    // target before velocity rises. Pick the first shoe by intended travel.
    if (last < 0 || t - free > 0.12) {
      const advance = a.track(t + duration * 1.25).sub(a.track(t));
      if (Math.abs(advance.x) > Math.max(0.008, 1.3 * Math.abs(advance.z))) {
        openingSide = Math.sign(advance.x * a.forward);
        i = a.legs.findIndex(l => l.s === openingSide);
      }
    }
    const rear = m.retreat > 0.50;
    if (rear) {
      // Chasse: racket foot opens, other foot closes without overtaking it.
      // A new retreat always opens with the racket foot, even after a run.
      const lead = a.legs.findIndex(leg => leg.s === -1);
      i = !wasRetreat || last !== lead ? lead : 1 - lead;
      const axisX = m.vx * a.forward / m.speed, axisZ = m.vz * a.forward / m.speed;
      const other = states[1-i], goal = goals[i];
      const gap = (goal.x - other.x) * axisX + (goal.z - other.z) * axisZ;
      const correction = i === lead ? Math.max(0, 0.32 - gap) : Math.min(0, -0.18 - gap);
      goal.x += correction * axisX; goal.z += correction * axisZ;
      if (Math.hypot(goal.x - states[i].x, goal.z - states[i].z) < 0.065) continue;
    } else if (gaps[i] < 0.105) { if (openingSide || gaps[1-i] < 0.19) continue; i = 1-i; }
    const height = Math.min(0.085 + 0.13 * m.run, gaps[i] * (0.24 + 0.16 * m.run));
    a.legs[i].steps.push({ start: t, end: t + duration, from: states[i], to: goals[i], height, run: m.run });
    // One low bound per open/gather pair, not a bounce on every footfall.
    // Trigger from the planned lead-foot step so flight follows the feet,
    // including diagonals and both ends of the court.
    const leadSide = rear ? -1 : Math.sign(m.vx);
    if (a.legs[i].s === leadSide && (rear || m.lateral > 0.60) && m.speed > 0.75) {
      const airTime = clamp(0.17 + 0.035 * m.speed, 0.19, 0.285);
      const off = t + duration * 0.32;
      const prev = a.bounds[a.bounds.length - 1];
      if (!prev || off > prev.off + prev.duration + 0.095)
        a.bounds.push({ off, duration: airTime, peak: 1.226 * airTime ** 2, side: leadSide });
    }
    states[i] = goals[i]; wasRetreat = rear; last = i; free = t + duration;
  }
}

function strideAt(steps, t) {
  let lo = 0, hi = steps.length;
  while (lo + 1 < hi) { const mid = (lo + hi) >> 1; if (steps[mid].start <= t) lo = mid; else hi = mid; }
  const step = steps[lo], u = clamp((t - step.start) / Math.max(0.001, step.end - step.start), 0, 1);
  const k = smooth(u), arc = Math.sin(Math.PI * u);
  return { x: lerp(step.from.x, step.to.x, k), z: lerp(step.from.z, step.to.z, k),
    yaw: lerp(step.from.yaw, step.to.yaw, k), lift: step.height * arc, drive: step.run * arc,
    pitch: step.run * arc * (0.55 - u * 0.85) };
}

// Ballistic flight has a distinct push-off and touchdown. Compression on
// either side bends the legs against the floor; it does not sink the shoes.
function flightArc(u) { return u <= 0 || u >= 1 ? 0 : 4 * u * (1 - u); }
function shuffleMotion(a, t) {
  const bounds = a.bounds;
  let lo = 0, hi = bounds.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (bounds[mid].off <= t + 0.09) lo = mid + 1; else hi = mid; }
  const b = bounds[lo - 1];
  if (!b) return { air: 0, bend: 0, bank: 0 };
  const d = t - b.off, arc = flightArc(d / b.duration);
  const gather = pulse(d + 0.045, 0.045, 0.045), land = pulse(d - b.duration - 0.045, 0.045, 0.075);
  return { air: b.peak * arc, bend: 0.065 * gather + 0.075 * land, bank: b.side * (gather - land) };
}

function poseAthlete(a, t) {
  const base = a.track(t);
  const { contact, dt, kind, label, gaze, travel, hip, sign, power, lateral, run, vz, speed, retreat, set, untilLob } = turning(a, t, base);
  const heading = a.heading + hip;
  a.root.position.copy(base); a.root.rotation.y = heading;
  for (const c of a.contacts) if (c.netOffset) a.root.position.z += c.netOffset * pulse((t-c.t)*(t<c.t?c.before:c.after),0.48,0.54);
  let receive = 0, hop = 0;
  for (const hit of a.opponents) {
    receive = Math.max(receive, pulse(t - hit - 0.045, 0.08, 0.15));
    hop = Math.max(hop, pulse(t - hit + 0.075, 0.09, 0.085));
  }
  const load = pulse(dt, 0.32, 0.30), prep = pulse(dt + 0.17, 0.27, 0.17);
  // Keep a front-court lunge grounded as pressure moves over the planted shoe.
  const plant = contact?.plant ? pulse(dt - 0.02, 0.24, 0.28) : 0;
  const low = kind === 'under' && !label.startsWith('serve') ? load : 0;
  const high = kind === 'over' ? load : 0;
  const split = receive * (1 - load);
  // Scissor change on a rear-court attacking overhead. Drive and net
  // exchanges stay grounded; the trailing foot passes during flight only.
  // Decide at the contact, not at the current position: crossing a depth
  // threshold during the approach must not switch a jump on or off midair.
  const strike = a.contacts.find(c => c.label === 'smash' && Math.abs(t - c.t) < 0.65);
  const powerJump = strike?.elevation || 0;
  const age = strike ? t - strike.t : Infinity;
  const airTime = Math.sqrt(8 * powerJump / 9.81);
  const off = -0.54 * airTime, downAt = off + airTime;
  const jump = powerJump ? flightArc((age - off) / airTime) : 0;
  const crouch = powerJump ? pulse(age - off + 0.09, 0.12, 0.09) : 0;
  const landing = powerJump ? pulse(age - downAt - 0.07, 0.07, 0.15) : 0;
  const bound = shuffleMotion(a, t);
  const groundGame = 1 - Math.max(crouch, jump, landing);
  const airborne = Math.max(bound.air, 0.055 * hop * (1 - load)) * groundGame * (1 - plant) + powerJump * jump;
  a.airHeight = airborne;
  const feet = a.legs.map(leg => strideAt(leg.steps, t));
  const armDrive = (feet[0].drive - feet[1].drive) * (1 - load);
  const gather = Math.max(retreat, lateral * Math.abs(travel));
  // In base position, stay low over a broad, staggered pair of planted
  // shoes. Shift pressure toward play, not the shoes themselves.
  const ready = (1 - smooth(clamp(speed / 1.15, 0, 1))) * (1 - Math.max(load, prep, jump, landing));
  const role = a.roleAt?.(t) || 0;
  const front = Math.max(0, role), rear = Math.max(0, -role);
  const driveSet = label === 'drive' ? pulse(dt - 0.025, 0.24, 0.27) : 0;
  const pressure = ready * (0.026 * Math.sin(gaze) + 0.014 * Math.sin(3.2*t + (a.idlePhase || 0)));
  a.pelvis.position.set(-0.045 * low + pressure, 0.78 - 0.07 * driveSet - (0.073 + 0.032 * rear) * ready - 0.12 * low + 0.055 * high - 0.035 * split
    - 0.14 * crouch - 0.15 * landing - bound.bend * groundGame - 0.045 * gather + 0.035 * Math.abs(armDrive) + airborne, 0.09 * low + 0.08 * plant + 0.065 * landing + (0.045 + 0.040 * front) * ready);

  for (const [index, leg] of a.legs.entries()) {
    const foot = feet[index];
    const lock = leg.s === -1 ? smooth(clamp(plant * 1.45, 0, 1)) : 0;
    if (lock) {
      foot.x = lerp(foot.x, contact.plant.x, lock); foot.z = lerp(foot.z, contact.plant.z, lock);
      foot.lift *= 1 - lock; foot.pitch *= 1 - lock;
    }
    const dx = foot.x - a.root.position.x, dz = foot.z - a.root.position.z;
    const toe = foot.yaw - heading;
    const extraReach = -leg.s * (low * 0.27 * (1 - plant) + jump * clamp(age * 2.5, -0.26, 0.26));
    const x = clamp(dx * Math.cos(heading) - dz * Math.sin(heading), -0.53, 0.53) - leg.hip.position.x;
    const z = clamp(dx * Math.sin(heading) + dz * Math.cos(heading), -0.46, 0.46) + extraReach - a.pelvis.position.z;
    // In a smash the trailing heel folds higher. Extend to meet the
    // floor on descent instead of holding a squat throughout the flight.
    const tuck = jump * (leg.s > 0 ? 0.17 : 0.095) * (1 - smooth(clamp(age / 0.22, 0, 1)));
    const lift = foot.lift * (1 - jump) + tuck + 0.13 * Math.abs(Math.sin(foot.pitch));
    const down = a.pelvis.position.y - 0.04 - 0.055 - lift - airborne;
    const vertical = Math.hypot(down, x - a.pelvis.position.x);
    const length = Math.min(0.859, Math.hypot(vertical, z));
    const knee = Math.acos(clamp((length ** 2 - 0.44 ** 2 - 0.42 ** 2) / (2 * 0.44 * 0.42), -1, 1));
    leg.hip.rotation.order = 'ZXY';
    leg.hip.rotation.z = Math.atan2(x - a.pelvis.position.x, down);
    leg.hip.rotation.x = -Math.atan2(z, vertical) - Math.atan2(0.42 * Math.sin(knee), 0.44 + 0.42 * Math.cos(knee));
    leg.knee.rotation.x = knee;
    leg.foot.quaternion.copy(leg.hip.quaternion).multiply(leg.knee.quaternion).invert();
    leg.foot.rotateY(toe); leg.foot.rotateX(foot.pitch);
  }
  // Overheads share a preparation; the drop checks its follow-through,
  // whereas the smash turns the shoulders and finishes across the body.
  const swingTime = label === 'drop' && dt > 0 ? dt * 1.45 : dt;
  const pose = (kind && swingPose(kind, swingTime, label, contact.backhand)) || READY;
  if (label === 'drop' && pose !== READY && dt > 0) {
    // Check the follow-through, not the preparation. Fade the check away
    // before recovery so the shoulder still blends all the way to ready.
    const check = pulse(swingTime - 0.20, 0.20, 0.42);
    pose.sx -= 0.74 * check; pose.tw += 0.20 * check;
  }
  const finish = label === 'smash' ? pulse(dt - 0.14, 0.14, 0.30) : 0;
  // A block or net touch has almost no backswing; keep the racket out front.
  const compact = ['block', 'push', 'net', 'serve_short'].includes(label);
  const reach = compact ? pulse(dt, 0.3, 0.36) : 0;
  const r = a.rArm;
  r.shoulder.rotation.set(lerp(pose.sx, kind === 'under' ? -0.88 : -1.45, reach * 0.7), 0, pose.sz + 0.38 * finish);
  // The same racket hand reaches across the chest for a backhand. Roll the
  // forearm through impact rather than rotating the entire arm as one lever.
  const across = sign < 0 ? load : 0;
  r.shoulder.rotation.x += 0.30 * armDrive;
  r.shoulder.rotation.y = 0.94 * across + sign * power * (-0.22 * prep + 0.25 * finish);
  // Directional finish begins after contact: it cannot displace the sweet spot.
  r.shoulder.rotation.y += (contact?.azimuth || 0) * 0.65 * pulse(dt - 0.12, 0.12, 0.23);
  r.elbow.rotation.set(pose.ex, sign * power * (-0.35 * prep + 0.40 * load), 0);
  r.wrist.rotation.set(pose.rx, sign * power * (-0.48 * prep + 0.60 * load), across * 0.24);
  // Show the receiving shape early rather than carrying the racket down
  // until the swing starts: elbow away from ribs, head up by the shoulder,
  // free arm sighting the flight. Hand the arm back to the keyed swing.
  // Footwork is shared; overhead preparation is not. Start the set late
  // in the assigned receiver's incoming flight, not on every backward step.
  const guard = set * smooth(clamp((1.05 - untilLob) / 0.40, 0, 1)) * (1 - Math.max(load, prep));
  r.shoulder.rotation.x = lerp(r.shoulder.rotation.x, -1.85, guard);
  r.shoulder.rotation.z = lerp(r.shoulder.rotation.z, -1.04, guard);
  r.elbow.rotation.x = lerp(r.elbow.rotation.x, -1.27, guard);
  r.wrist.rotation.x = lerp(r.wrist.rotation.x, -0.30, guard);
  r.wrist.rotation.y += 0.35 * guard;
  // A covering player carries the hand forward around waist height. Do
  // not blend this over a receiver's setup or the hitter's follow-through.
  const keys = strokeKeys(kind, label, contact?.backhand);
  const engaged = keys ? smooth(clamp((dt - keys[0][0] + 0.12) / 0.12, 0, 1))
    * smooth(clamp((keys[keys.length - 1][0] + 0.12 - dt) / 0.12, 0, 1)) : 0;
  const carry = Math.max(0.50, retreat, run, lateral * Math.abs(travel)) * (1 - Math.max(engaged, guard));
  r.shoulder.rotation.x = lerp(r.shoulder.rotation.x, -0.61 + 0.15 * armDrive, carry);
  r.shoulder.rotation.z = lerp(r.shoulder.rotation.z, -0.24, carry);
  r.elbow.rotation.x = lerp(r.elbow.rotation.x, -1.01, carry);
  r.wrist.rotation.x = lerp(r.wrist.rotation.x, -0.48, carry);
  // The net player presents the strings in front of the chest, not above
  // the head. Retreating, preparing or following through takes precedence.
  const intercept = front * smooth(clamp((vz + 0.26) / 0.26, 0, 1)) * (1 - retreat) * (1 - run) * (1 - Math.max(engaged, guard));
  r.shoulder.rotation.x = lerp(r.shoulder.rotation.x, -1.28, intercept);
  r.elbow.rotation.x = lerp(r.elbow.rotation.x, -1.08, intercept);
  r.wrist.rotation.x = lerp(r.wrist.rotation.x, -0.44, intercept);
  a.spine.rotation.set(0.14 + 0.17 * finish + (0.16 + 0.065 * front) * ready + 0.22 * crouch + 0.19 * landing + low * 0.29 - high * 0.15 + run * clamp(vz * 0.075, -0.09, 0.24) * (1-load), 0.12 * armDrive - sign * pose.tw + sign * 0.26 * finish, high * 0.10 - 0.11 * travel + 0.075 * bound.bank * groundGame);
  a.lArm.shoulder.rotation.set(-0.72 - 0.62 * armDrive - (kind === 'over' ? prep * 1.55 : 0) + low * 0.85, 0, 0.40 + low * 0.85 + high * 0.28);
  a.lArm.shoulder.rotation.x -= 0.86 * guard + 0.16 * ready;
  a.lArm.shoulder.rotation.z += 0.16 * ready;
  a.neck.rotation.order = 'YXZ';
  a.neck.rotation.set(-0.65 * a.spine.rotation.x - 0.24 * high - 0.24 * guard, clamp(gaze - hip - a.spine.rotation.y, -1.05, 1.05), -0.6 * a.spine.rotation.z);
  a.lArm.elbow.rotation.x = -1.04 + low * 0.78 - 0.48 * finish;
  // A fixed correction in chest space steers the whole swing arc. Do not
  // chase a stationary point each frame: that stalls the strings at impact.
  if (contact?.aim) {
    const weight = pulse(dt, 0.22, 0.24);
    if (weight) {
      r.shoulder.quaternion.premultiply(a.steering.identity().slerp(contact.aim, weight));
      // Turn about the shaft: this presents the strings without moving the sweet spot.
      r.wrist.rotateY((contact.faceRoll || 0) * weight);
    }
  }
}

// A staging cue, not a tactical label: relative depth within a known pair.
// Bake one complementary curve per team. Level partners, missing observations
// and singles use the neutral stance. Blending in time avoids pose flips.
function doublesFormation(match, start, end) {
  const roles = new Map(), teams = new Map();
  for (const { id, team } of match.analysis.players) {
    if (!team) continue;
    if (!teams.has(team)) teams.set(team, []);
    teams.get(team).push(id);
  }
  const hz = match.analysis.tracks.rate_hz, first = Math.floor(start*hz);
  const count = Math.max(2, Math.ceil(end*hz) - first + 1);
  for (const pair of teams.values()) {
    if (pair.length !== 2) continue;
    const [a,b] = pair.map(id => match.trackIndex.get(id));
    if (!a || !b) continue;
    const values = Array.from({length: count}, (_,i) => {
      const ya = a.y[first+i], yb = b.y[first+i];
      if (!Number.isFinite(ya) || !Number.isFinite(yb)) return 0;
      const za = ya - COURT_L/2, zb = yb - COURT_L/2;
      if (za*zb <= 0) return 0;
      const gap = Math.abs(zb) - Math.abs(za);
      return Math.sign(gap) * smooth(clamp((Math.abs(gap)-0.50)/1.35, 0, 1));
    });
    const radius = Math.max(1, Math.round(hz*0.30));
    const blend = values.map((_,i) => {
      let sum=0; for(let j=-radius;j<=radius;j++) sum+=(radius+1-Math.abs(j))*values[clamp(i+j,0,count-1)];
      return sum/(radius+1)**2;
    });
    for (const [k,id] of pair.entries()) roles.set(id,t => {
      const [i,u]=curveIndex(t,first/hz,hz,count-1);
      return (k ? -1 : 1) * lerp(blend[i],blend[i+1],u);
    });
  }
  return roles;
}

function prepareAthlete(a, id, flights, match, rally, formation = doublesFormation(match, rally.start_s, flights[flights.length-1].t1)) {
  a.roleAt = formation.get(id);
  // each athlete's own contacts, so the swing starts before the shuttle arrives
  a.contacts = flights.flatMap((f, i) => f.shot.hitter_id === id ? [{ t: f.t0, incoming: flights[i - 1]?.t0 ?? -Infinity,
    flight: f, kind: swingKind(f.label), label: f.label, backhand: f.shot.side === 'backhand' }] : []);
  a.lobs = flights.slice(1).flatMap((f, i) => f.shot.hitter_id === id && HIGH.has(flights[i].label) && swingKind(f.label) === 'over'
    ? [{ start: flights[i].t0, end: f.t0 }] : []);
  a.opponents = flights.filter(f => f.shot.hitter_id && teamOf(match, f.shot.hitter_id) !== teamOf(match, id)).map(f => f.t0);
  const own = flights.find(f => f.shot.hitter_id === id);
  const fallback = positionAt(match, id, rally.start_s) || own?.shot.hitter_position || { x: COURT_W / 2, y: COURT_L / 2 };
  // Snapshot positions before racket alignment replaces the flight endpoints.
  a.targets = flights.filter(f => f.shot.hitter_id && teamOf(match, f.shot.hitter_id) !== teamOf(match, id))
    .map(f => ({ t: f.t0, x: f.from.x, z: f.from.z }));
  a.heading = fallback.y < COURT_L / 2 ? 0 : Math.PI;
  a.forward = Math.cos(a.heading);
  a.idlePhase = match.analysis.players.findIndex(p => p.id === id) * 2.4;
  a.track = presentationTrack(match, id, rally.start_s, flights[flights.length - 1].t1, fallback);
  // Fit preparation and recovery between consecutive strokes. Both motions
  // reach ready at their midpoint, even during rapid drive exchanges.
  for (const [i, c] of a.contacts.entries()) {
    // Animation staging, not an inferred jump label: full rear-court
    // smash, compact midcourt hop, or grounded quick interception.
    if (c.label === 'smash') {
      const depth = Math.abs(a.track(c.t).z);
      const room = Math.min(c.t - (a.contacts[i-1]?.t ?? -Infinity), (a.contacts[i+1]?.t ?? Infinity) - c.t);
      c.elevation = depth > 1.8 && room > 0.7 ? lerp(0.20, 0.46, smooth(clamp((depth - 1.8) / 2.3, 0, 1))) : 0;
    }
    const keys = strokeKeys(c.kind, c.label, c.backhand);
    c.before = Math.max(1, -keys[0][0] / Math.max(0.01, c.t - c.incoming), -2 * keys[0][0] / (c.t - (a.contacts[i - 1]?.t ?? -Infinity)));
    c.after = Math.max(1, 2 * keys[keys.length - 1][0] / ((a.contacts[i + 1]?.t ?? Infinity) - c.t));
  }
  a.facingAt = presentationFacing(a, rally.start_s - 0.6, flights[flights.length - 1].t1 + 0.5);
  planSteps(a, rally.start_s - 0.6, flights[flights.length - 1].t1 + 0.5);
  // Some fitted poses reach through the tape. Make room on the hitter's
  // side before sampling contacts rather than detaching the bird from the bed.
  const bed = new THREE.Vector3();
  a.steering = new THREE.Quaternion();
  for (const c of a.contacts) {
    const at = a.track(c.t);
    if ((c.label === 'net' || c.label === 'lift') && Math.abs(at.z) < 2.6) {
      const yaw = a.heading + a.facingAt(c.t);
      c.plant = { x: at.x - 0.19*Math.cos(yaw) + 0.38*Math.sin(yaw),
        z: at.z + 0.19*Math.sin(yaw) + 0.38*Math.cos(yaw) };
    }
    poseAthlete(a, c.t);
    // Stage a reachable contact relative to the player, not a global +X
    // offset. Both court ends use the same forehand/backhand convention.
    const over = c.kind === 'over', touch = !!TOUCH[c.label];
    const sideReach = c.backhand ? 0.29 : over ? -0.32 : -0.42;
    const frontReach = over ? (c.label === 'smash' ? 0.49 : 0.35) : touch ? 0.70 : 0.79;
    const target = a.root.position.clone();
    target.x += sideReach * a.forward; target.z += frontReach * a.forward;
    target.y = (CONTACT_H[c.label] ?? 1.2) + a.airHeight;
    const shoulder = a.rArm.shoulder.position;
    const from = a.spine.worldToLocal(a.rArm.wrist.localToWorld(bed.set(0,-0.53,0))).sub(shoulder).normalize();
    const to = a.spine.worldToLocal(target).sub(shoulder).normalize();
    c.aim = new THREE.Quaternion().setFromUnitVectors(from, to);
    poseAthlete(a,c.t);
    a.rArm.wrist.localToWorld(bed.set(0,-0.53,0));
    const side = -a.forward;
    c.netOffset = side * Math.max(0, 0.44-side*bed.z);
  }
}

// Flight geometry is final here. Turning around the shaft leaves both endpoints intact.
function aimOutgoing(a, c) {
  const f = c.flight;
  const v = flightPoint(f, Math.min(f.t1, f.t0 + 0.008), new THREE.Vector3()).sub(f.from);
  if (v.lengthSq() < 1e-12) return;
  c.azimuth = clamp(Math.atan2(a.forward * v.x, Math.max(0.001, a.forward * v.z)), -1.15, 1.15);
  c.faceRoll = 0;
  poseAthlete(a, c.t);
  v.applyQuaternion(a.rArm.wrist.getWorldQuaternion(a.steering).invert());
  const roll = Math.atan2(v.x, v.z);
  c.faceRoll = roll - Math.round(roll / Math.PI) * Math.PI;
}

export function createHero(container, match, { still = false, phone = false, onShot } = {}) {
  const rally = pickRally(match);
  const flights = buildFlights(match, rally);
  const ids = match.analysis.players.map((p) => p.id);
  const won = ralliesWon(match, rally);

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, phone ? 1.5 : 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.setAttribute('aria-hidden', 'true');
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x131c25);
  scene.fog = new THREE.FogExp2(0x131c25, 0.028);
  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 200);

  /* floor, mat, lines */
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(90, 90),
    new THREE.MeshStandardMaterial({ map: floorTexture(), roughness: 0.42, metalness: 0.05, color: 0x8a6a52 }));
  floor.rotation.x = -Math.PI / 2; scene.add(floor);
  const ct = courtTexture();
  const mat = new THREE.Mesh(new THREE.PlaneGeometry(ct.w, ct.l), new THREE.MeshStandardMaterial({ map: ct.tex, roughness: 0.78 }));
  mat.rotation.x = -Math.PI / 2; mat.position.y = 0.006; scene.add(mat);

  /* net */
  const postMat = new THREE.MeshStandardMaterial({ color: 0xd9dcd2, roughness: 0.4, metalness: 0.4 });
  for (const x of [-COURT_W / 2, COURT_W / 2]) {
    const post = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 1.55, 10), postMat);
    post.position.set(x, 0.775, 0); scene.add(post);
    const foot = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.18, 0.06, 18), new THREE.MeshStandardMaterial({ color: 0x24303a }));
    foot.position.set(x, 0.03, 0); scene.add(foot);
  }
  const net = new THREE.Mesh(new THREE.PlaneGeometry(COURT_W, 0.72),
    new THREE.MeshStandardMaterial({ map: netTexture(), transparent: true, alphaTest: 0.05, side: THREE.DoubleSide, color: 0x111111, roughness: 1 }));
  net.material.alphaMap = net.material.map;
  net.position.set(0, NET_TOP - 0.075 - 0.36, 0); scene.add(net);
  const tape = new THREE.Mesh(new THREE.BoxGeometry(COURT_W, 0.075, 0.012), new THREE.MeshStandardMaterial({ color: 0xf4f4ee, roughness: 0.6 }));
  tape.position.set(0, NET_TOP - 0.0375, 0); scene.add(tape);

  /* stands: stepped timber tiers down both long sides */
  const timber = new THREE.MeshStandardMaterial({ color: 0x5a412d, roughness: 0.6 });
  const seatColors = [0x2c3f52, 0x3d2f45, 0x2c3f52, 0x4a3a2a];
  const m4 = new THREE.Matrix4();
  for (const side of [-1, 1]) {
    for (let row = 0; row < 7; row++) {
      const step = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.42 * (row + 1), 34), timber);
      step.position.set(side * (9.2 + row * 0.9), 0.21 * (row + 1), 0); scene.add(step);
      const seats = new THREE.InstancedMesh(new THREE.BoxGeometry(0.42, 0.34, 0.44), new THREE.MeshStandardMaterial({ color: seatColors[row % 4], roughness: 0.6 }), 60);
      for (let i = 0; i < 60; i++) { m4.makeTranslation(side * (9.2 + row * 0.9 + 0.1), 0.42 * (row + 1) + 0.17, -16.5 + i * 0.55); seats.setMatrixAt(i, m4); }
      scene.add(seats);
    }
  }
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x1b2631, roughness: 0.9 });
  for (const z of [-17.5, 17.5]) {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(40, 12), wallMat);
    wall.position.set(0, 6, z); wall.rotation.y = z > 0 ? Math.PI : 0; scene.add(wall);
    for (let i = -3; i <= 3; i++) {
      const panel = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 1.1), new THREE.MeshStandardMaterial({ color: i % 2 ? 0x1e6a50 : 0x24384a, roughness: 0.8 }));
      panel.position.set(i * 4.2, 1.2, z + (z > 0 ? -0.02 : 0.02)); panel.rotation.y = wall.rotation.y; scene.add(panel);
    }
  }
  const board = scoreboard();
  board.draw(won.before);
  const boardMesh = new THREE.Mesh(new THREE.PlaneGeometry(5.2, 1.8), new THREE.MeshBasicMaterial({ map: board.tex, toneMapped: false }));
  boardMesh.position.set(0, 5.6, -17.45); scene.add(boardMesh);
  const stripMat = new THREE.MeshBasicMaterial({ color: 0xffc777 });
  for (const side of [-1, 1]) for (let row = 0; row < 7; row += 2) {
    const strip = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.03, 34), stripMat);
    strip.position.set(side * (9.2 + row * 0.9 - 0.45), 0.42 * (row + 1) + 0.02, 0); scene.add(strip);
  }

  /* floodlights: eight fixtures with beams; four real spot lights (two on phones) */
  const LAMP_H = 8.2;
  const housingMat = new THREE.MeshStandardMaterial({ color: 0x0e141a, roughness: 0.5 });
  const fixtures = [];
  for (const z of [-10.5, -3.5, 3.5, 10.5]) {
    for (const x of [-4.2, 4.2]) {
      // phones look down from above the lamps, where the housings would only block the court
      const housing = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.22, 0.5), housingMat);
      housing.position.set(x, LAMP_H + 0.12, z); housing.visible = !phone; scene.add(housing);
      const lampMat = new THREE.MeshBasicMaterial({ color: 0x1a1d20 });
      const lamp = new THREE.Mesh(new THREE.PlaneGeometry(1.15, 0.38), lampMat);
      lamp.rotation.x = Math.PI / 2; lamp.position.set(x, LAMP_H, z); lamp.visible = !phone; scene.add(lamp);
      const cone = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 3.6, LAMP_H, 32, 1, true), coneMaterial());
      cone.position.set(x, LAMP_H / 2, z); scene.add(cone);
      fixtures.push({ lampMat, cone, pos: new THREE.Vector3(x, LAMP_H, z) });
    }
  }
  const spotSpots = phone ? [[0, -6.5], [0, 6.5]] : [[-4.2, -7], [4.2, -7], [-4.2, 7], [4.2, 7]];
  const spotPower = phone ? 900 : 520;
  const spots = spotSpots.map(([x, z]) => {
    const s = new THREE.SpotLight(FLOOD, 0, 40, phone ? 0.75 : 0.62, 0.75, 2);
    s.position.set(x, LAMP_H, z); s.target.position.set(x * 0.25, 0, z * 0.55);
    scene.add(s, s.target); return s;
  });
  scene.add(new THREE.HemisphereLight(0x34475c, 0x4a3626, 0.9));
  const lampOn = new THREE.Color(0xfff3d6), lampOff = new THREE.Color(0x1a1d20);
  /** The one orchestrated moment: the lights come on, far banks first, with a flicker. */
  function setLights(elapsed) {
    let total = 0;
    fixtures.forEach((f, k) => {
      const start = 0.25 + Math.floor(k / 2) * 0.32 + (k % 2) * 0.08;
      let lvl = still ? 1 : Math.min(Math.max((elapsed - start) / 0.35, 0), 1);
      if (!still && elapsed > start + 0.05 && elapsed < start + 0.12) lvl *= 0.25; // flicker as it strikes
      f.lampMat.color.copy(lampOff).lerp(lampOn, lvl);
      f.cone.material.uniforms.strength.value = (phone ? 0.16 : 0.32) * lvl;
      total += lvl;
    });
    const lvl = total / fixtures.length;
    spots.forEach((s) => (s.intensity = spotPower * lvl));
    return lvl >= 1;
  }

  /* dust drifting in the beams */
  const DUST = phone ? 160 : 420;
  const dustGeo = new THREE.BufferGeometry();
  const dustPos = new Float32Array(DUST * 3);
  for (let i = 0; i < DUST; i++) {
    const f = fixtures[i % fixtures.length].pos;
    const r = Math.random() * 2.6, a = Math.random() * Math.PI * 2, y = 1 + Math.random() * 7;
    dustPos.set([f.x + Math.cos(a) * r * (1 - y / 12), y, f.z + Math.sin(a) * r * (1 - y / 12)], i * 3);
  }
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
  const dustMat = new THREE.PointsMaterial({ color: FLOOD, size: 0.035, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false, map: radialTexture('rgba(255,255,255,1)', 'rgba(255,255,255,0)') });
  scene.add(new THREE.Points(dustGeo, dustMat));

  /* athletes */
  const shadowTex = radialTexture('rgba(0,0,0,0.6)', 'rgba(0,0,0,0)');
  const players = new Map();
  const formation = doublesFormation(match, rally.start_s, flights[flights.length-1].t1);
  for (const id of ids) {
    const a = makeAthlete(TEAM_COLOR[teamOf(match, id)] || 0xffffff);
    scene.add(a.root);
    a.shadows = spots.map(() => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false, opacity: phone ? 0.65 : 0.55 }));
      m.rotation.x = -Math.PI / 2; m.position.y = 0.01; scene.add(m); return m;
    });
    prepareAthlete(a, id, flights, match, rally, formation);
    players.set(id, a);
  }
  for (const [i, f] of flights.entries()) {
    const a = players.get(f.shot.hitter_id);
    if (!a) continue; // keep the positional estimate for an unidentified hitter
    poseAthlete(a, f.t0);
    a.rArm.wrist.localToWorld(f.from.set(0, -0.53, 0));
    if (i) flights[i - 1].to.copy(f.from);
  }
  const shuttleScale = phone ? 3.4 : 2.8;
  for (const [i,f] of flights.entries()) fitNet(f, shuttleScale, match, flights[i+1]?.shot);

  /* shuttlecock: cork, band and a feather skirt, nose first along its flight */
  const shuttle = new THREE.Group();
  const white = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.5, emissive: 0xffffff, emissiveIntensity: 0.35 });
  const cork = new THREE.Mesh(new THREE.SphereGeometry(0.0145, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), white);
  const band = new THREE.Mesh(new THREE.CylinderGeometry(0.0146, 0.0146, 0.01, 14), new THREE.MeshStandardMaterial({ color: 0xe0b14a, roughness: 0.6 }));
  band.position.y = -0.005;
  const skirt = new THREE.Mesh(new THREE.CylinderGeometry(0.013, 0.034, 0.068, 16, 1, true),
    new THREE.MeshStandardMaterial({ color: 0xffffff, map: featherTexture(), transparent: true, side: THREE.DoubleSide, depthWrite: false, emissive: 0xffffff, emissiveIntensity: 0.3, roughness: 0.8 }));
  skirt.position.y = -0.044;
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialTexture('rgba(255,244,214,0.75)', 'rgba(255,244,214,0)'), blending: THREE.AdditiveBlending, depthWrite: false }));
  glow.scale.set(0.12, 0.12, 1); glow.position.y = -0.02;
  shuttle.add(cork, band, skirt, glow);
  shuttle.scale.setScalar(shuttleScale);
  scene.add(shuttle);
  const shuttleShadow = new THREE.Mesh(new THREE.PlaneGeometry(0.35, 0.35), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
  shuttleShadow.rotation.x = -Math.PI / 2; shuttleShadow.position.y = 0.012; scene.add(shuttleShadow);

  const TRAIL = 46;
  const trailPts = [];
  const trailGeo = new THREE.BufferGeometry();
  const trailPos = new Float32Array(TRAIL * 2 * 3);
  const trailAlpha = new Float32Array(TRAIL * 2);
  const idx = [];
  for (let i = 0; i < TRAIL - 1; i++) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
  trailGeo.setIndex(idx);
  trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPos, 3));
  trailGeo.setAttribute('alpha', new THREE.BufferAttribute(trailAlpha, 1));
  const trail = new THREE.Mesh(trailGeo, new THREE.ShaderMaterial({
    uniforms: { color: { value: new THREE.Color(0xfff1cc) } },
    vertexShader: 'attribute float alpha; varying float vA; void main(){ vA=alpha; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
    fragmentShader: 'uniform vec3 color; varying float vA; void main(){ gl_FragColor=vec4(color*vA, vA); }',
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  }));
  trail.frustumCulled = false; scene.add(trail);
  const labels = [];

  /* camera: a slow sway, hover parallax on desktop, drag (or horizontal swipe) to orbit */
  // Optional local shot study (one-based index); ordinary landing playback is unchanged.
  const query = new URLSearchParams(location.search);
  const study = flights[Number(query.get('studyShot')) - 1];
  const rate = study && query.get('rate') === '0.25' ? 0.25 : 1;
  const base = phone ? { az: 0.26, el: 0.64, r: 17.5, fov: 50 } : { az: 0.62, el: 0.2, r: 20, fov: 38 };
  const target = phone ? new THREE.Vector3(0, 0.6, 0.9) : new THREE.Vector3(0, 2.0, 0.4);
  const cam = { az: base.az, el: base.el, user: 0, userEl: 0, hoverX: 0, hoverY: 0, v: 0, clock: 0 };
  let dragging = false, lastX = 0, lastY = 0, idleUntil = 0;
  const el = renderer.domElement;
  el.style.touchAction = 'pan-y'; // vertical swipes scroll the page; horizontal ones orbit
  el.addEventListener('pointerdown', (e) => { dragging = true; lastX = e.clientX; lastY = e.clientY; el.classList.add('grabbing'); if (e.pointerType === 'mouse') el.setPointerCapture(e.pointerId); });
  el.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'mouse') {
      const r = el.getBoundingClientRect();
      cam.hoverX = ((e.clientX - r.left) / r.width - 0.5) * 2;
      cam.hoverY = ((e.clientY - r.top) / r.height - 0.5) * 2;
    }
    if (!dragging) return;
    cam.v = (e.clientX - lastX) * -0.006;
    cam.user += cam.v;
    if (e.pointerType === 'mouse') cam.userEl = Math.min(Math.max(cam.userEl + (e.clientY - lastY) * 0.004, -0.15), 0.8);
    lastX = e.clientX; lastY = e.clientY; idleUntil = performance.now() + 4000;
    if (still) { placeCamera(0); render(); }
  });
  const endDrag = () => { dragging = false; el.classList.remove('grabbing'); };
  ['pointerup', 'pointercancel'].forEach((ev) => el.addEventListener(ev, endDrag));
  el.addEventListener('pointerleave', () => { cam.hoverX = cam.hoverY = 0; if (dragging) endDrag(); });

  function placeCamera(dt) {
    if (study) {
      const side = study.from.z < 0 ? -1 : 1;
      const handSide = study.shot.side === 'backhand' ? -side : side;
      camera.position.set(study.from.x + 4.2*handSide, 2.45, study.from.z - 3.8*side);
      camera.lookAt(study.from.x, 1.15, study.from.z);
      return;
    }
    if (!still && !dragging) {
      if (performance.now() > idleUntil) cam.clock += dt;
      cam.user += cam.v; cam.v *= 0.9;
    }
    const sway = still ? 0 : Math.sin(cam.clock * 0.07) * (phone ? 0.3 : 0.55);
    const az = base.az + cam.user + sway + (still ? 0 : cam.hoverX * 0.08);
    const elv = Math.min(base.el + cam.userEl + (still ? 0 : cam.hoverY * 0.04), 1.3);
    camera.position.set(
      target.x + Math.sin(az) * Math.cos(elv) * base.r,
      target.y + Math.sin(elv) * base.r,
      target.z + Math.cos(az) * Math.cos(elv) * base.r,
    );
    camera.lookAt(target);
  }

  /* replay clock */
  const t0 = study ? study.t0 - 0.42 : rally.start_s - 0.6;
  const lastT = flights[flights.length - 1].t1;
  const tEnd = study ? study.t0 + 0.55 : lastT + 2.2;
  let t = t0 + (Number(new URLSearchParams(location.search).get('heroT')) || 0), lastShot = -1;
  const tmp = new THREE.Vector3(), prev = new THREE.Vector3(), dir = new THREE.Vector3(), UP = new THREE.Vector3(0, 1, 0);
  const wantQ = new THREE.Quaternion();

  function update(dt) {
    let fi = flights.findIndex((f) => t >= f.t0 && t < f.t1);
    if (fi < 0) fi = t >= lastT ? flights.length : -1;
    // shuttle
    if (fi === -1) flightPoint(flights[0], flights[0].t0, tmp);
    else if (fi >= flights.length) flightPoint(flights[flights.length - 1], lastT, tmp);
    else flightPoint(flights[fi], t, tmp);
    prev.copy(shuttle.position);
    shuttle.position.copy(tmp);
    dir.copy(tmp).sub(prev);
    // Use the same tangent as the clearance solver, including after seeks.
    if (fi >= 0 && fi < flights.length) {
      const f = flights[fi];
      flightPoint(f,Math.max(f.t0,t-0.0001),prev);
      flightPoint(f,Math.min(f.t1,t+0.0001),dir).sub(prev);
    }
    if (dir.lengthSq() > 1e-14) {
      wantQ.setFromUnitVectors(UP, dir.normalize());
      shuttle.quaternion.copy(wantQ);
    }
    shuttleShadow.position.set(tmp.x, 0.012, tmp.z);
    shuttleShadow.material.opacity = Math.max(0.15, 0.8 - tmp.y * 0.12);

    // athletes
    for (const a of players.values()) {
      poseAthlete(a, t);
      a.flash = Math.max(0, a.flash - dt * 1.6);
      a.ring.material.opacity = 0.3 + a.flash * 0.7;
      a.ring.scale.setScalar(1 + a.flash * 0.5);
      a.shadows.forEach((m, i) => {
        m.material.opacity = (phone ? 0.65 : 0.55) * (1 - 0.64 * a.airHeight);
        const L = spots[i].position;
        const dx = a.pos.x - L.x, dz = a.pos.z - L.z;
        const dist = Math.hypot(dx, dz) || 1;
        const len = Math.min(1.75 * dist / (L.y - 1.75), 5);
        m.position.set(a.pos.x + (dx / dist) * len * 0.5, 0.01 + i * 0.0005, a.pos.z + (dz / dist) * len * 0.5);
        m.rotation.z = -Math.atan2(dz, dx);
        m.scale.set(len + 0.7, 0.75, 1);
      });
    }

    // contacts
    const cur = fi >= flights.length ? flights.length - 1 : fi;
    if (cur > lastShot) {
      for (let i = lastShot + 1; i <= cur; i++) contact(i, i < cur || t - flights[i].t0 > 0.4);
      lastShot = cur;
    }
    board.draw(t > lastT + 0.4 ? won.after : won.before);

    // trail ribbon
    trailPts.unshift(tmp.clone());
    if (trailPts.length > TRAIL) trailPts.pop();
    const camDir = camera.position.clone().sub(tmp).normalize();
    for (let i = 0; i < TRAIL; i++) {
      const p = trailPts[Math.min(i, trailPts.length - 1)];
      const q = trailPts[Math.min(i + 1, trailPts.length - 1)];
      const sdir = q.clone().sub(p);
      if (sdir.lengthSq() < 1e-8) sdir.set(1, 0, 0);
      const side = sdir.cross(camDir).normalize().multiplyScalar(0.045 * (1 - i / TRAIL));
      trailPos.set([p.x + side.x, p.y + side.y, p.z + side.z, p.x - side.x, p.y - side.y, p.z - side.z], i * 6);
      const al = i < trailPts.length ? Math.pow(1 - i / TRAIL, 1.6) * 0.85 : 0;
      trailAlpha[i * 2] = trailAlpha[i * 2 + 1] = al;
    }
    trailGeo.attributes.position.needsUpdate = true;
    trailGeo.attributes.alpha.needsUpdate = true;

    for (let i = labels.length - 1; i >= 0; i--) {
      const L = labels[i];
      L.age += dt;
      const k = L.age / 1.9;
      L.s.position.y = L.y + k * 0.7;
      L.s.material.opacity = k < 0.12 ? k / 0.12 : Math.max(0, 1 - (k - 0.55) / 0.45);
      if (k >= 1) { scene.remove(L.s); L.s.material.map.dispose(); L.s.material.dispose(); labels.splice(i, 1); }
    }
    const arr = dustGeo.attributes.position.array;
    for (let i = 1; i < arr.length; i += 3) { arr[i] += dt * 0.05; if (arr[i] > 8) arr[i] = 1; }
    dustGeo.attributes.position.needsUpdate = true;
  }

  function contact(i, quiet = false) {
    const f = flights[i];
    const a = players.get(f.shot.hitter_id);
    if (a && !quiet) a.flash = 1;
    const sp = speedOf(f.shot);
    const label = labelText(f.label);
    if (sp && !still && !quiet && !study) {
      labels.forEach((L) => (L.age = Math.max(L.age, 1.45))); // one speed in the air at a time
      const s = labelSprite(sp.bound ? 'Speed uncertain' : `${sp.kmh} km/h`, sp.settled ? 'est. at +0.1 s' : label.toLowerCase(), sp.bound ? '#ffe6b0' : '#ffffff');
      if (phone) s.scale.multiplyScalar(1.35);
      s.position.copy(f.from).add(new THREE.Vector3(0, 0.9, 0));
      scene.add(s); labels.push({ s, age: 0, y: s.position.y });
    }
    onShot && onShot({ index: i, total: flights.length, shot: f.shot, label, speed: sp, rally });
  }

  function render() { renderer.render(scene, camera); }
  function resize() {
    const w = container.clientWidth, h = container.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.fov = base.fov;
    // on wide screens slide the court right, clear of the headline
    if (study) camera.clearViewOffset();
    else if (!phone && w / h > 1.2) camera.setViewOffset(w, h, -w * 0.17, 0, w, h);
    else if (phone) camera.setViewOffset(w, h, 0, h * 0.07, w, h); // lift the court clear of the readout
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
    if (still) { placeCamera(0); render(); }
  }
  const ro = new ResizeObserver(resize); ro.observe(container);

  let raf = 0, visible = true, last = performance.now(), running = false, lightsDone = false;
  const born = performance.now();
  function frame(now) {
    raf = 0;
    if (!running) return;
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    if (!lightsDone) { lightsDone = setLights((now - born) / 1000); dustMat.opacity = lightsDone ? 0.55 : 0.2; }
    t += dt * rate;
    if (t > tEnd) { t = t0; lastShot = -1; trailPts.length = 0; }
    placeCamera(dt);
    update(dt * rate);
    render();
    raf = requestAnimationFrame(frame);
  }
  function start() { if (running || still) return; running = true; last = performance.now(); raf = requestAnimationFrame(frame); }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = 0; }
  const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; visible && !document.hidden ? start() : stop(); }, { threshold: 0.02 });
  io.observe(container);
  const onVis = () => (document.hidden || !visible ? stop() : start());
  document.addEventListener('visibilitychange', onVis);

  if (still) {
    // Hold one telling moment: the shuttle at the top of a lift, trail drawn behind it, lights already on.
    setLights(99); dustMat.opacity = 0.55;
    const pick = flights.find((f) => f.label === 'lift' && f.t1 - f.t0 > 0.8) || flights[Math.floor(flights.length / 2)];
    const at = study ? study.t0 : pick.t0 + (pick.t1 - pick.t0) * 0.5;
    resize(); placeCamera(0);
    for (let k = 0; k < 30; k++) { t = at - (30 - k) * 0.016; update(0.016); }
    render();
  } else {
    resize(); start();
  }

  return {
    rally, won,
    destroy() {
      stop(); io.disconnect(); ro.disconnect();
      document.removeEventListener('visibilitychange', onVis);
      renderer.dispose(); renderer.domElement.remove();
    },
  };
}
