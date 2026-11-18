// The landing hero: a procedurally built feather shuttlecock that hangs and
// turns, then launches along the match's fastest well-measured shot.
// Progress p (0..1) drives everything, so scroll can scrub the flight.
import * as THREE from 'three';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { solveToTarget, kmh } from './physics.js';

const C = {
  plume: 0xf4f6f8,
  tube: 0x1f3dff,
  cork: 0xb4834f,
  line: 0x9aa7b6,
  feather: 0xfbfcfd,
};

const smooth = (t) => t * t * (3 - 2 * t);
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, t) => a + (b - a) * t;

// ---------- textures ----------

function corkTexture() {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 128;
  const g = c.getContext('2d');
  g.fillStyle = '#c39a6c';
  g.fillRect(0, 0, 256, 128);
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 2600; i++) {
    const x = rnd() * 256;
    const y = rnd() * 128;
    const r = 0.4 + rnd() * 1.6;
    const d = rnd();
    g.fillStyle = d < 0.5 ? `rgba(120,80,45,${0.15 + rnd() * 0.3})` : `rgba(235,205,165,${0.2 + rnd() * 0.3})`;
    g.beginPath();
    g.arc(x, y, r, 0, Math.PI * 2);
    g.fill();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.wrapS = THREE.RepeatWrapping;
  return t;
}

