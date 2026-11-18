// Watch: the video with a coach's telestration synced to the playhead.

import {
  loadMatch,
  matchKey,
  dataBase,
  displayNames,
  teamName,
  firstName,
  initials,
  shotLabel,
  cap,
  viewForFrame,
  apply3,
  positionAt,
  lastKnownPosition,
  clock,
  esc,
  session,
  writeSession,
  prefersReducedMotion,
} from './data.js';
import { polyLoop, arrowPath, crossPath, ringPath, svgEl } from './ink.js';
import { toast } from './app.js';

const TEAM_VAR = { T1: 'var(--blue)', T2: 'var(--red)' };
const TEAM_HEX = { T1: '#1F57C3', T2: '#D3362D' };
const TEAM_WORD = { T1: 'Blue', T2: 'Red' };

export async function renderWatch(v) {
  const key = matchKey();
  const { analysis: A } = await loadMatch(key);
  const names = displayNames(A);
  const team = Object.fromEntries(A.players.map((p) => [p.id, p.team]));
  const W = A.video.width;
  const H = A.video.height;
  const fps = A.video.fps;
  const dur = A.video.duration_s;
  const doubles = A.video.mode === 'doubles';
  const reduced = prefersReducedMotion();
  const swaps = (session().swaps && session().swaps[key]) || {};

  v.innerHTML = `
  <div class="page">
    <div class="match-head">
      <h1><span class="c-blue">${esc(teamName(A, 'T1', names))}</span> <span style="color:var(--ink-3);font-weight:600">v</span> <span class="c-red">${esc(teamName(A, 'T2', names))}</span></h1>
      <span class="meta">${doubles ? 'Doubles' : 'Singles'}, ${clock(dur)} of video, ${A.rallies.length} rallies</span>
    </div>
    ${A.warnings.map((w) => `<p class="warn">${esc(w)}</p>`).join('')}
    <div class="watch">
      <div>
        <div class="screen paused" id="screen" style="aspect-ratio:${W}/${H}">
          <video id="vid" src="${dataBase(key)}/video.mp4" poster="${dataBase(key)}/poster.jpg" preload="metadata" playsinline></video>
          <svg class="tele" id="tele" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true">
            <g id="g-paused"></g><g id="g-live"></g>
          </svg>
          <div class="hud" aria-hidden="true">
            <span class="chip" id="chip-score"></span>
            <span class="chip" id="chip-rally"></span>
          </div>
          <p class="paused-note" id="pnote"></p>
          <button class="play-big" id="bigplay" aria-label="Play">
            <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true"><path d="M9 5 L25 15 L9 25 Z" fill="currentColor"/></svg>
          </button>
        </div>
        <div class="transport">
          <button class="icon-btn" id="play" aria-label="Play"></button>
          <span class="time" id="time">0:00 / ${clock(dur)}</span>
          <div class="strip" id="strip" role="slider" tabindex="0" aria-label="Video position. Left and right move 5 seconds, page up and page down jump between rallies" aria-valuemin="0" aria-valuemax="${Math.round(dur)}" aria-valuenow="0">
            <div class="track"></div>
            ${A.rallies
              .map((r, i) => {
                const w = r.outcome && r.outcome.winner_team;
                return `<span class="seg-r ${w || 'none'}" data-i="${i}" style="left:${(r.start_s / dur) * 100}%;width:${(Math.max(0.3, r.end_s - r.start_s) / dur) * 100}%" data-tip="${esc(
                  `Rally ${i + 1}: ${r.shots.length} shots. ${outcomeText(r)}`
                )}"></span>`;
              })
              .join('')}
            <div class="head" id="head"></div>
          </div>
          <button class="icon-btn light" id="next" aria-label="Next rally">
            <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true"><path d="M4 4 L13 10 L4 16 Z M14 4 H17 V16 H14 Z" fill="currentColor"/></svg>
          </button>
        </div>
      </div>
      <aside class="side" aria-label="Live details">
        <section class="side-block">
          <h2 id="rally-h">This rally</h2>
          <div class="rally-now" id="rally-now"></div>
        </section>
        <section class="side-block last-shot" aria-live="polite">
          <h2>Last shot</h2>
          <div id="last"></div>
        </section>
        <section class="side-block mini-court">
          <h2>On court now</h2>
          <svg id="mini" viewBox="-0.9 -0.9 7.9 15.2" role="img" aria-label="Top-down court with every player and the last landing spot"></svg>
          <div class="legend" id="mini-legend"></div>
        </section>
      </aside>
    </div>

    <section class="rallies" aria-labelledby="rl-title">
      <h2 id="rl-title">Rallies</h2>
      <p>Jump to any rally. If two players were mixed up in one rally, swap them there and the numbers follow.</p>
      <ol class="rally-list" id="rlist"></ol>
    </section>
  </div>`;

  const vid = v.querySelector('#vid');
  const screen = v.querySelector('#screen');
  const live = v.querySelector('#g-live');
  const pausedG = v.querySelector('#g-paused');
  const chipScore = v.querySelector('#chip-score');
  const chipRally = v.querySelector('#chip-rally');
  const pnote = v.querySelector('#pnote');
  const playBtn = v.querySelector('#play');
  const bigPlay = v.querySelector('#bigplay');
  const timeEl = v.querySelector('#time');
  const strip = v.querySelector('#strip');
  const head = v.querySelector('#head');
  const rallyNow = v.querySelector('#rally-now');
  const rallyH = v.querySelector('#rally-h');
  const lastEl = v.querySelector('#last');
  const mini = v.querySelector('#mini');
  const rlist = v.querySelector('#rlist');
  const segs = [...strip.querySelectorAll('.seg-r')];

  // ---------------------------------------------------------------- mini court
  drawCourt(mini);
  const miniDyn = svgEl('g', {}, mini);
  v.querySelector('#mini-legend').innerHTML = `<span><i style="background:var(--blue);border-radius:50%"></i>${doubles ? 'Blue team' : 'Blue side'}</span><span><i style="background:var(--red);border-radius:50%"></i>${doubles ? 'Red team' : 'Red side'}</span><span>○ winner landed, × error landed</span>`;

  // ---------------------------------------------------------------- helpers
  const rallyAt = (t) => A.rallies.findIndex((r) => t >= r.start_s - 0.4 && t <= r.end_s + 1.2);
  const proj = (view, p) => {
    if (!view || !p) return null;
    const q = apply3(view._inv, p.x, p.y);
    return q ? { x: q.x * W, y: q.y * H } : null;
  };
  function lastShotAt(r, t) {
    let s = null;
    for (const sh of r.shots) if (sh.time_s <= t + 0.02) s = sh;
    return s;
  }
  function wonSoFar(t) {
    const c = { T1: 0, T2: 0 };
    for (const r of A.rallies) {
      const land = r.shots.length && r.shots[r.shots.length - 1].landing;
      const decided = land ? land.time_s : r.end_s;
      if (decided <= t && r.outcome && r.outcome.winner_team) c[r.outcome.winner_team]++;
    }
    return c;
  }

  function speedHtml(sh) {
    const f = sh.flight;
    if (!f) return '';
    if (f.quality === 'good' && f.initial_speed_kmh != null)
      return `<div class="speed"><b>${Math.round(f.initial_speed_kmh)}</b><span>km/h off the racket</span></div><p class="note">An estimate from the video; single shots can be well off.</p>`;
    if (f.quality === 'speed_bound')
      return `<p class="note" style="font-size:var(--t-s);color:var(--ink-2)">Too fast to measure: at ${Math.round(fps)} frames a second the video can’t pin down a hit this hard.</p>`;
    return '';
  }

  // ---------------------------------------------------------------- render
  let lastKey = '';
  let ui = 1; // overlay scale: marks stay legible on small screens
  let pausedKey = '';
  let liveShotId = null;
  let liveDrawStart = 0;

  function frame() {
    const t = vid.currentTime || 0;
    ui = Math.max(1, 720 / Math.max(1, screen.clientWidth));
    const frameNo = Math.round(t * fps);
    const view = viewForFrame(A, frameNo);
    const ri = rallyAt(t);
    const r = ri >= 0 ? A.rallies[ri] : null;
    const sh = r ? lastShotAt(r, t) : null;

    // transport
    timeEl.textContent = `${clock(t)} / ${clock(dur)}`;
    head.style.left = `${(t / dur) * 100}%`;
    strip.setAttribute('aria-valuenow', Math.round(t));
    strip.setAttribute('aria-valuetext', `${clock(t)}${r ? `, rally ${ri + 1}` : ''}`);

    // chips
    const won = wonSoFar(t);
    chipScore.innerHTML = `<i style="background:var(--blue)"></i><span class="n">${won.T1}</span><i style="background:var(--red);margin-left:4px"></i><span class="n">${won.T2}</span><span class="lbl" style="margin-left:4px">rallies won</span>`;
    if (r) {
      const n = r.shots.filter((s) => s.time_s <= t + 0.02).length;
      const el = Math.max(0, Math.min(t, r.end_s) - r.start_s);
      chipRally.hidden = false;
      chipRally.innerHTML = `<span class="lbl">Rally ${ri + 1}</span><span class="n" style="margin-left:6px">${n}</span>${n === 1 ? 'shot' : 'shots'}<span class="n" style="margin-left:6px">${el.toFixed(1)}</span>s`;
    } else {
      chipRally.hidden = true;
    }

    // side: this rally + last shot (only when they change)
    const k = `${ri}|${sh ? sh.id : ''}|${vid.paused}|${r ? Math.floor(Math.min(t, r.end_s) * 10) : ''}`;
    const big = k.split('|').slice(0, 3).join('|') !== lastKey.split('|').slice(0, 3).join('|');
    if (k !== lastKey) {
      lastKey = k;
      segs.forEach((s, i) => s.classList.toggle('on', i === ri));
      rlist.querySelectorAll('.rally').forEach((li, i) => li.classList.toggle('on', i === ri));
      if (r) {
        const n = r.shots.filter((s) => s.time_s <= t + 0.02).length;
        rallyH.textContent = `Rally ${ri + 1} of ${A.rallies.length}`;
        rallyNow.innerHTML = `<div><b>${n}</b><span>of ${r.shots.length} shots</span></div><div><b>${Math.max(0, Math.min(t, r.end_s) - r.start_s).toFixed(1)} s</b><span>of ${(r.end_s - r.start_s).toFixed(1)} s</span></div>`;
      } else {
        rallyH.textContent = 'This rally';
        rallyNow.innerHTML = `<p class="empty" style="margin:0;color:var(--ink-3)">Between rallies. Press next rally to skip ahead.</p>`;
      }
      if (!big) {
        /* only the rally clock moved */
      } else if (sh) {
        const who = sh.hitter_id ? names[sh.hitter_id] : 'Not sure who';
        const sideTxt = sh.side ? `${sh.side}` : 'side unknown';
        lastEl.innerHTML = `<p class="what" style="color:${sh.hitter_id ? TEAM_VAR[team[sh.hitter_id]] : 'var(--ink)'}">${esc(cap(shotLabel(sh)))}, ${esc(sideTxt)}</p><p class="who">${esc(who)}</p>${speedHtml(sh)}`;
      } else {
        lastEl.innerHTML = `<p class="empty">No shot yet in this stretch of video.</p>`;
      }
    }

    // live telestration: circle the hitter, scribble the shot
    live.innerHTML = '';
    if (sh && sh.hitter_id && view && t <= (r.end_s + 0.8)) {
      if (sh.id !== liveShotId) {
        liveShotId = sh.id;
        liveDrawStart = performance.now();
      }
      const feet = positionAt(A, sh.hitter_id, t) || lastKnownPosition(A, sh.hitter_id, t, 1) || sh.hitter_position;
      if (feet) {
        const color = TEAM_HEX[team[sh.hitter_id]];
        const pts = [];
        for (let i = 0; i < 32; i++) {
          const a = (i / 32) * Math.PI * 2 + 0.4;
          const q = proj(view, { x: feet.x + Math.cos(a) * 0.75, y: feet.y + Math.sin(a) * 0.75 });
          if (q) pts.push(q);
        }
        const c = proj(view, feet);
        if (pts.length > 20 && c) {
          const path = svgEl('path', { d: polyLoop(pts, 5), fill: 'none', stroke: color, 'stroke-width': 6 * ui, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, live);
          const halo = path.cloneNode();
          halo.setAttribute('stroke', '#fff');
          halo.setAttribute('stroke-width', 10 * ui);
          halo.setAttribute('opacity', 0.55);
          live.insertBefore(halo, path);
          const u = reduced || vid.paused ? 1 : Math.min(1, (performance.now() - liveDrawStart) / 320);
          if (u < 1) {
            const L = path.getTotalLength();
            for (const p of [path, halo]) {
              p.style.strokeDasharray = `${L} ${L}`;
              p.style.strokeDashoffset = `${L * (1 - u)}`;
            }
          }
          // label: to the right of the circle, flipped near the right edge
          const top = Math.min(...pts.map((p) => p.y));
          const right = Math.max(...pts.map((p) => p.x));
          const left = Math.min(...pts.map((p) => p.x));
          const flip = right > W - 300 * ui;
          const lx = flip ? left - 12 : right + 12;
          const ly = Math.max(40 * ui, top + 4);
          const anchor = flip ? 'end' : 'start';
          const txt = (s, y, size, fill = '#fff') => {
            const el = svgEl('text', { x: lx, y, 'text-anchor': anchor, fill, stroke: 'rgba(15,18,24,.78)', 'stroke-width': 5 * ui, 'paint-order': 'stroke', 'stroke-linejoin': 'round', style: `font:700 ${size * ui}px Kalam` }, live);
            el.textContent = s;
            return el;
          };
          txt(`${shotLabel(sh)}${sh.side ? `, ${sh.side}` : ''}`, ly, 30);
          txt(names[sh.hitter_id], ly + 28 * ui, 22, '#e9eef0');
          const f = sh.flight;
          if (f && f.quality === 'good' && f.initial_speed_kmh != null) txt(`~${Math.round(f.initial_speed_kmh)} km/h`, ly + 56 * ui, 24, '#F4D03F');
          else if (f && f.quality === 'speed_bound') txt('too fast to measure', ly + 56 * ui, 20, '#F4D03F');
        }
      }
    } else liveShotId = null;

    // paused: draw the rally so far as a coach would on a frozen frame
    const pk = vid.paused && r && view ? `${ri}|${sh ? sh.id : ''}|${view.start_frame}` : '';
    if (pk !== pausedKey) {
      pausedKey = pk;
      pausedG.innerHTML = '';
      pnote.textContent = '';
      if (pk) drawRallySoFar(r, t, view);
    }
    screen.classList.toggle('paused', vid.paused);
    bigPlay.hidden = !vid.paused || t > 0.05;
    drawMini(t, r, sh);
  }

  function drawRallySoFar(r, t, view) {
    const shots = r.shots.filter((s) => s.time_s <= t + 0.02);
    const paths = [];
    const firstShown = Math.max(0, shots.length - 5); // the last five shots keep the frame readable
    shots.forEach((s, i) => {
      if (i < firstShown) return;
      const next = r.shots[i + 1];
      const isLast = !next;
      const from = proj(view, s.hitter_position);
      let to = null;
      if (next && next.time_s <= t + 0.02) to = proj(view, next.hitter_position);
      else if (isLast && s.landing && s.landing.position && s.landing.time_s <= t) to = proj(view, s.landing.position);
      if (!from || !to || !s.hitter_id) return;
      const color = TEAM_HEX[team[s.hitter_id]];
      const a = arrowPath(from.x, from.y, to.x, to.y, i % 2 ? 0.14 : -0.14, 22 * ui);
      const g = svgEl('g', { fill: 'none', 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }, pausedG);
      svgEl('path', { d: a.body + a.head, stroke: '#fff', 'stroke-width': 9 * ui, opacity: 0.5 }, g);
      paths.push(svgEl('path', { d: a.body, stroke: color, 'stroke-width': 5 * ui }, g));
      paths.push(svgEl('path', { d: a.head, stroke: color, 'stroke-width': 5 * ui }, g));
      const num = svgEl('text', { x: from.x, y: from.y + 6 * ui, 'text-anchor': 'middle', fill: '#fff', stroke: color, 'stroke-width': 7 * ui, 'paint-order': 'stroke', style: `font:700 ${20 * ui}px Kalam` }, pausedG);
      num.textContent = i + 1;
      if (isLast && r.outcome && s.landing && s.landing.time_s <= t) {
        const d = r.outcome.reason === 'winner' ? ringPath(to.x, to.y, 22 * ui, i) : crossPath(to.x, to.y, 16 * ui);
        paths.push(svgEl('path', { d, stroke: color, 'stroke-width': 6 * ui, fill: 'none', 'stroke-linecap': 'round' }, pausedG));
      }
    });
    if (shots.length)
      pnote.textContent =
        shots.length > 5 ? `Paused: the last 5 of ${shots.length} shots so far` : `Paused: the rally so far, ${shots.length} ${shots.length === 1 ? 'shot' : 'shots'}`;
    import('./ink.js').then(({ drawOn }) => drawOn(paths, { duration: 280 }));
  }

  function drawMini(t, r, sh) {
    miniDyn.innerHTML = '';
    // last landing at or before t
    let land = null;
    for (const rr of A.rallies) {
      const last = rr.shots[rr.shots.length - 1];
      if (last && last.landing && last.landing.position && last.landing.time_s <= t) land = { rr, last };
    }
    if (land) {
      const { x, y } = land.last.landing.position;
      const c = land.last.hitter_id ? TEAM_HEX[team[land.last.hitter_id]] : '#22262E';
      const winner = land.rr.outcome && land.rr.outcome.reason === 'winner';
      svgEl('path', { d: winner ? ringPath(x, y, 0.35, 5) : crossPath(x, y, 0.28), fill: 'none', stroke: c, 'stroke-width': 0.12, 'stroke-linecap': 'round' }, miniDyn);
    }
    for (const p of A.players) {
      const pos = positionAt(A, p.id, t) || lastKnownPosition(A, p.id, t, 2);
      if (!pos) continue;
      const g = svgEl('g', { transform: `translate(${pos.x} ${pos.y})` }, miniDyn);
      if (sh && sh.hitter_id === p.id && r) svgEl('circle', { r: 0.62, fill: 'none', stroke: '#F4D03F', 'stroke-width': 0.18 }, g);
      svgEl('circle', { r: 0.42, fill: TEAM_HEX[p.team], stroke: '#fff', 'stroke-width': 0.08 }, g);
      const tx = svgEl('text', { y: 0.13, 'text-anchor': 'middle', fill: '#fff', style: 'font:700 0.36px "Barlow Condensed"' }, g);
      tx.textContent = initials(names[p.id]);
    }
  }

  // ---------------------------------------------------------------- rally list
  function renderList() {
    rlist.innerHTML = A.rallies
      .map((r, i) => {
        const last = r.shots[r.shots.length - 1];
        const lc = last && last.hitter_id ? TEAM_HEX[team[last.hitter_id]] : '#646b76';
        const icon = !r.outcome
          ? ''
          : r.outcome.reason === 'winner'
          ? `<path d="${ringPath(20, 20, 12, i)}" stroke="${lc}" stroke-width="3" fill="none" stroke-linecap="round"/>`
          : `<path d="${crossPath(20, 20, 10)}" stroke="${lc}" stroke-width="3.2" fill="none" stroke-linecap="round"/>`;
        const sw = swaps[r.id];
        return `<li class="rally" data-i="${i}">
          <button class="jump" data-jump="${i}" aria-label="Play rally ${i + 1}">
            <svg viewBox="0 0 40 40" aria-hidden="true">${icon}<text x="20" y="26" text-anchor="middle" style="font:700 16px 'Barlow Condensed'" fill="#22262E">${i + 1}</text></svg>
          </button>
          <span class="line1">${esc(outcomeText(r, names, team))}</span>
          <button class="swap-btn" data-swap="${i}" aria-expanded="false">Players mixed up?</button>
          <span class="line2">${r.shots.length} ${r.shots.length === 1 ? 'shot' : 'shots'}, ${(r.end_s - r.start_s).toFixed(1)} s, starts at ${clock(r.start_s)}</span>
          ${sw ? `<span class="swapped">Swapped ${esc(names[sw[0]])} and ${esc(names[sw[1]])} here. <button class="linkish" data-undo="${i}">Undo</button></span>` : ''}
        </li>`;
      })
      .join('');
  }
  renderList();

  rlist.addEventListener('click', (e) => {
    const j = e.target.closest('[data-jump]');
    const s = e.target.closest('[data-swap]');
    const u = e.target.closest('[data-undo]');
    const pk = e.target.closest('[data-pick]');
    const go = e.target.closest('[data-do-swap]');
    if (j) {
      const r = A.rallies[+j.dataset.jump];
      vid.currentTime = Math.max(0, r.start_s - 1);
      vid.play().catch(() => {});
      screen.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'center' });
    } else if (s) {
      const li = s.closest('.rally');
      const open = li.querySelector('.swap-panel');
      rlist.querySelectorAll('.swap-panel').forEach((p) => p.remove());
      rlist.querySelectorAll('[data-swap]').forEach((b) => b.setAttribute('aria-expanded', 'false'));
      if (open) return;
      s.setAttribute('aria-expanded', 'true');
      const panel = document.createElement('div');
      panel.className = 'swap-panel';
      panel.innerHTML = `<p>Pick the two players who are the wrong way round in rally ${+s.dataset.swap + 1}.</p>
        <div class="opts">${A.players
          .map((p) => `<button class="pick" data-pick="${p.id}" aria-pressed="false"><i style="background:${TEAM_VAR[p.team]}"></i>${esc(names[p.id])}</button>`)
          .join('')}</div>
        <button class="btn small" data-do-swap="${s.dataset.swap}" disabled>Swap them in this rally</button>`;
      li.appendChild(panel);
      panel.querySelector('.pick').focus();
    } else if (pk) {
      const panel = pk.closest('.swap-panel');
      const on = panel.querySelectorAll('.pick[aria-pressed=true]');
      if (pk.getAttribute('aria-pressed') === 'true') pk.setAttribute('aria-pressed', 'false');
      else if (on.length < 2) pk.setAttribute('aria-pressed', 'true');
      panel.querySelector('[data-do-swap]').disabled = panel.querySelectorAll('.pick[aria-pressed=true]').length !== 2;
    } else if (go) {
      const i = +go.dataset.doSwap;
      const ids = [...go.closest('.swap-panel').querySelectorAll('.pick[aria-pressed=true]')].map((b) => b.dataset.pick);
      swaps[A.rallies[i].id] = ids;
      saveSwaps();
      renderList();
      toast(`Swapped ${names[ids[0]]} and ${names[ids[1]]} in rally ${i + 1}. The numbers update in a moment.`);
      rlist.querySelector(`[data-swap="${i}"]`).focus();
    } else if (u) {
      const i = +u.dataset.undo;
      delete swaps[A.rallies[i].id];
      saveSwaps();
      renderList();
      toast(`Rally ${i + 1} is back as it was.`);
      rlist.querySelector(`[data-swap="${i}"]`).focus();
    }
  });
  function saveSwaps() {
    const all = session().swaps || {};
    all[key] = swaps;
    writeSession({ swaps: all });
  }

  // ---------------------------------------------------------------- transport
  const playIcon = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M4 2 L16 9 L4 16 Z" fill="currentColor"/></svg>';
  const pauseIcon = '<svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true"><path d="M3 2h4v14H3zM11 2h4v14h-4z" fill="currentColor"/></svg>';
  const syncPlay = () => {
    playBtn.innerHTML = vid.paused ? playIcon : pauseIcon;
    playBtn.setAttribute('aria-label', vid.paused ? 'Play' : 'Pause');
    bigPlay.hidden = !vid.paused || vid.currentTime > 0.05;
  };
  syncPlay();
  const toggle = () => (vid.paused ? vid.play().catch(() => {}) : vid.pause());
  playBtn.addEventListener('click', toggle);
  bigPlay.addEventListener('click', toggle);
  vid.addEventListener('click', toggle);
  let raf = 0;
  const loop = () => {
    frame();
    raf = vid.paused ? 0 : requestAnimationFrame(loop);
  };
  vid.addEventListener('play', () => {
    syncPlay();
    if (!raf) raf = requestAnimationFrame(loop);
  });
  vid.addEventListener('pause', () => {
    syncPlay();
    frame();
  });
  vid.addEventListener('seeked', frame);
  vid.addEventListener('loadedmetadata', frame);
  vid.addEventListener('error', () => {
    pnote.textContent = 'The video did not load. The marks and numbers still work.';
  });

  const seekTo = (t) => {
    vid.currentTime = Math.max(0, Math.min(dur - 0.05, t));
    frame();
  };
  const fromX = (clientX) => {
    const rc = strip.getBoundingClientRect();
    return ((clientX - rc.left) / rc.width) * dur;
  };
  let dragging = false;
  strip.addEventListener('pointerdown', (e) => {
    dragging = true;
    strip.setPointerCapture(e.pointerId);
    seekTo(fromX(e.clientX));
  });
  strip.addEventListener('pointermove', (e) => dragging && seekTo(fromX(e.clientX)));
  strip.addEventListener('pointerup', () => (dragging = false));
  const jumpRally = (dir) => {
    const t = vid.currentTime;
    const idx = dir > 0 ? A.rallies.findIndex((r) => r.start_s - 1 > t + 0.3) : findLastIndex(A.rallies, (r) => r.start_s - 1 < t - 1.5);
    if (idx >= 0) seekTo(A.rallies[idx].start_s - 1);
  };
  strip.addEventListener('keydown', (e) => {
    const map = { ArrowRight: () => seekTo(vid.currentTime + 5), ArrowLeft: () => seekTo(vid.currentTime - 5), PageDown: () => jumpRally(1), PageUp: () => jumpRally(-1), Home: () => seekTo(0), End: () => seekTo(dur) };
    if (map[e.key]) {
      e.preventDefault();
      map[e.key]();
    }
  });
  v.querySelector('#next').addEventListener('click', () => jumpRally(1));
  const onKey = (e) => {
    if (e.key !== ' ' || e.target.closest('input,button,textarea,select,[role=slider],a')) return;
    e.preventDefault();
    toggle();
  };
  document.addEventListener('keydown', onKey);

  frame();
  return () => {
    cancelAnimationFrame(raf);
    vid.pause();
    vid.removeAttribute('src');
    vid.load();
    document.removeEventListener('keydown', onKey);
  };
}

function findLastIndex(a, f) {
  for (let i = a.length - 1; i >= 0; i--) if (f(a[i])) return i;
  return -1;
}

function outcomeText(r, names, team) {
  const o = r.outcome;
  if (!o || !o.winner_team) return 'Outcome unclear';
  const w = TEAM_WORD[o.winner_team];
  const l = o.winner_team === 'T1' ? 'Red' : 'Blue';
  const where = o.detail === 'net' ? ' into the net' : o.detail === 'out' ? ' out' : '';
  if (o.reason === 'winner') return `${w} won with a winner`;
  if (o.reason === 'error') return `${w} won, ${l} hit${where || ' an error'}`;
  return `${w} won`;
}

// A printed top-down court, far end at the top, as in the video.
export function drawCourt(svg, { fill = '#E2EEE5', line = '#2E7D57', w = 0.05 } = {}) {
  const g = svgEl('g', { fill: 'none', stroke: line, 'stroke-width': w }, svg);
  svgEl('rect', { x: 0, y: 0, width: 6.1, height: 13.4, fill }, g);
  const ln = (x1, y1, x2, y2) => svgEl('line', { x1, y1, x2, y2 }, g);
  ln(0.46, 0, 0.46, 13.4);
  ln(5.64, 0, 5.64, 13.4);
  for (const y of [4.72, 8.68, 0.76, 12.64]) ln(0, y, 6.1, y);
  ln(3.05, 0, 3.05, 4.72);
  ln(3.05, 8.68, 3.05, 13.4);
  svgEl('line', { x1: -0.3, y1: 6.7, x2: 6.4, y2: 6.7, stroke: '#22262E', 'stroke-width': w * 1.8 }, g);
  return g;
}
