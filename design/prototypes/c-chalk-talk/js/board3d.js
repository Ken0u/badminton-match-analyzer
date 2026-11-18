// The landing page's magnetic tactics board (Three.js).
// Pucks follow the real 10 Hz feet tracks of a rally from the doubles match;
// a marker stroke draws itself for each shot (hitter to the next contact, the
// last one to its landing), then a ring for a winner or a cross for an error.

import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js';
import { positionAt, lastKnownPosition, shotLabel, initials, firstName } from './data.js';

const BW = 16; // board face, along X (court length)
const BD = 10; // board face, along Z (court width)
const TOP = 0.21; // board face height
const PRINT_PPU = 128;
const INK_PPU = 96;
const COL = {
  T1: '#1F57C3',
  T2: '#D3362D',
  ink: '#22262E',
  court: '#2E7D57',
  courtFill: '#E2EEE5',
  board: '#F6F8F6',
};

// court metres -> board X/Z (far end on the left, the camera's left sideline toward the viewer)
const toBoard = (p) => ({ X: p.y - 6.7, Z: 3.05 - p.x });

export async function createBoard(host, { analysis, names, reduced }) {
  await Promise.all([
    document.fonts.load('700 40px "Barlow Condensed"'),
    document.fonts.load('600 40px "Barlow Condensed"'),
    document.fonts.load('700 40px "Kalam"'),
    document.fonts.load('500 40px "Barlow"'),
  ]).catch(() => {});

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
  renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 1.75));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  host.appendChild(renderer.domElement);
  renderer.domElement.setAttribute('aria-hidden', 'true');

  const scene = new THREE.Scene();
  const pmrem = new THREE.PMREMGenerator(renderer);
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;

  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);

  scene.add(new THREE.HemisphereLight(0xffffff, 0x24443a, 0.9));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(-5, 16, 7);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -12, right: 12, top: 12, bottom: -12, near: 1, far: 40 });
  sun.shadow.bias = -0.0004;
  sun.shadow.radius = 4;
  scene.add(sun);

  const world = new THREE.Group();
  scene.add(world);

  // ---- board -------------------------------------------------------------
  const frame = new THREE.Mesh(
    new RoundedBoxGeometry(BW + 0.6, 0.4, BD + 0.6, 4, 0.12),
    new THREE.MeshStandardMaterial({ color: 0xc3c9cf, metalness: 0.85, roughness: 0.32, envMapIntensity: 0.9 })
  );
  frame.position.y = 0;
  frame.castShadow = true;
  frame.receiveShadow = true;
  world.add(frame);

  const printCanvas = drawPrint();
  const printTex = new THREE.CanvasTexture(printCanvas);
  printTex.colorSpace = THREE.SRGBColorSpace;
  printTex.anisotropy = 8;
  const face = new THREE.Mesh(
    new THREE.PlaneGeometry(BW, BD),
    new THREE.MeshStandardMaterial({ map: printTex, roughness: 0.42, metalness: 0, envMapIntensity: 0.35 })
  );
  face.rotation.x = -Math.PI / 2;
  face.position.y = TOP;
  face.receiveShadow = true;
  world.add(face);

  const inkCanvas = document.createElement('canvas');
  inkCanvas.width = BW * INK_PPU;
  inkCanvas.height = BD * INK_PPU;
  const ink = inkCanvas.getContext('2d');
  const inkTex = new THREE.CanvasTexture(inkCanvas);
  inkTex.colorSpace = THREE.SRGBColorSpace;
  inkTex.anisotropy = 8;
  const inkPlane = new THREE.Mesh(
    new THREE.PlaneGeometry(BW, BD),
    new THREE.MeshStandardMaterial({ map: inkTex, transparent: true, roughness: 0.3, envMapIntensity: 0.3, depthWrite: false })
  );
  inkPlane.rotation.x = -Math.PI / 2;
  inkPlane.position.y = TOP + 0.003;
  inkPlane.receiveShadow = true;
  world.add(inkPlane);

  // soft contact shadow on the backdrop
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(60, 60), new THREE.ShadowMaterial({ opacity: 0.32 }));
  ground.rotation.x = -Math.PI / 2;
  ground.position.y = -0.21;
  ground.receiveShadow = true;
  world.add(ground);

  // marker tray along the near edge, three markers and an eraser
  const trayMat = new THREE.MeshStandardMaterial({ color: 0xb9bfc5, metalness: 0.8, roughness: 0.35 });
  const tray = new THREE.Mesh(new RoundedBoxGeometry(9, 0.22, 0.7, 3, 0.06), trayMat);
  tray.position.set(1.2, -0.02, BD / 2 + 0.62);
  tray.castShadow = tray.receiveShadow = true;
  world.add(tray);
  const markers = [COL.T1, COL.T2, COL.ink].map((c, i) => {
    const g = new THREE.Group();
    const body = new THREE.Mesh(
      new THREE.CylinderGeometry(0.12, 0.12, 1.35, 24),
      new THREE.MeshStandardMaterial({ color: 0xf2f3f1, roughness: 0.4 })
    );
    const capM = new THREE.MeshStandardMaterial({ color: c, roughness: 0.35 });
    const capA = new THREE.Mesh(new THREE.CylinderGeometry(0.135, 0.135, 0.45, 24), capM);
    capA.position.y = 0.72;
    const capB = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.12, 0.12, 24), capM);
    capB.position.y = -0.73;
    const band = new THREE.Mesh(new THREE.CylinderGeometry(0.122, 0.122, 0.3, 24), capM);
    band.position.y = 0.1;
    g.add(body, capA, capB, band);
    g.rotation.z = Math.PI / 2;
    g.rotation.y = (i - 1) * 0.06;
    g.position.set(-1.6 + i * 1.7, 0.2, BD / 2 + 0.62 + (i - 1) * 0.04);
    g.traverse((m) => m.isMesh && (m.castShadow = true));
    world.add(g);
    return g;
  });
  const eraser = new THREE.Group();
  {
    const top = new THREE.Mesh(new RoundedBoxGeometry(0.7, 0.32, 3.1, 3, 0.08), new THREE.MeshStandardMaterial({ color: 0x2c3138, roughness: 0.55 }));
    top.position.y = 0.2;
    const felt = new THREE.Mesh(new THREE.BoxGeometry(0.66, 0.08, 3.04), new THREE.MeshStandardMaterial({ color: 0xd8d4c8, roughness: 1 }));
    felt.position.y = 0.04;
    const grip = new THREE.Mesh(new RoundedBoxGeometry(0.42, 0.18, 2.3, 3, 0.08), new THREE.MeshStandardMaterial({ color: COL.T1, roughness: 0.5 }));
    grip.position.y = 0.42;
    eraser.add(top, felt, grip);
    eraser.traverse((m) => m.isMesh && (m.castShadow = true));
  }
  const eraserRest = new THREE.Vector3(6.6, 0.0, BD / 2 + 0.62);
  eraser.position.copy(eraserRest);
  eraser.rotation.y = Math.PI / 2;
  world.add(eraser);

  // ---- pucks -------------------------------------------------------------
  const puckProfile = [
    [0, 0],
    [0.4, 0],
    [0.43, 0.03],
    [0.43, 0.12],
    [0.4, 0.16],
    [0.0, 0.16],
  ].map(([x, y]) => new THREE.Vector2(x, y));
  const puckGeo = new THREE.LatheGeometry(puckProfile, 48);
  const pucks = new Map();
  for (const p of analysis.players) {
    const g = new THREE.Group();
    const color = COL[p.team] || COL.ink;
    const body = new THREE.Mesh(puckGeo, new THREE.MeshStandardMaterial({ color, roughness: 0.28, metalness: 0.05, envMapIntensity: 0.8 }));
    body.castShadow = true;
    g.add(body);
    const decal = new THREE.Mesh(
      new THREE.CircleGeometry(0.34, 40),
      new THREE.MeshStandardMaterial({ map: textTexture(initials(names[p.id]), 'disc', color), transparent: true, roughness: 0.3 })
    );
    decal.rotation.x = -Math.PI / 2;
    decal.position.y = 0.162;
    g.add(decal);
    const tagTex = textTexture(names[p.id], 'tag', color);
    const tag = new THREE.Mesh(
      new THREE.PlaneGeometry(2.1, 0.56),
      new THREE.MeshStandardMaterial({ map: tagTex, transparent: true, roughness: 0.6, depthWrite: false })
    );
    tag.rotation.x = -Math.PI / 2;
    tag.position.set(0, 0.006, 0.78);
    tag.receiveShadow = true;
    g.add(tag);
    g.position.set(0, TOP, 0);
    g.userData = { tag, team: p.team };
    world.add(g);
    pucks.set(p.id, g);
  }

  // ---- rally replay data -------------------------------------------------
  const teamOf = Object.fromEntries(analysis.players.map((p) => [p.id, p.team]));
  const rallies = analysis.rallies
    .filter((r) => {
      const last = r.shots[r.shots.length - 1];
      return (
        r.outcome &&
        r.outcome.reason &&
        last &&
        last.landing &&
        last.landing.position &&
        r.shots.length >= 6 &&
        r.shots.length <= 16 &&
        r.end_s - r.start_s < 14 &&
        r.shots.filter((s) => s.hitter_position).length >= r.shots.length - 1
      );
    })
    .sort((a, b) => (a.id === 'rally-6' ? -1 : b.id === 'rally-6' ? 1 : 0));
  let rallyIdx = 0;

  function strokesFor(r) {
    const out = [];
    r.shots.forEach((s, i) => {
      const next = r.shots[i + 1];
      const from = s.hitter_position;
      const last = !next;
      const to = last ? s.landing && s.landing.position : next.hitter_position;
      if (!from || !to) return;
      const t1 = last ? s.landing.time_s : next.time_s;
      out.push({
        t0: s.time_s,
        dur: Math.max(0.22, Math.min(0.85, (t1 - s.time_s) * 0.9)),
        from: toBoard(from),
        to: toBoard(to),
        color: COL[teamOf[s.hitter_id]] || COL.ink,
        label: shotLabel(s),
        bow: (i % 2 ? 1 : -1) * 0.1,
        last,
        landT: last ? s.landing.time_s : null,
      });
    });
    return out;
  }

  // ---- state -------------------------------------------------------------
  let progress = 0; // 0 = hero tilt, 1 = flat
  let portrait = false;
  let running = !reduced;
  let visible = true;
  let raf = 0;
  let clockStart = performance.now();
  let pointer = { x: 0, y: 0, sx: 0, sy: 0 };
  let current = null; // {rally, strokes, tStart, tEnd, hold}
  let anim = null;

  function startRally(i) {
    const r = rallies[i % rallies.length];
    current = {
      rally: r,
      strokes: strokesFor(r),
      tStart: r.start_s - 0.7,
      tEnd: r.end_s + 0.6,
    };
    clockStart = performance.now();
    eraser.position.copy(eraserRest);
    eraser.rotation.y = Math.PI / 2;
  }

  function ends(r) {
    // which end each team plays at, from the opening contact
    const s = r.shots[0];
    const sum = { T1: [], T2: [] };
    for (const pl of s.players || []) {
      const tm = teamOf[pl.person_id];
      if (tm && pl.position) sum[tm].push(pl.position.y);
    }
    const mean = (a) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : null);
    const t1 = mean(sum.T1);
    return t1 == null ? { far: 'T2', near: 'T1' } : t1 < 6.7 ? { far: 'T1', near: 'T2' } : { far: 'T2', near: 'T1' };
  }

  function teamLabel(team) {
    const all = analysis.players.map((p) => firstName(names[p.id]));
    const unique = new Set(all).size === all.length;
    return analysis.players
      .filter((p) => p.team === team)
      .map((p) => (unique ? firstName(names[p.id]) : names[p.id]))
      .join(' & ');
  }

  // ---- ink drawing -------------------------------------------------------
  const cx = (X) => (X + BW / 2) * INK_PPU;
  const cz = (Z) => (Z + BD / 2) * INK_PPU;

  function drawInk(t, wipe) {
    ink.clearRect(0, 0, inkCanvas.width, inkCanvas.height);
    if (!current) return;
    const r = current.rally;
    ink.lineCap = 'round';
    ink.lineJoin = 'round';

    // headline in the top margin
    const e = ends(r);
    ink.globalAlpha = 0.92;
    ink.fillStyle = COL.ink;
    ink.font = `700 ${0.5 * INK_PPU}px Kalam`;
    ink.textBaseline = 'middle';
    const shotsSoFar = r.shots.filter((s) => s.time_s <= t).length;
    ink.fillText(`Rally ${r.id.split('-')[1]}`, cx(-7.3), cz(-4.25));
    ink.font = `400 ${0.36 * INK_PPU}px Kalam`;
    ink.fillText(`${shotsSoFar} ${shotsSoFar === 1 ? 'shot' : 'shots'}`, cx(-5.15), cz(-4.22));
    // team names at each end, bottom margin
    ink.font = `700 ${0.38 * INK_PPU}px Kalam`;
    ink.fillStyle = COL[e.far];
    ink.textAlign = 'left';
    ink.fillText(teamLabel(e.far), cx(-6.7), cz(4.3));
    ink.fillStyle = COL[e.near];
    ink.textAlign = 'right';
    ink.fillText(teamLabel(e.near), cx(6.7), cz(4.3));
    ink.textAlign = 'left';

    const started = current.strokes.filter((s) => t >= s.t0);
    started.forEach((s, idx) => {
      const age = started.length - 1 - idx; // 0 = the newest stroke
      const k = Math.min(1, (t - s.t0) / s.dur);
      drawStroke(s, easeOut(k), age);
      if (s.last && t >= s.landT) {
        const kk = Math.min(1, (t - s.landT) / 0.45);
        drawFinish(s, r.outcome, easeOut(kk));
      }
    });

    if (wipe) {
      ink.save();
      ink.globalCompositeOperation = 'destination-out';
      ink.fillStyle = '#000';
      for (const rect of wipe) ink.fillRect(rect.x, rect.y, rect.w, rect.h);
      ink.restore();
    }
    ink.globalAlpha = 1;
  }

  function drawStroke(s, k, age = 0) {
    const x1 = cx(s.from.X);
    const y1 = cz(s.from.Z);
    const x2 = cx(s.to.X);
    const y2 = cz(s.to.Z);
    const dx = x2 - x1;
    const dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const mx = (x1 + x2) / 2 + (-dy / len) * len * s.bow;
    const my = (y1 + y2) / 2 + (dx / len) * len * s.bow;
    ink.strokeStyle = s.color;
    const fade = age < 3 ? 0.88 : 0.3;
    ink.globalAlpha = fade;
    ink.lineWidth = (age < 3 ? 0.08 : 0.06) * INK_PPU;
    ink.beginPath();
    ink.moveTo(x1, y1);
    const N = 28;
    let px = x1;
    let py = y1;
    let qx = x1;
    let qy = y1;
    for (let i = 1; i <= Math.ceil(N * k); i++) {
      const u = Math.min(k, i / N);
      const a = (1 - u) * (1 - u);
      const b = 2 * (1 - u) * u;
      const c = u * u;
      qx = px;
      qy = py;
      px = a * x1 + b * mx + c * x2;
      py = a * y1 + b * my + c * y2;
      ink.lineTo(px, py);
    }
    ink.stroke();
    // label at the start of the stroke
    if (k > 0.15 && s.label && age < 2 && len > 0.8 * INK_PPU) {
      ink.globalAlpha = (age ? 0.55 : 0.95) * Math.min(1, (k - 0.15) * 4);
      ink.fillStyle = s.color;
      ink.font = `700 ${0.4 * INK_PPU}px Kalam`;
      ink.textBaseline = 'middle';
      const lx = x1 + (mx - x1) * 0.42;
      const ly = y1 + (my - y1) * 0.42 + (s.bow > 0 ? 0.22 : -0.22) * INK_PPU;
      ink.fillText(s.label, lx, ly);
    }
    if (k >= 0.999 && !s.last) {
      const tx = x2 - mx;
      const ty = y2 - my;
      const tl = Math.hypot(tx, ty) || 1;
      const ux = tx / tl;
      const uy = ty / tl;
      const h = 0.26 * INK_PPU;
      ink.globalAlpha = fade;
      ink.beginPath();
      ink.moveTo(x2 - ux * h - uy * h * 0.55, y2 - uy * h + ux * h * 0.55);
      ink.lineTo(x2, y2);
      ink.lineTo(x2 - ux * h + uy * h * 0.55, y2 - uy * h - ux * h * 0.55);
      ink.stroke();
    }
    void qx;
    void qy;
  }

  function drawFinish(s, outcome, k) {
    const x = cx(s.to.X);
    const y = cz(s.to.Z);
    const R = 0.42 * INK_PPU;
    ink.strokeStyle = s.color;
    ink.lineWidth = 0.09 * INK_PPU;
    ink.globalAlpha = 0.92;
    const winner = outcome.reason === 'winner';
    if (winner) {
      ink.beginPath();
      const turns = 1.12 * k;
      for (let i = 0; i <= 40 * turns; i++) {
        const a = -0.6 + (i / 40) * Math.PI * 2;
        const rr = R * (1 + i * 0.002);
        const px = x + Math.cos(a) * rr;
        const py = y + Math.sin(a) * rr * 0.96;
        i ? ink.lineTo(px, py) : ink.moveTo(px, py);
      }
      ink.stroke();
    } else {
      const sz = R * 0.85;
      const k1 = Math.min(1, k * 2);
      const k2 = Math.max(0, k * 2 - 1);
      ink.beginPath();
      ink.moveTo(x - sz, y - sz);
      ink.lineTo(x - sz + 2 * sz * k1, y - sz + 2 * sz * k1);
      if (k2 > 0) {
        ink.moveTo(x + sz, y - sz);
        ink.lineTo(x + sz - 2 * sz * k2, y - sz + 2 * sz * k2);
      }
      ink.stroke();
    }
    if (k > 0.6) {
      ink.globalAlpha = 0.92 * Math.min(1, (k - 0.6) * 3);
      ink.fillStyle = s.color;
      ink.font = `700 ${0.36 * INK_PPU}px Kalam`;
      ink.textBaseline = 'middle';
      const txt = winner ? 'winner!' : outcome.detail === 'net' ? 'into the net' : outcome.detail === 'out' ? 'out' : 'error';
      const right = s.to.X < 5;
      ink.textAlign = right ? 'left' : 'right';
      ink.fillText(txt, x + (right ? 1 : -1) * (R + 0.15 * INK_PPU), y - 0.05 * INK_PPU);
      ink.textAlign = 'left';
    }
  }

  // ---- loop --------------------------------------------------------------
  function updatePucks(t) {
    for (const [pid, g] of pucks) {
      const pos = positionAt(analysis, pid, t) || lastKnownPosition(analysis, pid, t, 3);
      if (!pos) continue;
      const b = toBoard(pos);
      g.position.x = b.X;
      g.position.z = b.Z;
    }
  }

  function wipeRects(u) {
    // three lanes, the eraser sweeping left to right then back
    const lanes = 3;
    const laneH = BD / lanes;
    const lane = Math.min(lanes - 1, Math.floor(u * lanes));
    const lu = u * lanes - lane;
    const dir = lane % 2 ? -1 : 1;
    const x = dir > 0 ? -BW / 2 - 0.5 + lu * (BW + 1) : BW / 2 + 0.5 - lu * (BW + 1);
    const z = -BD / 2 + laneH * (lane + 0.5);
    eraser.position.set(x, TOP - 0.02, z);
    eraser.rotation.y = 0;
    const rects = [];
    for (let i = 0; i < lane; i++) rects.push({ x: 0, y: cz(-BD / 2 + laneH * i), w: inkCanvas.width, h: laneH * INK_PPU + 2 });
    const y0 = cz(-BD / 2 + laneH * lane);
    if (dir > 0) rects.push({ x: 0, y: y0, w: cx(x), h: laneH * INK_PPU + 2 });
    else rects.push({ x: cx(x), y: y0, w: inkCanvas.width, h: laneH * INK_PPU + 2 });
    return rects;
  }

  let lastInkKey = '';
  function tick(now) {
    raf = 0;
    smoother();
    if (!current) startRally(rallyIdx);
    const elapsed = (now - clockStart) / 1000;
    const span = current.tEnd - current.tStart;
    const HOLD = 3.2;
    const WIPE = 2.1;
    let t = current.tStart + elapsed;
    let wipe = null;
    if (elapsed > span + HOLD) {
      const u = Math.min(1, (elapsed - span - HOLD) / WIPE);
      wipe = wipeRects(u);
      t = current.tEnd;
      if (u >= 1) {
        rallyIdx++;
        startRally(rallyIdx);
        t = current.tStart;
        wipe = null;
      }
    } else if (elapsed > span) {
      t = current.tEnd;
      // lift the eraser off the tray just before wiping
    }
    updatePucks(Math.min(t, current.rally.end_s + 0.4));
    const key = `${current.rally.id}|${t.toFixed(2)}|${wipe ? eraser.position.x.toFixed(2) + eraser.position.z.toFixed(1) : ''}`;
    if (key !== lastInkKey) {
      drawInk(t, wipe);
      inkTex.needsUpdate = true;
      lastInkKey = key;
    }
    if (!wipe && elapsed <= span + HOLD) {
      eraser.position.copy(eraserRest);
      eraser.rotation.y = Math.PI / 2;
    }
    render(now);
    if (running && visible) raf = requestAnimationFrame(tick);
  }

  // ---- camera ------------------------------------------------------------
  const eyeA = new THREE.Vector3();
  const tgtA = new THREE.Vector3();
  const qA = new THREE.Quaternion();
  const qB = new THREE.Quaternion();
  const m4 = new THREE.Matrix4();

  function layout() {
    const w = host.clientWidth || 1;
    const h = host.clientHeight || 1;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    portrait = w / h < 0.9;
    camera.updateProjectionMatrix();
  }

  function render() {
    const p = ease(progress);
    const aspect = camera.aspect;
    const vfov = (camera.fov * Math.PI) / 180;
    const tan = Math.tan(vfov / 2);
    // flat: fit the board (with frame and tray) to the viewport
    const bw = BW + 1.0;
    const bd = BD + 2.4;
    const distFlat = Math.max(bd / 2 / tan, bw / 2 / (tan * aspect)) * 1.1;
    // leave room under the board for the caption
    const lift = portrait ? 0 : 1.3;
    const eyeFlat = new THREE.Vector3(0, distFlat, 0.55 - lift);
    const tgtFlat = new THREE.Vector3(0, 0, 0.55 - lift);
    // hero: low three-quarter view
    const px = pointer.sx * (1 - p);
    const py = pointer.sy * (1 - p);
    let eyeHero;
    let tgtHero;
    if (portrait) {
      // phone: the board sits below the headline, seen from the front and above
      const d = 22 / Math.max(aspect, 0.4);
      eyeHero = new THREE.Vector3(1.5 + px * 1.5, d * 0.62 + py, d * 0.72);
      tgtHero = new THREE.Vector3(0.6, 0, -6.5);
    } else {
      // keep the board clear of the headline column on any landscape shape
      const k = Math.max(0, 1.75 - aspect);
      const d = 23 * (1 + k * 0.75);
      const shift = -5.9 - k * 8;
      eyeHero = new THREE.Vector3(shift - 0.6 + px * 2.2, d * 0.58 + py * 1.2, d * 0.8);
      tgtHero = new THREE.Vector3(shift, -0.6, 1.4);
    }
    eyeA.lerpVectors(eyeHero, eyeFlat, p);
    tgtA.lerpVectors(tgtHero, tgtFlat, p);
    m4.lookAt(eyeHero, tgtHero, new THREE.Vector3(0, 1, 0));
    qA.setFromRotationMatrix(m4);
    m4.lookAt(eyeFlat, tgtFlat, new THREE.Vector3(0, 0, -1));
    qB.setFromRotationMatrix(m4);
    camera.position.copy(eyeA);
    camera.quaternion.slerpQuaternions(qA, qB, p);
    // a gentle roll in the hero pose so the board reads as lying on a bench
    if (p < 1) camera.rotateZ(0.06 * (1 - p) * (portrait ? 0 : 1));
    // tags fade slightly when the board lies flat (more room for strokes)
    renderer.render(scene, camera);
  }

  // ---- public ------------------------------------------------------------
  const ro = new ResizeObserver(() => {
    layout();
    if (!running || !visible) requestRender();
  });
  ro.observe(host);
  layout();

  const io = new IntersectionObserver(([e]) => {
    visible = e.isIntersecting;
    if (visible) kick();
  });
  io.observe(host);
  const onVis = () => {
    visible = document.visibilityState === 'visible';
    if (visible) kick();
  };
  document.addEventListener('visibilitychange', onVis);

  const onPointer = (e) => {
    pointer.x = (e.clientX / innerWidth) * 2 - 1;
    pointer.y = (e.clientY / innerHeight) * 2 - 1;
  };
  if (!reduced) addEventListener('pointermove', onPointer, { passive: true });
  // smooth the pointer inside the loop
  function smoother() {
    pointer.sx += (pointer.x - pointer.sx) * 0.05;
    pointer.sy += (pointer.y - pointer.sy) * 0.05;
  }

  function kick() {
    if (!raf && running && visible) {
      raf = requestAnimationFrame(tick);
    }
  }

  function requestRender() {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      render();
    });
  }

  if (reduced) {
    // hold still: the first rally fully drawn, pucks at its last contact
    startRally(0);
    const r = current.rally;
    updatePucks(r.shots[r.shots.length - 1].time_s);
    drawInk(r.end_s + 5, null);
    inkTex.needsUpdate = true;
    requestRender();
  } else {
    startRally(0);
    kick();
  }

  return {
    setProgress(v) {
      progress = Math.max(0, Math.min(1, v));
      if (!running || !visible) requestRender();
    },
    get progress() {
      return progress;
    },
    animateTo(target, ms = 900) {
      if (anim) cancelAnimationFrame(anim);
      if (reduced) {
        progress = target;
        requestRender();
        return Promise.resolve();
      }
      const from = progress;
      const t0 = performance.now();
      return new Promise((res) => {
        const step = (n) => {
          const u = Math.min(1, (n - t0) / ms);
          progress = from + (target - from) * u;
          if (!running || !visible) render();
          if (u < 1) anim = requestAnimationFrame(step);
          else {
            anim = null;
            res();
          }
        };
        anim = requestAnimationFrame(step);
      });
    },
    dispose() {
      running = false;
      cancelAnimationFrame(raf);
      if (anim) cancelAnimationFrame(anim);
      ro.disconnect();
      io.disconnect();
      document.removeEventListener('visibilitychange', onVis);
      removeEventListener('pointermove', onPointer);
      renderer.dispose();
      pmrem.dispose();
      renderer.domElement.remove();
      scene.traverse((o) => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) {
          if (o.material.map) o.material.map.dispose();
          o.material.dispose();
        }
      });
    },
  };
}

