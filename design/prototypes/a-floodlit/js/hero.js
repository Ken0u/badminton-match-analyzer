// The landing hero: one real rally replayed on a court in a floodlit hall.
import * as THREE from 'three';
import { positionAt, shotLabel, labelText, speedOf, teamOf } from './data.js';

const COURT_W = 6.1, COURT_L = 13.4;
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
    flights.push({ shot: s, label: a.label, from: a.pos, to: b, t0: s.time_s, t1, apex, drag: HIGH.has(a.label) ? 2.2 : 1.3 });
  }
  return flights;
}

function flightPoint(f, t, out) {
  const tt = Math.min(Math.max((t - f.t0) / Math.max(f.t1 - f.t0, 0.05), 0), 1);
  const u = (1 - Math.exp(-f.drag * tt)) / (1 - Math.exp(-f.drag)); // air drag: fast out, slow in
  const h0 = f.from.y, a = f.to.y - h0, D = f.apex - h0;
  const q = 2 * D - a;
  const k = D <= 0.001 ? 0 : q + Math.sqrt(Math.max(q * q - a * a, 0));
  out.set(f.from.x + (f.to.x - f.from.x) * u, h0 + (a + k) * u - k * u * u, f.from.z + (f.to.z - f.from.z) * u);
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

function scoreboardTexture(match, rally) {
  const c = document.createElement('canvas'); c.width = 1040; c.height = 320;
  const g = c.getContext('2d');
  g.fillStyle = '#0b1016'; g.fillRect(0, 0, 1040, 320);
  g.strokeStyle = '#2a3644'; g.lineWidth = 6; g.strokeRect(3, 3, 1034, 314);
  const sc = rally.score?.before || { T1: 0, T2: 0 };
  if ('fontStretch' in g) g.fontStretch = 'condensed';
  g.textAlign = 'center';
  g.font = '800 210px Anybody, sans-serif';
  g.fillStyle = '#f2b23e'; g.fillText(String(sc.T1), 300, 240);
  g.fillStyle = '#86c9f2'; g.fillText(String(sc.T2), 740, 240);
  g.fillStyle = '#ffe6b0'; g.fillRect(512, 120, 16, 16); g.fillRect(512, 190, 16, 16);
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

/* ---------- light cones ---------- */
function coneMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { color: { value: new THREE.Color(FLOOD) }, strength: { value: 0.32 } },
    vertexShader: `varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ vUv=uv; vec4 mv=modelViewMatrix*vec4(position,1.0); vN=normalize(normalMatrix*normal); vV=normalize(-mv.xyz); gl_Position=projectionMatrix*mv; }`,
    fragmentShader: `uniform vec3 color; uniform float strength; varying vec2 vUv; varying vec3 vN; varying vec3 vV;
      void main(){ float edge=pow(abs(dot(vN,vV)),2.2); float a=strength*edge*(0.25+0.75*pow(vUv.y,1.2)); gl_FragColor=vec4(color*a,a); }`,
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide,
  });
}