function featherTexture() {
  const w = 256;
  const h = 512;
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const g = c.getContext('2d');
  g.fillStyle = '#ffffff';
  g.fillRect(0, 0, w, h);
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  // barbs: fine lines from the rachis out and up to both edges
  for (let y = -60; y < h + 40; y += 3) {
    const tone = 200 + Math.floor(rnd() * 30);
    g.strokeStyle = `rgba(${tone - 25},${tone - 15},${tone},${0.22 + rnd() * 0.18})`;
    g.lineWidth = 0.8;
    g.beginPath();
    g.moveTo(w / 2, h - y);
    g.quadraticCurveTo(w * 0.3, h - y - 30, 0, h - y - 70);
    g.moveTo(w / 2, h - y);
    g.quadraticCurveTo(w * 0.7, h - y - 30, w, h - y - 70);
    g.stroke();
  }
  // rachis
  g.strokeStyle = 'rgba(205,212,222,0.9)';
  g.lineWidth = 5;
  g.beginPath();
  g.moveTo(w / 2, h);
  g.lineTo(w / 2, 6);
  g.stroke();
  // ragged edges: small gaps where barbs separate
  g.globalCompositeOperation = 'destination-out';
  for (let i = 0; i < 70; i++) {
    const side = rnd() < 0.5 ? 0 : w;
    const y = rnd() * h;
    const depth = 8 + rnd() * 34;
    g.beginPath();
    g.moveTo(side, y);
    g.lineTo(Math.abs(side - depth), y - 14 - rnd() * 18);
    g.lineTo(side, y - 4 - rnd() * 6);
    g.fill();
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

// ---------- the shuttle (built in centimetres, cork at the bottom) ----------

function buildShuttle() {
  const g = new THREE.Group();
  const corkMat = new THREE.MeshStandardMaterial({ map: corkTexture(), roughness: 0.95, metalness: 0 });
  const R = 1.32;
  const dome = new THREE.Mesh(new THREE.SphereGeometry(R, 48, 20, 0, Math.PI * 2, Math.PI / 2, Math.PI / 2), corkMat);
  const side = new THREE.Mesh(new THREE.CylinderGeometry(R, R, 1.25, 48, 1, true), corkMat);
  side.position.y = 0.625;
  const top = new THREE.Mesh(new THREE.CircleGeometry(R, 48), corkMat);
  top.rotation.x = -Math.PI / 2;
  top.position.y = 1.25;
  const tubeMat = new THREE.MeshStandardMaterial({ color: C.tube, roughness: 0.55 });
  const band = new THREE.Mesh(new THREE.CylinderGeometry(R + 0.012, R + 0.012, 0.2, 48, 1, true), tubeMat);
  band.position.y = 1.08;
  g.add(dome, side, top, band);

  // feather skirt geometry
  const N = 16;
  const rb = 1.0;
  const yb = 1.15;
  const rt = 3.3;
  const yt = 7.35;
  const radius = (s) => rb + (rt - rb) * s;
  const height = (s) => yb + (yt - yb) * s;

  const quillMat = new THREE.MeshStandardMaterial({ color: 0xf2f4f6, roughness: 0.6 });
  const featherMat = new THREE.MeshStandardMaterial({
    map: featherTexture(),
    color: C.feather,
    roughness: 0.92,
    side: THREE.DoubleSide,
    transparent: true,
    alphaTest: 0.35,
  });

  const SU = 10;
  const SV = 26;
  const positions = [];
  const uvs = [];
  const index = [];
  const step = (Math.PI * 2) / N;
  const span = step * 1.62; // overlap so the vanes lie like scales
  for (let i = 0; i < N; i++) {
    const phi = i * step;
    // quill
    const B = new THREE.Vector3(rb * Math.cos(phi), yb, rb * Math.sin(phi));
    const T = new THREE.Vector3(rt * Math.cos(phi), yt, rt * Math.sin(phi));
    const dir = T.clone().sub(B);
    const len = dir.length();
    const q = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.055, len, 6), quillMat);
    q.position.copy(B).addScaledVector(dir, 0.5);
    q.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.normalize());
    g.add(q);
    // vane
    const start = positions.length / 3;
    for (let a = 0; a <= SV; a++) {
      const v = a / SV;
      for (let b = 0; b <= SU; b++) {
        const u = b / SU;
        const c = 2 * u - 1;
        const s0 = 0.4;
        const s1 = 1 - 0.075 * c * c;
        const s = s0 + v * (s1 - s0);
        const widen = smooth(clamp(v / 0.32)) * (1 - 0.12 * v);
        const ang = phi + (u - 0.5) * span * widen;
        const r = radius(s) + u * 0.11 + 0.06 * Math.sin(Math.PI * u) * widen;
        positions.push(r * Math.cos(ang), height(s), r * Math.sin(ang));
        uvs.push(u, v);
      }
    }
    for (let a = 0; a < SV; a++) {
      for (let b = 0; b < SU; b++) {
        const p = start + a * (SU + 1) + b;
        index.push(p, p + SU + 1, p + 1, p + 1, p + SU + 1, p + SU + 2);
      }
    }
  }
  const vg = new THREE.BufferGeometry();
  vg.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  vg.setAttribute('uv', new THREE.Float32BufferAttribute(uvs, 2));
  vg.setIndex(index);
  vg.computeVertexNormals();
  g.add(new THREE.Mesh(vg, featherMat));

  // the thread: two rings and a zigzag that ties the quills together
  const threadMat = new THREE.MeshStandardMaterial({ color: C.tube, roughness: 0.5 });
  const sa = 0.17;
  const sb = 0.27;
  [sa, sb].forEach((s) => {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(radius(s) + 0.03, 0.022, 6, 96), threadMat);
    ring.rotation.x = Math.PI / 2;
    ring.position.y = height(s);
    g.add(ring);
  });
  const zig = [];
  for (let i = 0; i < N * 2; i++) {
    const phi = (i * step) / 2;
    const s = i % 2 ? sb : sa;
    const r = radius(s) + 0.04;
    zig.push(new THREE.Vector3(r * Math.cos(phi), height(s), r * Math.sin(phi)));
  }
  const curve = new THREE.CatmullRomCurve3(zig, true, 'catmullrom', 0.1);
  g.add(new THREE.Mesh(new THREE.TubeGeometry(curve, 320, 0.015, 5, true), threadMat));

  // centre the pivot between cork and skirt
  g.children.forEach((m) => (m.position.y -= 2.6));
  return g;
}