function ease(x) {
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}
function easeOut(x) {
  return 1 - Math.pow(1 - x, 2.2);
}

// The printed board: white melamine, faint ghosting of old marker, a printed court.
function drawPrint() {
  const c = document.createElement('canvas');
  c.width = BW * PRINT_PPU;
  c.height = BD * PRINT_PPU;
  const g = c.getContext('2d');
  const P = PRINT_PPU;
  g.fillStyle = COL.board;
  g.fillRect(0, 0, c.width, c.height);
  // ghosting: a few erased strokes
  g.lineCap = 'round';
  for (let i = 0; i < 26; i++) {
    const s = Math.sin(i * 12.9898) * 43758.5453;
    const r = s - Math.floor(s);
    const r2 = (Math.sin(i * 78.233) * 12345.678) % 1;
    g.strokeStyle = i % 3 ? 'rgba(31,87,195,0.025)' : 'rgba(34,38,46,0.03)';
    g.lineWidth = (0.08 + r * 0.25) * P;
    g.beginPath();
    const x = r * c.width;
    const y = Math.abs(r2) * c.height;
    g.moveTo(x, y);
    g.quadraticCurveTo(x + 2 * P, y - P * r, x + (1 + r * 3) * P, y + P * (r - 0.5) * 2);
    g.stroke();
  }
  const X = (cy) => (cy - 6.7 + BW / 2) * P; // court length -> canvas x
  const Y = (cx) => (3.05 - cx + BD / 2) * P; // court width -> canvas y
  // court fill
  g.fillStyle = COL.courtFill;
  g.fillRect(X(0), Y(6.1), 13.4 * P, 6.1 * P);
  g.strokeStyle = COL.court;
  g.lineWidth = 0.055 * P;
  g.lineCap = 'butt';
  const line = (x1, y1, x2, y2) => {
    g.beginPath();
    g.moveTo(X(y1), Y(x1));
    g.lineTo(X(y2), Y(x2));
    g.stroke();
  };
  // outer doubles lines
  g.strokeRect(X(0), Y(6.1), 13.4 * P, 6.1 * P);
  // singles sidelines
  line(0.46, 0, 0.46, 13.4);
  line(5.64, 0, 5.64, 13.4);
  // short service lines, doubles long service lines
  for (const y of [4.72, 8.68, 0.76, 12.64]) line(0, y, 6.1, y);
  // centre lines
  line(3.05, 0, 3.05, 4.72);
  line(3.05, 8.68, 3.05, 13.4);
  // net
  g.strokeStyle = COL.ink;
  g.lineWidth = 0.08 * P;
  line(-0.25, 6.7, 6.35, 6.7);
  g.fillStyle = COL.ink;
  for (const x of [-0.25, 6.35]) {
    g.beginPath();
    g.arc(X(6.7), Y(x), 0.11 * P, 0, Math.PI * 2);
    g.fill();
  }
  // small printed marks in the margin
  g.fillStyle = 'rgba(46,125,87,0.75)';
  g.font = `600 ${0.26 * P}px "Barlow Condensed"`;
  g.textBaseline = 'middle';
  g.textAlign = 'right';
  g.fillText('Chalk talk tactics board', c.width - 0.55 * P, 0.55 * P);
  g.textAlign = 'left';
  g.font = `500 ${0.2 * P}px Barlow`;
  g.save();
  g.translate(0.5 * P, c.height / 2);
  g.rotate(-Math.PI / 2);
  g.textAlign = 'center';
  g.fillText('far end', 0, 0);
  g.restore();
  g.save();
  g.translate(c.width - 0.5 * P, c.height / 2);
  g.rotate(Math.PI / 2);
  g.textAlign = 'center';
  g.fillText('near end', 0, 0);
  g.restore();
  return c;
}

function textTexture(text, kind, color) {
  const c = document.createElement('canvas');
  if (kind === 'disc') {
    c.width = c.height = 256;
    const g = c.getContext('2d');
    g.fillStyle = color;
    g.beginPath();
    g.arc(128, 128, 126, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.35)';
    g.lineWidth = 6;
    g.beginPath();
    g.arc(128, 128, 112, 0, Math.PI * 2);
    g.stroke();
    g.fillStyle = '#fff';
    g.font = '700 120px "Barlow Condensed"';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, 128, 136);
  } else {
    c.width = 512;
    c.height = 144;
    const g = c.getContext('2d');
    g.fillStyle = 'rgba(255,255,255,0.96)';
    roundRect(g, 6, 18, 500, 108, 18);
    g.fill();
    g.fillStyle = color;
    g.fillRect(6 + 18, 18, 10, 108);
    g.fillStyle = '#22262E';
    g.font = '700 70px Kalam';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    g.fillText(text, 270, 80, 450);
  }
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return t;
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}