export function createHero(container, match, { still = false, onShot, onRallyEnd } = {}) {
  const rally = pickRally(match);
  const flights = buildFlights(match, rally);
  const ids = match.analysis.players.map((p) => p.id);

  const renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 1.75));
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.domElement.setAttribute('aria-hidden', 'true');
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const HALL = new THREE.Color(0x131c25);
  scene.background = HALL;
  scene.fog = new THREE.FogExp2(0x131c25, 0.028);

  const camera = new THREE.PerspectiveCamera(36, 1, 0.1, 200);

  /* floor, mat, lines */
  const floor = new THREE.Mesh(new THREE.PlaneGeometry(90, 90),
    new THREE.MeshStandardMaterial({ map: floorTexture(), roughness: 0.42, metalness: 0.05, color: 0x8a6a52 }));
  floor.rotation.x = -Math.PI / 2; scene.add(floor);
  const ct = courtTexture();
  const mat = new THREE.Mesh(new THREE.PlaneGeometry(ct.w, ct.l),
    new THREE.MeshStandardMaterial({ map: ct.tex, roughness: 0.78 }));
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
  net.position.set(0, 1.55 - 0.075 - 0.36, 0); scene.add(net);
  const tape = new THREE.Mesh(new THREE.BoxGeometry(COURT_W, 0.075, 0.012), new THREE.MeshStandardMaterial({ color: 0xf4f4ee, roughness: 0.6 }));
  tape.position.set(0, 1.55 - 0.0375, 0); scene.add(tape);

  /* stands: stepped timber tiers down both long sides, receding into the dark */
  const timber = new THREE.MeshStandardMaterial({ color: 0x5a412d, roughness: 0.6 });
  const seatColors = [0x2c3f52, 0x3d2f45, 0x2c3f52, 0x4a3a2a];
  for (const side of [-1, 1]) {
    for (let row = 0; row < 7; row++) {
      const step = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.42 * (row + 1), 34), timber);
      step.position.set(side * (9.2 + row * 0.9), 0.21 * (row + 1), 0); scene.add(step);
      const seats = new THREE.InstancedMesh(new THREE.BoxGeometry(0.42, 0.34, 0.44),
        new THREE.MeshStandardMaterial({ color: seatColors[row % 4], roughness: 0.6 }), 60);
      const m4 = new THREE.Matrix4();
      for (let i = 0; i < 60; i++) {
        m4.makeTranslation(side * (9.2 + row * 0.9 + 0.1), 0.42 * (row + 1) + 0.17, -16.5 + i * 0.55);
        seats.setMatrixAt(i, m4);
      }
      scene.add(seats);
    }
  }
  // end walls with dim panels
  const wallMat = new THREE.MeshStandardMaterial({ color: 0x1b2631, roughness: 0.9 });
  for (const z of [-17.5, 17.5]) {
    const wall = new THREE.Mesh(new THREE.PlaneGeometry(40, 12), wallMat);
    wall.position.set(0, 6, z); wall.rotation.y = z > 0 ? Math.PI : 0; scene.add(wall);
    for (let i = -3; i <= 3; i++) {
      const panel = new THREE.Mesh(new THREE.PlaneGeometry(3.6, 1.1), new THREE.MeshStandardMaterial({ color: i % 2 ? 0x1e6a50 : 0x24384a, roughness: 0.8 }));
      panel.position.set(i * 4.2, 1.2, z + (z > 0 ? -0.02 : 0.02)); panel.rotation.y = wall.rotation.y; scene.add(panel);
    }
  }

  /* floodlights: visible fixtures, four real spot lights, additive beams */
  const fixtures = [];
  const lampMat = new THREE.MeshBasicMaterial({ color: 0xfff3d6 });
  const housingMat = new THREE.MeshStandardMaterial({ color: 0x0e141a, roughness: 0.5 });
  const coneMat = coneMaterial();
  const LAMP_H = 8.2;
  for (const x of [-4.2, 4.2]) {
    for (const z of [-10.5, -3.5, 3.5, 10.5]) {
      const housing = new THREE.Mesh(new THREE.BoxGeometry(1.3, 0.22, 0.5), housingMat);
      housing.position.set(x, LAMP_H + 0.12, z); scene.add(housing);
      const lamp = new THREE.Mesh(new THREE.PlaneGeometry(1.15, 0.38), lampMat);
      lamp.rotation.x = Math.PI / 2; lamp.position.set(x, LAMP_H, z); scene.add(lamp);
      const cone = new THREE.Mesh(new THREE.CylinderGeometry(0.55, 3.6, LAMP_H, 32, 1, true), coneMat);
      cone.position.set(x, LAMP_H / 2, z); scene.add(cone);
      fixtures.push(new THREE.Vector3(x, LAMP_H, z));
    }
  }
  const spots = [];
  for (const [x, z] of [[-4.2, -7], [4.2, -7], [-4.2, 7], [4.2, 7]]) {
    const s = new THREE.SpotLight(FLOOD, 520, 40, 0.62, 0.75, 2);
    s.position.set(x, LAMP_H, z);
    s.target.position.set(x * 0.25, 0, z * 0.55);
    scene.add(s, s.target); spots.push(s);
  }
  scene.add(new THREE.HemisphereLight(0x34475c, 0x4a3626, 0.9));
  // stair lights along the stands give the dark hall its depth
  const stripMat = new THREE.MeshBasicMaterial({ color: 0xffc777 });
  for (const side of [-1, 1]) for (let row = 0; row < 7; row += 2) {
    const strip = new THREE.Mesh(new THREE.BoxGeometry(0.04, 0.03, 34), stripMat);
    strip.position.set(side * (9.2 + row * 0.9 - 0.45), 0.42 * (row + 1) + 0.02, 0); scene.add(strip);
  }
  // a scoreboard glowing on the far wall
  const board = new THREE.Mesh(new THREE.PlaneGeometry(5.2, 1.6), new THREE.MeshBasicMaterial({ map: scoreboardTexture(match, rally), toneMapped: false }));
  board.position.set(0, 5.6, -17.45); scene.add(board);

  /* dust in the beams */
  const DUST = 420;
  const dustGeo = new THREE.BufferGeometry();
  const dustPos = new Float32Array(DUST * 3);
  for (let i = 0; i < DUST; i++) {
    const f = fixtures[i % fixtures.length];
    const r = Math.random() * 2.6, a = Math.random() * Math.PI * 2, y = 1 + Math.random() * 8;
    dustPos.set([f.x + Math.cos(a) * r * (1 - y / 12), y, f.z + Math.sin(a) * r * (1 - y / 12)], i * 3);
  }
  dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPos, 3));
  const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({ color: FLOOD, size: 0.035, transparent: true, opacity: 0.55,
    blending: THREE.AdditiveBlending, depthWrite: false, map: radialTexture('rgba(255,255,255,1)', 'rgba(255,255,255,0)') }));
  scene.add(dust);

  /* players */
  const shadowTex = radialTexture('rgba(0,0,0,0.6)', 'rgba(0,0,0,0)');
  const ringTex = radialTexture('rgba(255,255,255,0)', 'rgba(255,255,255,0)');
  const players = new Map();
  for (const id of ids) {
    const team = teamOf(match, id);
    const color = TEAM_COLOR[team] || 0xffffff;
    const g = new THREE.Group();
    const kit = new THREE.MeshStandardMaterial({ color, roughness: 0.55, emissive: color, emissiveIntensity: 0.12 });
    const skin = new THREE.MeshStandardMaterial({ color: 0xe8d6c4, roughness: 0.7 });
    const dark = new THREE.MeshStandardMaterial({ color: 0x1b2631, roughness: 0.7 });
    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.2, 0.5, 6, 12), kit); torso.position.y = 1.18; g.add(torso);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.12, 16, 12), skin); head.position.y = 1.67; g.add(head);
    for (const s of [-1, 1]) {
      const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.075, 0.6, 4, 8), dark); leg.position.set(s * 0.1, 0.4, 0); g.add(leg);
    }
    const arm = new THREE.Group(); arm.position.set(0.24, 1.38, 0); g.add(arm);
    const upper = new THREE.Mesh(new THREE.CapsuleGeometry(0.05, 0.42, 4, 8), skin); upper.position.y = 0.22; arm.add(upper);
    const shaft = new THREE.Mesh(new THREE.CylinderGeometry(0.008, 0.008, 0.42, 6), postMat); shaft.position.y = 0.62; arm.add(shaft);
    const head2 = new THREE.Mesh(new THREE.TorusGeometry(0.11, 0.009, 6, 24), postMat); head2.position.y = 0.92; head2.scale.y = 1.3; arm.add(head2);
    arm.rotation.z = -0.5;
    // pool of light at the feet; brightens on contact
    const ring = new THREE.Mesh(new THREE.RingGeometry(0.38, 0.46, 40),
      new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.35, depthWrite: false, blending: THREE.AdditiveBlending }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.012; g.add(ring);
    scene.add(g);
    // one soft shadow per floodlight bank: the four-way shadows of a lit hall
    const shadows = spots.map(() => {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false, opacity: 0.55 }));
      m.rotation.x = -Math.PI / 2; m.position.y = 0.01; scene.add(m); return m;
    });
    players.set(id, { g, arm, ring, shadows, swing: -1, pos: new THREE.Vector3(), heading: 0 });
  }
  void ringTex;

  /* shuttle + ribbon trail */
  const shuttle = new THREE.Group();
  const cork = new THREE.Mesh(new THREE.SphereGeometry(0.035, 12, 10), new THREE.MeshBasicMaterial({ color: 0xffffff }));
  const skirt = new THREE.Mesh(new THREE.ConeGeometry(0.05, 0.09, 14, 1, true), new THREE.MeshBasicMaterial({ color: 0xf6f3ea, side: THREE.DoubleSide }));
  skirt.position.y = 0.055; skirt.rotation.x = Math.PI; shuttle.add(cork, skirt);
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: radialTexture('rgba(255,244,214,0.95)', 'rgba(255,244,214,0)'), blending: THREE.AdditiveBlending, depthWrite: false }));
  glow.scale.set(0.55, 0.55, 1); shuttle.add(glow);
  shuttle.scale.setScalar(1.8);
  scene.add(shuttle);
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
  // the floor shadow of the shuttle helps read its height
  const shuttleShadow = new THREE.Mesh(new THREE.PlaneGeometry(0.35, 0.35), new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
  shuttleShadow.rotation.x = -Math.PI / 2; shuttleShadow.position.y = 0.012; scene.add(shuttleShadow);

  const labels = [];

  /* camera: slow drift, hover parallax, drag to orbit */
  const cam = { az: 0.62, el: 0.2, r: 21, dragAz: 0, dragEl: 0, hoverX: 0, hoverY: 0, vx: 0 };
  const target = new THREE.Vector3(0, 2.0, 0.4);
  let dragging = false, lastX = 0, lastY = 0, idleUntil = 0;
  const el = renderer.domElement;
  const finePointer = matchMedia('(pointer: fine)').matches;
  el.style.touchAction = 'pan-y';
  el.addEventListener('pointerdown', (e) => {
    if (e.pointerType !== 'mouse' && !finePointer) return;
    dragging = true; lastX = e.clientX; lastY = e.clientY; el.setPointerCapture(e.pointerId); el.classList.add('grabbing');
  });
  el.addEventListener('pointermove', (e) => {
    const r = el.getBoundingClientRect();
    cam.hoverX = ((e.clientX - r.left) / r.width - 0.5) * 2;
    cam.hoverY = ((e.clientY - r.top) / r.height - 0.5) * 2;
    if (!dragging) return;
    cam.vx = (e.clientX - lastX) * -0.006;
    cam.az += cam.vx;
    cam.el = Math.min(Math.max(cam.el + (e.clientY - lastY) * 0.004, 0.12), 1.15);
    lastX = e.clientX; lastY = e.clientY; idleUntil = performance.now() + 4000;
    if (still) render();
  });
  const endDrag = () => { dragging = false; el.classList.remove('grabbing'); };
  el.addEventListener('pointerup', endDrag); el.addEventListener('pointercancel', endDrag);
  el.addEventListener('pointerleave', () => { cam.hoverX = cam.hoverY = 0; });

  function placeCamera(dt) {
    if (!still && !dragging) {
      if (performance.now() > idleUntil) cam.az += dt * 0.035;
      cam.az += cam.vx; cam.vx *= 0.92;
    }
    const az = cam.az + (still ? 0 : cam.hoverX * 0.08);
    const elv = cam.el + (still ? 0 : cam.hoverY * 0.04);
    camera.position.set(
      target.x + Math.sin(az) * Math.cos(elv) * cam.r,
      target.y + Math.sin(elv) * cam.r,
      target.z + Math.cos(az) * Math.cos(elv) * cam.r,
    );
    camera.lookAt(target);
  }

  /* timeline */
  const t0 = rally.start_s - 0.6;
  const tEnd = flights[flights.length - 1].t1 + 1.8;
  // ?heroT=seconds starts the replay part-way in (handy for stills)
  let t = t0 + (Number(new URLSearchParams(location.search).get('heroT')) || 0), lastShot = -1;
  const tmp = new THREE.Vector3();
  const prevShuttle = new THREE.Vector3();

  function update(now, dt) {
    // players
    let fi = flights.findIndex((f) => t >= f.t0 && t < f.t1);
    if (fi < 0) fi = t >= flights[flights.length - 1].t1 ? flights.length : -1;
    for (const [id, p] of players) {
      const pos = positionAt(match, id, Math.min(Math.max(t, rally.start_s), tEnd));
      if (pos) p.pos.copy(toScene(pos));
      p.g.position.copy(p.pos);
      // face the shuttle
      const want = Math.atan2(shuttle.position.x - p.pos.x, shuttle.position.z - p.pos.z);
      let d = want - p.heading; d = Math.atan2(Math.sin(d), Math.cos(d));
      p.heading += d * Math.min(1, dt * 6);
      p.g.rotation.y = p.heading;
      // racket swing after contact
      if (p.swing >= 0) {
        p.swing += dt;
        const s = Math.min(p.swing / 0.35, 1);
        p.arm.rotation.x = -Math.sin(s * Math.PI) * 1.6;
        p.ring.material.opacity = 0.35 + (1 - s) * 0.65;
        p.ring.scale.setScalar(1 + (1 - s) * 0.5);
        if (s >= 1) { p.swing = -1; p.arm.rotation.x = 0; }
      }
      p.shadows.forEach((m, i) => {
        const L = spots[i].position;
        const dx = p.pos.x - L.x, dz = p.pos.z - L.z;
        const dist = Math.hypot(dx, dz) || 1;
        const len = Math.min(1.75 * dist / (L.y - 1.75), 5);
        m.position.set(p.pos.x + (dx / dist) * len * 0.5, 0.01 + i * 0.0005, p.pos.z + (dz / dist) * len * 0.5);
        m.rotation.z = -Math.atan2(dz, dx);
        m.scale.set(len + 0.7, 0.75, 1);
      });
    }
    // shuttle
    if (fi === -1) flightPoint(flights[0], flights[0].t0, tmp);
    else if (fi >= flights.length) flightPoint(flights[flights.length - 1], flights[flights.length - 1].t1, tmp);
    else flightPoint(flights[fi], t, tmp);
    prevShuttle.copy(shuttle.position);
    shuttle.position.copy(tmp);
    const vel = tmp.clone().sub(prevShuttle);
    if (vel.lengthSq() > 1e-6) shuttle.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), vel.normalize().negate());
    shuttleShadow.position.set(tmp.x, 0.012, tmp.z);
    shuttleShadow.material.opacity = Math.max(0.15, 0.8 - tmp.y * 0.12);

    // contacts
    const cur = fi >= flights.length ? flights.length - 1 : fi;
    if (cur > lastShot) {
      // when catching up (a jump in time), only the latest contact gets a label
      for (let i = lastShot + 1; i <= cur; i++) contact(i, i < cur || t - flights[i].t0 > 0.4);
      lastShot = cur;
    }

    // trail
    trailPts.unshift(tmp.clone());
    if (trailPts.length > TRAIL) trailPts.pop();
    const camDir = camera.position.clone().sub(tmp).normalize();
    for (let i = 0; i < TRAIL; i++) {
      const p = trailPts[Math.min(i, trailPts.length - 1)];
      const q = trailPts[Math.min(i + 1, trailPts.length - 1)];
      const dir = q.clone().sub(p);
      if (dir.lengthSq() < 1e-8) dir.set(1, 0, 0);
      const side = dir.cross(camDir).normalize().multiplyScalar(0.05 * (1 - i / TRAIL));
      trailPos.set([p.x + side.x, p.y + side.y, p.z + side.z, p.x - side.x, p.y - side.y, p.z - side.z], i * 6);
      const a = i < trailPts.length ? Math.pow(1 - i / TRAIL, 1.6) * 0.9 : 0;
      trailAlpha[i * 2] = trailAlpha[i * 2 + 1] = a;
    }
    trailGeo.attributes.position.needsUpdate = true;
    trailGeo.attributes.alpha.needsUpdate = true;

    // speed labels rise and fade
    for (let i = labels.length - 1; i >= 0; i--) {
      const L = labels[i];
      L.age += dt;
      const k = L.age / 1.9;
      L.s.position.y = L.y + k * 0.7;
      L.s.material.opacity = k < 0.12 ? k / 0.12 : Math.max(0, 1 - (k - 0.55) / 0.45);
      if (k >= 1) { scene.remove(L.s); L.s.material.map.dispose(); L.s.material.dispose(); labels.splice(i, 1); }
    }
    // dust drifts
    const arr = dustGeo.attributes.position.array;
    for (let i = 1; i < arr.length; i += 3) { arr[i] += dt * 0.05; if (arr[i] > 9) arr[i] = 1; }
    dustGeo.attributes.position.needsUpdate = true;
  }

  function contact(i, quiet = false) {
    const f = flights[i];
    const p = players.get(f.shot.hitter_id);
    if (p && !still) p.swing = 0;
    const sp = speedOf(f.shot);
    const label = labelText(f.label);
    if (sp && !still && !quiet) {
      const s = labelSprite(sp.bound ? 'Too fast to clock' : `${sp.kmh} km/h`, label.toLowerCase(), sp.bound ? '#ffe6b0' : '#ffffff');
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
    // pull back on narrow screens so the whole court stays in frame
    const aspect = w / h;
    cam.r = aspect < 0.8 ? 30 : aspect < 1.2 ? 25 : 20;
    camera.fov = aspect < 0.8 ? 46 : 38;
    // on wide screens slide the court right, clear of the headline; on phones push it up, clear of the copy
    if (aspect > 1.2) camera.setViewOffset(w, h, -w * 0.17, 0, w, h);
    else camera.setViewOffset(w, h, 0, h * 0.16, w, h);
    camera.updateProjectionMatrix();
    if (still) { placeCamera(0); render(); }
  }
  const ro = new ResizeObserver(resize); ro.observe(container);

  let raf = 0, visible = true, last = performance.now(), running = false;
  function frame(now) {
    raf = 0;
    if (!running) return;
    const dt = Math.min((now - last) / 1000, 0.05); last = now;
    t += dt;
    if (t > tEnd) {
      onRallyEnd && onRallyEnd(rally);
      t = t0; lastShot = -1; trailPts.length = 0;
    }
    placeCamera(dt);
    update(now, dt);
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
    // Hold one telling moment: the shuttle at the top of a lift, trail drawn behind it.
    const pick = flights.find((f) => f.label === 'lift' && f.t1 - f.t0 > 0.8) || flights[Math.floor(flights.length / 2)];
    const at = pick.t0 + (pick.t1 - pick.t0) * 0.5;
    resize(); placeCamera(0);
    for (let k = 0; k < 30; k++) { t = at - (30 - k) * 0.016; update(0, 0.016); }
    resize(); placeCamera(0); render();
  } else {
    resize(); start();
  }

  return {
    rally,
    destroy() {
      stop(); io.disconnect(); ro.disconnect();
      document.removeEventListener('visibilitychange', onVis);
      renderer.dispose(); renderer.domElement.remove();
    },
  };
}