// ---------- court lines in world space ----------
// world x = court x - 3.05, world z = court y - 6.7, world y = height

function buildCourt() {
  const v = [];
  const seg = (x1, y1, x2, y2) => v.push(x1 - 3.05, 0, y1 - 6.7, x2 - 3.05, 0, y2 - 6.7);
  seg(0, 0, 6.1, 0);
  seg(0, 13.4, 6.1, 13.4);
  seg(0, 0, 0, 13.4);
  seg(6.1, 0, 6.1, 13.4);
  seg(0.46, 0, 0.46, 13.4);
  seg(5.64, 0, 5.64, 13.4);
  seg(0, 0.76, 6.1, 0.76);
  seg(0, 12.64, 6.1, 12.64);
  seg(0, 4.72, 6.1, 4.72);
  seg(0, 8.68, 6.1, 8.68);
  seg(3.05, 0, 3.05, 4.72);
  seg(3.05, 8.68, 3.05, 13.4);
  // net: posts, top tape and bottom edge
  v.push(-3.1, 0, 0, -3.1, 1.55, 0, 3.1, 0, 0, 3.1, 1.55, 0);
  v.push(-3.1, 1.524, 0, 3.1, 1.524, 0, -3.1, 0.76, 0, 3.1, 0.76, 0);
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(v, 3));
  const mat = new THREE.LineBasicMaterial({ color: C.line, transparent: true, opacity: 0 });
  const lines = new THREE.LineSegments(geo, mat);
  // net mesh: a faint vertical plane
  const net = new THREE.Mesh(
    new THREE.PlaneGeometry(6.2, 0.764),
    new THREE.MeshBasicMaterial({ color: 0x7d8a9a, transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false }),
  );
  net.position.set(0, 1.142, 0);
  const group = new THREE.Group();
  group.add(lines, net);
  return { group, lineMat: mat, netMat: net.material };
}

function ringOnFloor(radius) {
  const pts = [];
  for (let i = 0; i <= 64; i++) {
    const a = (i / 64) * Math.PI * 2;
    pts.push(new THREE.Vector3(Math.cos(a) * radius, 0.002, Math.sin(a) * radius));
  }
  const geo = new THREE.BufferGeometry().setFromPoints(pts);
  return new THREE.Line(geo, new THREE.LineBasicMaterial({ color: C.tube, transparent: true, opacity: 0 }));
}

function shadowSprite() {
  const c = document.createElement('canvas');
  c.width = c.height = 128;
  const g = c.getContext('2d');
  const grd = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  grd.addColorStop(0, 'rgba(18,35,58,0.35)');
  grd.addColorStop(1, 'rgba(18,35,58,0)');
  g.fillStyle = grd;
  g.fillRect(0, 0, 128, 128);
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(1, 1),
    new THREE.MeshBasicMaterial({ map: new THREE.CanvasTexture(c), transparent: true, depthWrite: false, opacity: 0 }),
  );
  m.rotation.x = -Math.PI / 2;
  return m;
}

// ---------- the flight from the data ----------

export function planFlight(best) {
  const { shot, next } = best;
  const f = shot.flight;
  const from = shot.hitter_position;
  let to = null;
  if (next && next.hitter_position) to = next.hitter_position;
  else if (shot.landing && shot.landing.position) to = shot.landing.position;
  if (!to) to = { x: 6.1 - from.x, y: 13.4 - from.y };
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const D = Math.max(1.5, Math.hypot(dx, dy));
  const downward = ['smash', 'drive', 'net_kill', 'push', 'block'].includes(shot.family);
  const h0 = downward ? Math.max(1.2, f.apex_m || 2.4) : 1.1;
  const sol = solveToTarget(f.initial_speed_kmh / 3.6, h0, D, { hEnd: next ? 0.9 : 0.05, apex: f.apex_m });
  const ux = dx / D;
  const uy = dy / D;
  const world = sol.pts.map((p) => ({
    t: p.t,
    v: kmh(p.v),
    pos: new THREE.Vector3(from.x + ux * p.x - 3.05, p.y, from.y + uy * p.x - 6.7),
  }));
  return { world, duration: world[world.length - 1].t, from, to, shot };
}

