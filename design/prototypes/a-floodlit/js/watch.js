// Watch: the real video with an overlay drawn like court lines and light.
import {
  asset, nameOf, firstName, teamOf, teamName, teamPlayers, sideNumber, shotLabel, labelText, speedOf, clock,
  applyH, viewAt, positionAt, rallyEnd, rallyNumber, getState, setState, esc,
} from './data.js';
import { courtLines, courtSegments } from './court.js';

export function renderWatch(root, match, { toast }) {
  const A = match.analysis;
  const { fps, width: VW, height: VH, duration_s: DUR } = A.video;
  const rallies = A.rallies;
  const people = A.players;
  const swaps = getState().swaps || {};

  root.innerHTML = `
  <div class="watch">
    <div class="watch-main">
      <div class="screen" id="screen">
        <video id="video" src="${asset('video.mp4')}" poster="${new URLSearchParams(location.search).get('still') || asset('poster.jpg')}" preload="metadata" playsinline></video>
        <svg class="ov" id="ov" viewBox="0 0 ${VW} ${VH}" aria-hidden="true">
          <defs>
            <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stop-color="#ffe6b0" stop-opacity="0"/>
              <stop offset="1" stop-color="#ffe6b0" stop-opacity="0.32"/>
            </linearGradient>
            <radialGradient id="pool"><stop offset="0" stop-color="#ffe6b0" stop-opacity="0.45"/><stop offset="1" stop-color="#ffe6b0" stop-opacity="0"/></radialGradient>
          </defs>
          <g id="ov-lines" class="ov-lines"></g>
          <g id="ov-land" class="ov-land"></g>
          <g id="ov-hit" class="ov-hit"></g>
        </svg>
        <button class="bigplay" id="bigplay" aria-label="Play">
          <svg viewBox="0 0 40 40" aria-hidden="true"><path d="M14 10 L31 20 L14 30 Z"/></svg>
        </button>
      </div>
      <div class="hud" id="hud">
        <div class="hud-cell hud-stroke"><span class="hud-k">Last stroke</span><span class="hud-v" id="h-stroke">–</span><span class="hud-s" id="h-who"></span></div>
        <div class="hud-cell hud-speed" id="h-speed-cell"><span class="hud-k">Shot speed, approx.</span><span class="hud-v" id="h-speed">–</span><span class="hud-s" id="h-speed-note"></span></div>
        <div class="hud-cell hud-rally"><span class="hud-k" id="h-rally-k">Rally</span><span class="hud-v"><span id="h-shots">–</span><small> shots</small></span><span class="hud-s" id="h-time"></span></div>
        <div class="hud-cell hud-won">
          <span class="hud-k">Rallies won so far</span>
          <span class="hud-v hud-score"><b class="t1" id="h-w1">0</b><i aria-hidden="true"></i><b class="t2" id="h-w2">0</b></span>
          <span class="hud-s">${esc(teamName(match, 'T1'))} v ${esc(teamName(match, 'T2'))}</span>
        </div>
        <div class="hud-mini" id="mini" aria-label="Positions from above"></div>
      </div>
      <div class="transport">
        <button class="tbtn" id="play" aria-label="Play"><svg viewBox="0 0 20 20" aria-hidden="true"><path id="play-icon" d="M6 4 L16 10 L6 16 Z"/></svg></button>
        <button class="tbtn" id="prev" aria-label="Previous rally"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M5 4v12M16 4 L7 10 L16 16 Z"/></svg></button>
        <button class="tbtn" id="next" aria-label="Next rally"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M15 4v12M4 4 L13 10 L4 16 Z"/></svg></button>
        <span class="tclock"><span id="cur">0:00</span> / ${clock(DUR)}</span>
        <label class="ttoggle"><input type="checkbox" id="lines-toggle" checked> Court lines</label>
      </div>
      <div class="timeline" id="timeline">
        <div class="tl-rallies" aria-hidden="true">${rallies.map((r) => {
          const w = r.outcome?.winner_team;
          return `<span class="tl-r ${w ? `w-${w}` : 'w-none'} ${r.outcome?.reason === 'error' ? 'err' : ''}" style="left:${(r.start_s / DUR) * 100}%;width:${Math.max(((rallyEnd(r) - r.start_s) / DUR) * 100, 0.35)}%"></span>`;
        }).join('')}</div>
        <div class="tl-head" id="tl-head"></div>
        <input type="range" id="scrub" min="0" max="${DUR}" step="0.04" value="0" aria-label="Position in the video">
      </div>
      <p class="kbd-hint">Space plays and pauses. Arrow keys skip 5 seconds. [ and ] jump between rallies.</p>
    </div>
    <aside class="rallies" aria-labelledby="rl-title">
      <h2 id="rl-title" class="rallies-title">Rallies</h2>
      <ol class="rl" id="rl">${rallies.map((r) => rallyItem(r)).join('')}</ol>
    </aside>
  </div>`;

  function resultSentence(r) {
    const o = r.outcome;
    const last = r.shots[r.shots.length - 1];
    if (!o || !o.winner_team) return 'Result unknown';
    const who = last?.hitter_id ? nameOf(match, last.hitter_id) : 'the last hitter';
    const stroke = last ? labelText(shotLabel(last)).toLowerCase() : 'shot';
    const team = teamName(match, o.winner_team);
    if (o.reason === 'winner') return `${team} won it with ${who}'s ${stroke}`;
    if (o.detail === 'net') return `${team} won it. ${who}'s ${stroke} went into the net`;
    if (o.detail === 'out') return `${team} won it. ${who}'s ${stroke} went out`;
    return `${team} won it on ${who}'s error`;
  }

  function rallyItem(r) {
    const w = r.outcome?.winner_team;
    const sw = swaps[r.id];
    return `<li class="rl-item ${w ? `w-${w}` : 'w-none'}" data-id="${r.id}">
      <button class="rl-jump" data-seek="${r.start_s}">
        <span class="rl-num">${rallyNumber(r)}</span>
        <span class="rl-meta"><span>${clock(r.start_s)}</span><span>${r.shots.length} ${r.shots.length === 1 ? 'shot' : 'shots'}</span><span>${Math.max(0, rallyEnd(r) - r.start_s).toFixed(1)} s</span></span>
        <span class="rl-res">${esc(resultSentence(r))}</span>
      </button>
      <div class="rl-fix">
        ${sw ? `<span class="rl-swapped">${esc(nameOf(match, sw[0]))} and ${esc(nameOf(match, sw[1]))} swapped here</span><button class="link-quiet rl-undo">Undo</button>`
            : '<button class="link-quiet rl-open" aria-expanded="false">Two players mixed up here?</button>'}
      </div>
      <div class="rl-panel" hidden>
        <p>Tap the two people who are the wrong way round in rally ${rallyNumber(r)}.</p>
        <div class="rl-people">${people.map((p) => `<button class="chip side-${sideNumber(p.team)}" data-pid="${p.id}" aria-pressed="false"><img src="${asset(`players/${p.id}.jpg`)}" alt="">${esc(firstName(match, p.id))}</button>`).join('')}</div>
        <div class="rl-panel-actions"><button class="btn btn-small" disabled>Swap them in this rally</button><button class="link-quiet rl-cancel">Cancel</button></div>
      </div>
    </li>`;
  }

  const video = document.getElementById('video');
  const $ = (id) => document.getElementById(id);
  const ovLines = $('ov-lines'), ovHit = $('ov-hit'), ovLand = $('ov-land');
  const mini = $('mini');
  const scrub = $('scrub');
  const rl = $('rl');

  /* ---- mini court ---- */
  mini.innerHTML = `<svg viewBox="-0.9 -0.9 7.9 15.2" role="img" aria-label="Players from above">
      <rect class="court-mat" x="-0.9" y="-0.9" width="7.9" height="15.2" rx="0.2"/>${courtLines({ width: 0.07 })}
      <g id="mini-land"></g>
      ${people.map((p) => `<g class="mini-p side-${sideNumber(p.team)}" id="mp-${p.id}" opacity="0"><circle r="0.42"/><text dy="0.17">${esc(firstName(match, p.id).slice(0, 1))}${p.id.slice(1)}</text></g>`).join('')}
    </svg>`;
  // label with initial and person number, e.g. A1; enough to tell four apart at a glance
  people.forEach((p) => { const t = mini.querySelector(`#mp-${p.id} text`); t.textContent = initials(nameOf(match, p.id)); });
  function initials(n) { return n.split(/\s+/).map((w) => w[0]).join('').slice(0, 2).toUpperCase(); }

  // mini court sits on the picture on wide screens, in the strip below on narrow ones
  const wide = matchMedia('(min-width: 861px)');
  const placeMini = () => (wide.matches ? $('screen') : $('hud')).appendChild(mini);
  placeMini(); wide.addEventListener('change', placeMini);

  /* ---- overlay ---- */
  let lastView = null;
  function drawLines(view) {
    if (view === lastView) return;
    lastView = view;
    if (!view) { ovLines.innerHTML = ''; return; }
    ovLines.innerHTML = courtSegments().map(([a, b]) => {
      const [x1, y1] = applyH(view.inverse, a[0], a[1]);
      const [x2, y2] = applyH(view.inverse, b[0], b[1]);
      return `<line x1="${x1 * VW}" y1="${y1 * VH}" x2="${x2 * VW}" y2="${y2 * VH}"/>`;
    }).join('');
  }

  function drawHitter(view, shot, t, strength) {
    if (!view || !shot?.hitter_id || strength <= 0) { ovHit.innerHTML = ''; return; }
    const pos = positionAt(match, shot.hitter_id, t) || shot.hitter_position;
    if (!pos) { ovHit.innerHTML = ''; return; }
    const pts = [];
    for (let i = 0; i < 32; i++) {
      const a = (i / 32) * Math.PI * 2;
      const [x, y] = applyH(view.inverse, pos.x + Math.cos(a) * 0.55, pos.y + Math.sin(a) * 0.55);
      pts.push([x * VW, y * VH]);
    }
    const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
    const [cx, cy] = applyH(view.inverse, pos.x, pos.y).map((v, i) => v * (i ? VH : VW));
    const w = Math.max(...xs) - Math.min(...xs);
    const h = w * 2.4;
    const left = Math.min(...xs), right = Math.max(...xs);
    const team = teamOf(match, shot.hitter_id);
    const name = nameOf(match, shot.hitter_id);
    ovHit.style.opacity = strength.toFixed(2);
    ovHit.innerHTML = `
      <polygon class="beam" points="${cx - w * 0.12},${cy - h * 1.15} ${cx + w * 0.12},${cy - h * 1.15} ${right},${cy} ${left},${cy}" fill="url(#beam)"/>
      <ellipse cx="${cx}" cy="${cy}" rx="${w * 0.6}" ry="${(Math.max(...ys) - Math.min(...ys)) * 0.6}" fill="url(#pool)"/>
      <polygon class="ring side-${sideNumber(team)}" points="${pts.map((p) => p.join(',')).join(' ')}"/>
      <g class="tag side-${sideNumber(team)}" transform="translate(${right + 8},${cy + 4})">
        <line x1="0" y1="0" x2="14" y2="0"/><text x="18" y="5">${esc(name)}</text>
      </g>`;
  }

  function drawLanding(rally, t) {
    const last = rally?.shots[rally.shots.length - 1];
    const L = last?.landing;
    if (!L || !L.image || t < L.time_s || t > rallyEnd(rally) + 3) { ovLand.innerHTML = ''; return; }
    const x = L.image.x * VW, y = L.image.y * VH;
    const word = L.in_court ? 'In' : 'Out';
    ovLand.innerHTML = `<g transform="translate(${x},${y})" class="${L.in_court ? 'in' : 'out'}">
      <ellipse rx="22" ry="8"/><line x1="-6" y1="-6" x2="6" y2="6"/><line x1="6" y1="-6" x2="-6" y2="6"/>
      <text y="-16">${word}</text></g>`;
  }

  /* ---- live state ---- */
  const H = {
    stroke: $('h-stroke'), who: $('h-who'), speed: $('h-speed'), speedNote: $('h-speed-note'), speedCell: $('h-speed-cell'),
    shots: $('h-shots'), time: $('h-time'), rallyK: $('h-rally-k'), w1: $('h-w1'), w2: $('h-w2'), cur: $('cur'), head: $('tl-head'),
  };
  let currentRallyId = null;

  function update() {
    const t = video.currentTime || 0;
    const frame = Math.round(t * fps);
    const view = viewAt(match, frame);
    drawLines(view);
    H.cur.textContent = clock(t);
    if (document.activeElement !== scrub) scrub.value = t;
    H.head.style.left = `${(t / DUR) * 100}%`;

    // the rally under the playhead, or the one just finished
    let rally = rallies.find((r) => t >= r.start_s - 0.2 && t <= rallyEnd(r) + 0.2);
    const inRally = !!rally;
    if (!rally) rally = [...rallies].reverse().find((r) => rallyEnd(r) < t) || null;

    let shot = null, idx = -1;
    if (rally) {
      for (let i = 0; i < rally.shots.length; i++) if (rally.shots[i].time_s <= t + 0.02) idx = i;
      shot = idx >= 0 ? rally.shots[idx] : null;
    }
    // hitter light: on from the contact until the next one, fading once the rally is over
    const next = rally && idx + 1 < rally.shots.length ? rally.shots[idx + 1].time_s : null;
    let strength = 0;
    if (shot && inRally) strength = next ? 1 : Math.max(0, 1 - (t - shot.time_s - 1.2) / 1.0);
    drawHitter(view, shot, t, Math.min(strength, 1));
    drawLanding(rally, t);

    if (rally && inRally) {
      H.rallyK.textContent = `Rally ${rallyNumber(rally)}`;
      H.shots.textContent = idx + 1;
      H.time.textContent = `${Math.max(0, Math.min(t, rallyEnd(rally)) - rally.start_s).toFixed(1)} s`;
    } else {
      H.rallyK.textContent = rally ? `After rally ${rallyNumber(rally)}` : 'Before the first rally';
      H.shots.textContent = rally ? rally.shots.length : '–';
      H.time.textContent = rally ? `${(rallyEnd(rally) - rally.start_s).toFixed(1)} s` : '';
    }
    if (shot) {
      H.stroke.textContent = labelText(shotLabel(shot));
      H.who.textContent = [shot.hitter_id ? nameOf(match, shot.hitter_id) : null, shot.side].filter(Boolean).join(', ');
      const sp = speedOf(shot);
      H.speedCell.classList.toggle('dim', !sp);
      if (sp?.kmh) { H.speed.innerHTML = `${sp.kmh}<small> km/h</small>`; H.speedNote.textContent = 'leaving the racket'; }
      else if (sp?.bound) { H.speed.textContent = 'Too fast'; H.speedNote.textContent = 'faster than this video can measure'; }
      else { H.speed.textContent = '–'; H.speedNote.textContent = 'not measured for this shot'; }
    } else {
      H.stroke.textContent = '–'; H.who.textContent = ''; H.speed.textContent = '–'; H.speedNote.textContent = '';
      H.speedCell.classList.add('dim');
    }

    // rallies won up to the playhead
    let w1 = 0, w2 = 0;
    for (const r of rallies) if (r.outcome?.winner_team && rallyEnd(r) <= t) r.outcome.winner_team === 'T1' ? w1++ : w2++;
    H.w1.textContent = w1; H.w2.textContent = w2;

    // mini court: everybody now, plus the last landing so far
    for (const p of people) {
      const g = document.getElementById(`mp-${p.id}`);
      const pos = positionAt(match, p.id, t, 3);
      if (pos && view) { g.setAttribute('transform', `translate(${pos.x},${pos.y})`); g.setAttribute('opacity', '1'); }
      else g.setAttribute('opacity', '0');
      g.classList.toggle('hitting', !!shot && shot.hitter_id === p.id && strength > 0.5);
    }
    let land = null;
    for (const r of rallies) { const L = r.shots[r.shots.length - 1]?.landing; if (L?.position && L.time_s <= t) land = L; }
    document.getElementById('mini-land').innerHTML = land
      ? `<g class="mini-land ${land.in_court ? 'in' : 'out'}" transform="translate(${land.position.x},${land.position.y})"><circle r="0.32"/><path d="M-0.2 -0.2 L0.2 0.2 M0.2 -0.2 L-0.2 0.2"/></g>` : '';

    // rally list follows the playhead
    const id = inRally ? rally.id : null;
    if (id !== currentRallyId) {
      currentRallyId = id;
      rl.querySelectorAll('.rl-item').forEach((li) => li.classList.toggle('current', li.dataset.id === id));
      if (id && !video.paused) {
        const li = rl.querySelector(`[data-id="${id}"]`);
        if (li && rl.scrollHeight > rl.clientHeight) rl.scrollTo({ top: li.offsetTop - rl.offsetTop - 12, behavior: 'smooth' });
      }
    }
  }

  /* ---- loop ---- */
  let raf = 0;
  const loop = () => { update(); raf = video.paused ? 0 : requestAnimationFrame(loop); };
  const setPlayIcon = () => {
    const playing = !video.paused;
    $('play-icon').setAttribute('d', playing ? 'M5 4h3.5v12H5zM11.5 4H15v12h-3.5z' : 'M6 4 L16 10 L6 16 Z');
    $('play').setAttribute('aria-label', playing ? 'Pause' : 'Play');
    $('bigplay').hidden = playing;
  };
  video.addEventListener('play', () => { setPlayIcon(); if (!raf) raf = requestAnimationFrame(loop); });
  video.addEventListener('pause', setPlayIcon);
  video.addEventListener('seeked', update);
  video.addEventListener('loadedmetadata', update);
  const toggle = () => (video.paused ? video.play() : video.pause());
  $('play').addEventListener('click', toggle);
  $('bigplay').addEventListener('click', toggle);
  video.addEventListener('click', toggle);
  const seek = (s) => { video.currentTime = Math.min(Math.max(s, 0), DUR - 0.1); update(); };
  scrub.addEventListener('input', () => seek(Number(scrub.value)));
  const jumpRally = (dir) => {
    const t = video.currentTime;
    const list = dir > 0 ? rallies.filter((r) => r.start_s > t + 0.5) : rallies.filter((r) => r.start_s < t - 1.5).reverse();
    if (list[0]) seek(list[0].start_s - 0.8);
  };
  $('prev').addEventListener('click', () => jumpRally(-1));
  $('next').addEventListener('click', () => jumpRally(1));
  $('lines-toggle').addEventListener('change', (e) => ovLines.classList.toggle('off', !e.target.checked));

  const onKey = (e) => {
    if (e.target.closest('input, textarea, select') && e.target.type !== 'range') return;
    if (e.key === ' ' && !e.target.closest('button')) { e.preventDefault(); toggle(); }
    else if (e.key === '[') jumpRally(-1);
    else if (e.key === ']') jumpRally(1);
    else if (e.key === 'ArrowRight' && e.target === document.body) seek(video.currentTime + 5);
    else if (e.key === 'ArrowLeft' && e.target === document.body) seek(video.currentTime - 5);
  };
  addEventListener('keydown', onKey);

  /* ---- rally list: jump and swap ---- */
  rl.addEventListener('click', (e) => {
    const li = e.target.closest('.rl-item');
    if (!li) return;
    const r = rallies.find((x) => x.id === li.dataset.id);
    const panel = li.querySelector('.rl-panel');
    if (e.target.closest('.rl-jump')) { seek(r.start_s - 0.8); video.play(); return; }
    if (e.target.closest('.rl-open')) {
      panel.hidden = !panel.hidden;
      li.classList.toggle('open', !panel.hidden);
      e.target.setAttribute('aria-expanded', String(!panel.hidden));
      return;
    }
    if (e.target.closest('.rl-cancel')) { panel.hidden = true; li.classList.remove('open'); li.querySelector('.rl-open')?.setAttribute('aria-expanded', 'false'); return; }
    const chip = e.target.closest('.chip');
    if (chip) {
      const on = chip.getAttribute('aria-pressed') !== 'true';
      const pressed = panel.querySelectorAll('.chip[aria-pressed="true"]');
      if (on && pressed.length >= 2) pressed[0].setAttribute('aria-pressed', 'false');
      chip.setAttribute('aria-pressed', String(on));
      panel.querySelector('.btn').disabled = panel.querySelectorAll('.chip[aria-pressed="true"]').length !== 2;
      return;
    }
    if (e.target.closest('.rl-panel .btn')) {
      const ids = [...panel.querySelectorAll('.chip[aria-pressed="true"]')].map((c) => c.dataset.pid);
      swaps[r.id] = ids; setState({ swaps });
      li.outerHTML = rallyItem(r);
      toast(`Swapped ${nameOf(match, ids[0])} and ${nameOf(match, ids[1])} in rally ${rallyNumber(r)}. The match is rebuilt with the fix.`);
      update();
      return;
    }
    if (e.target.closest('.rl-undo')) {
      delete swaps[r.id]; setState({ swaps });
      li.outerHTML = rallyItem(r);
      toast(`Undid the swap in rally ${rallyNumber(r)}.`);
    }
  });

  // start at the beginning of the first rally so the overlay has something to say
  // ?t=seconds opens the video at that moment (shareable), otherwise just before the first rally
  const startAt = Number(new URLSearchParams(location.search).get('t'));
  video.addEventListener('loadedmetadata', () => { if (video.currentTime < 1) seek(startAt || rallies[0].start_s - 0.5); }, { once: true });
  update();
  setPlayIcon();

  return () => { wide.removeEventListener('change', placeMini); cancelAnimationFrame(raf); removeEventListener('keydown', onKey); video.pause(); video.removeAttribute('src'); video.load(); };
}