// ---------- the scene ----------

export function createHero(canvas, flight, { onFrame } = {}) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  scene.fog = new THREE.Fog(C.plume, 22, 48);
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(renderer), 0.04).texture;
  scene.add(new THREE.HemisphereLight(0xffffff, 0xdfe5ec, 0.9));
  const key = new THREE.DirectionalLight(0xffffff, 1.6);
  key.position.set(-3, 6, 4);
  scene.add(key);

  const camera = new THREE.PerspectiveCamera(28, 1, 0.01, 200);

  const shuttle = buildShuttle();
  const holder = new THREE.Group();
  holder.add(shuttle);
  scene.add(holder);

  const court = buildCourt();
  scene.add(court.group);

  const startRing = ringOnFloor(0.35);
  const endRing = ringOnFloor(0.35);
  scene.add(startRing, endRing);
  const shadow = shadowSprite();
  scene.add(shadow);

  // trail and stroboscopic marks every 10 ms of flight
  const pts = flight.world;
  const start = pts[0].pos.clone();
  const end = pts[pts.length - 1].pos.clone();
  startRing.position.set(start.x, 0, start.z);
  endRing.position.set(end.x, 0, end.z);
  const trailGeo = new THREE.BufferGeometry().setFromPoints(pts.map((p) => p.pos));
  const trail = new THREE.Line(trailGeo, new THREE.LineBasicMaterial({ color: C.tube }));
  trail.geometry.setDrawRange(0, 0);
  scene.add(trail);
  const strobe = [];
  const strobeIdx = [];
  for (let t = 0, i = 0; i < pts.length; i++) {
    if (pts[i].t >= t) {
      strobe.push(pts[i].pos);
      strobeIdx.push(i);
      t += 0.01;
    }
  }
  const strobeGeo = new THREE.BufferGeometry().setFromPoints(strobe);
  const strobePts = new THREE.Points(strobeGeo, new THREE.PointsMaterial({ color: C.tube, size: 4.5, sizeAttenuation: false }));
  strobePts.geometry.setDrawRange(0, 0);
  scene.add(strobePts);

  // camera framing
  const mid = start.clone().lerp(end, 0.5);
  mid.y = 1.4;
  const dir0 = new THREE.Vector3(0.28, 0.1, 1).normalize();
  const along = end.clone().sub(start).setY(0).normalize();
  const sideways = new THREE.Vector3(along.z, 0, -along.x);
  if (sideways.x < 0) sideways.negate();
  const dir1 = sideways.clone().multiplyScalar(1).add(new THREE.Vector3(0, 0.42, 0)).normalize();
  let d1 = 18;
  let w = 1;
  let h = 1;
  let narrow = false;

  function resize() {
    const r = canvas.getBoundingClientRect();
    w = Math.max(1, r.width);
    h = Math.max(1, r.height);
    narrow = w < 760;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.fov = narrow ? 40 : 28;
    const hfov = 2 * Math.atan(Math.tan((camera.fov * Math.PI) / 360) * camera.aspect);
    d1 = Math.max(16, (narrow ? 7.6 : 11.5) / Math.tan(hfov / 2));
    scene.fog.near = d1 * 1.2;
    scene.fog.far = d1 * 2.6;
    camera.updateProjectionMatrix();
  }
  resize();
  const ro = new ResizeObserver(resize);
  ro.observe(canvas);

  const up = new THREE.Vector3(0, 1, 0);
  const qFlight = new THREE.Quaternion();
  const qHang = new THREE.Quaternion();
  const tilt = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), 0.12);
  const spinQ = new THREE.Quaternion();
  const tmp = new THREE.Vector3();
  const target = new THREE.Vector3();
  const camDir = new THREE.Vector3();

  const state = { p: 0, spin: 0, last: performance.now(), running: false, still: false };

  function velocityAt(i) {
    const a = pts[Math.max(0, i - 1)].pos;
    const b = pts[Math.min(pts.length - 1, i + 1)].pos;
    return tmp.copy(b).sub(a).normalize();
  }
  qFlight.setFromUnitVectors(up, velocityAt(1).clone().negate());

  function render(now) {
    const dt = Math.min(0.05, (now - state.last) / 1000);
    state.last = now;
    const p = state.p;
    const pull = smooth(clamp((p - 0.06) / 0.32));
    const fl = clamp((p - 0.36) / 0.52);
    const hold = clamp((p - 0.9) / 0.1);

    if (!state.still) state.spin += dt * 0.35 * (1 - pull);
    spinQ.setFromAxisAngle(up, state.spin);
    qHang.copy(tilt).multiply(spinQ);

    // shuttle position, orientation and display scale
    let idx = 0;
    if (fl > 0) {
      const tt = fl * flight.duration;
      while (idx < pts.length - 1 && pts[idx + 1].t <= tt) idx++;
      holder.position.copy(pts[idx].pos);
      holder.quaternion.setFromUnitVectors(up, velocityAt(idx).clone().negate());
    } else {
      holder.position.copy(start);
      holder.quaternion.copy(qHang).slerp(qFlight, smooth(clamp((p - 0.16) / 0.2)));
    }
    const scale = 0.01 * lerp(1, d1 / 3.2, pull);
    shuttle.scale.setScalar(scale);

    // trail, marks, rings, court
    trail.geometry.setDrawRange(0, fl > 0 ? idx + 1 : 0);
    let sCount = 0;
    while (sCount < strobeIdx.length && strobeIdx[sCount] <= idx && fl > 0) sCount++;
    strobePts.geometry.setDrawRange(0, sCount);
    court.lineMat.opacity = 0.85 * pull;
    court.netMat.opacity = 0.06 * pull;
    startRing.material.opacity = pull;
    endRing.material.opacity = hold;
    shadow.position.set(holder.position.x, 0.003, holder.position.z);
    shadow.scale.setScalar(0.6 + holder.position.y * 0.25);
    shadow.material.opacity = 0.5 * pull;

    // camera: log-distance dolly from close-up to the side of the court
    const d0 = narrow ? 0.36 : 0.44;
    const dist = Math.exp(lerp(Math.log(d0), Math.log(d1), pull));
    target.copy(start).lerp(mid, pull);
    camDir.copy(dir0).lerp(dir1, pull).normalize();
    camera.position.copy(target).addScaledVector(camDir, dist);
    camera.lookAt(target);
    // shift the resting shuttle off centre so it sits beside the headline
    if (narrow) camera.setViewOffset(w, h, 0, h * lerp(0.13, 0.06, pull), w, h);
    else camera.setViewOffset(w, h, w * lerp(-0.17, 0.12, pull), h * lerp(-0.04, 0.15, pull), w, h);

    renderer.render(scene, camera);

    const v = fl > 0 ? pts[idx].v : 0;
    const rise = clamp((p - 0.28) / 0.08);
    onFrame && onFrame({ p, pull, fl, hold, speed: fl > 0 ? v : pts[0].v * smooth(rise), t: fl > 0 ? pts[idx].t : 0 });
  }

  function loop(now) {
    if (!state.running) return;
    render(now);
    requestAnimationFrame(loop);
  }

  return {
    setProgress(p) {
      state.p = clamp(p);
      if (!state.running) render(performance.now());
    },
    get progress() {
      return state.p;
    },
    setStill(still) {
      state.still = still;
    },
    start() {
      if (state.running) return;
      state.running = true;
      state.last = performance.now();
      requestAnimationFrame(loop);
    },
    stop() {
      state.running = false;
    },
    renderOnce() {
      render(performance.now());
    },
    dispose() {
      state.running = false;
      ro.disconnect();
      renderer.dispose();
      pmrem.dispose();
    },
  };
}
