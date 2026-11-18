// Router and the flow screens: landing, upload, processing, name confirmation.

import {
  loadMatch,
  session,
  writeSession,
  matchKey,
  dataBase,
  displayNames,
  esc,
  prefersReducedMotion,
} from './data.js';
import { rng, loopPath, drawOn } from './ink.js';

const view = document.getElementById('view');
const rail = document.getElementById('rail');
const railNav = document.getElementById('rail-nav');
const railCta = document.getElementById('rail-cta');
let cleanup = null;

// ---------------------------------------------------------------- shared UI
export function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 3200);
}

const tip = document.getElementById('tip');
function showTip(el, x, y) {
  tip.textContent = el.getAttribute('data-tip');
  tip.hidden = false;
  const r = tip.getBoundingClientRect();
  let left = x + 14;
  let top = y + 14;
  if (left + r.width > innerWidth - 8) left = x - r.width - 14;
  if (top + r.height > innerHeight - 8) top = y - r.height - 14;
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${Math.max(8, top)}px`;
}
document.addEventListener('pointermove', (e) => {
  const el = e.target.closest && e.target.closest('[data-tip]');
  if (el) showTip(el, e.clientX, e.clientY);
  else tip.hidden = true;
});
document.addEventListener('focusin', (e) => {
  const el = e.target.closest && e.target.closest('[data-tip]');
  if (el) {
    const r = el.getBoundingClientRect();
    showTip(el, r.left + r.width / 2, r.bottom);
  } else tip.hidden = true;
});
document.addEventListener('scroll', () => (tip.hidden = true), { passive: true });

function setRail(mode) {
  rail.classList.toggle('is-hero', mode === 'hero');
  railCta.hidden = mode === 'flow';
  if (mode === 'match') {
    const r = location.hash.includes('analysis') ? 'analysis' : 'watch';
    railNav.innerHTML = `
      <a class="magnet-tab" href="#/match/watch" ${r === 'watch' ? 'aria-current="page"' : ''}>Watch</a>
      <a class="magnet-tab" href="#/match/analysis" ${r === 'analysis' ? 'aria-current="page"' : ''}>Analysis</a>`;
  } else railNav.innerHTML = '';
}

// ---------------------------------------------------------------- router
const routes = {
  '/': landing,
  '/upload': upload,
  '/processing': processing,
  '/names': names,
  '/match/watch': (v) => import('./watch.js').then((m) => m.renderWatch(v)),
  '/match/analysis': (v) => import('./analysis.js').then((m) => m.renderAnalysis(v)),
};

async function route() {
  const path = (location.hash.replace(/^#/, '') || '/').split('?')[0];
  const fn = routes[path] || landing;
  if (cleanup) {
    try {
      cleanup();
    } catch (e) {
      console.warn(e);
    }
    cleanup = null;
  }
  tip.hidden = true;
  view.innerHTML = '';
  scrollTo(0, 0);
  setRail(path === '/' ? 'hero' : path.startsWith('/match') ? 'match' : 'flow');
  document.title = titles[path] || 'Chalk talk';
  try {
    const c = await fn(view);
    cleanup = typeof c === 'function' ? c : null;
  } catch (e) {
    console.error(e);
    view.innerHTML = `<div class="page"><div class="page-head"><h1>This page didn't load</h1><p>${esc(
      e.message
    )}. Check that the prototype server is running from <code>design/prototypes</code>, then reload.</p></div></div>`;
  }
  if (path !== '/') view.focus({ preventScroll: true });
}
const titles = {
  '/': 'Chalk talk',
  '/upload': 'Analyse a match | Chalk talk',
  '/processing': 'Analysing | Chalk talk',
  '/names': "Who's who | Chalk talk",
  '/match/watch': 'Watch | Chalk talk',
  '/match/analysis': 'Analysis | Chalk talk',
};
addEventListener('hashchange', route);

// ---------------------------------------------------------------- landing
async function landing(v) {
  const reduced = prefersReducedMotion();
  v.innerHTML = `
  <div class="landing">
    <section class="hero ${reduced ? 'still' : ''}" id="hero" aria-labelledby="hero-title">
      <div class="stage" id="stage">
        <div class="board-host" id="board-host"></div>
        <div class="hero-copy">
          <h1 id="hero-title">See your match the way your coach does.</h1>
          <p>Upload a video of a game or a highlight reel. We find every rally, every shot and who played it, then put it all on the board.</p>
          <div class="hero-actions">
            <a class="btn" href="#/upload" id="go"><span class="puck" aria-hidden="true"></span>Analyse a match</a>
            <a class="btn ghost" href="#/match/watch">Open a sample match</a>
          </div>
        </div>
        <p class="hero-note" aria-hidden="true">Real rallies from a club doubles match, replayed at real speed.
          <small>Each magnet follows a player's feet. Each line is one shot; a ring marks a winner, a cross an error.</small></p>
        <div class="scroll-cue" aria-hidden="true">
          <svg viewBox="0 0 26 34"><path d="M13 3 C12 12 14 20 13 30 M5 22 C9 25 11 28 13 31 C15 27 18 24 21 22" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
          scroll to lay the board flat
        </div>
      </div>
    </section>
    <section class="how" aria-labelledby="how-title">
      <div class="how-inner">
        <h2 id="how-title">From phone video to team talk</h2>
        <p>Film from behind the baseline, as high as you can, with the whole court in view. Any length works, from one rally to a full match.</p>
        <ol class="steps">
          <li><h3>Upload the video</h3><p>Choose singles or doubles and type the names, partners together.</p></li>
          <li><h3>We read the match</h3><p>We find the court, follow the players and the shuttle, spot every shot and split the video into rallies.</p></li>
          <li><h3>Check who's who, then dig in</h3><p>Confirm which player is which name. Then watch with the coach's marks, or read the numbers for each player and team.</p></li>
        </ol>
        <div class="how-cta">
          <a class="btn" href="#/upload"><span class="puck" aria-hidden="true"></span>Analyse a match</a>
          <span class="hand">An 8-minute video takes a few minutes.</span>
        </div>
      </div>
    </section>
    <footer class="site-foot">Chalk talk prototype. Speeds, positions and outcomes are estimates from one camera.</footer>
  </div>`;

  const stage = v.querySelector('#stage');
  const hero = v.querySelector('#hero');
  const host = v.querySelector('#board-host');
  let board = null;
  let disposed = false;

  try {
    const { analysis } = await loadMatch('doubles');
    if (disposed) return;
    const s = session();
    const nm = s.key === 'doubles' && s.assigned ? s.assigned : Object.fromEntries(analysis.players.map((p) => [p.id, p.name || p.id]));
    const { createBoard } = await import('./board3d.js');
    if (disposed) return;
    board = await createBoard(host, { analysis, names: nm, reduced });
    if (disposed) board.dispose();
  } catch (e) {
    console.warn('3D board unavailable', e);
    host.innerHTML = `<p class="fallback-note">The 3D board needs WebGL, which this browser has turned off. Everything else works.</p>`;
  }

  const onScroll = () => {
    if (reduced) return;
    const max = hero.offsetHeight - innerHeight;
    const p = Math.max(0, Math.min(1, scrollY / Math.max(1, max)));
    stage.style.setProperty('--p', p.toFixed(3));
    if (board) board.setProgress(p);
    rail.classList.toggle('is-hero', p < 0.55 && scrollY < hero.offsetHeight - innerHeight * 0.5);
  };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll);
  onScroll();

  // Clicking in: the board lies flat and becomes the page.
  const go = v.querySelector('#go');
  go.addEventListener('click', (e) => {
    if (reduced || !board) return;
    e.preventDefault();
    const from = board.progress;
    const t0 = performance.now();
    const dur = 900 * (1 - from) + 200;
    const step = (n) => {
      const u = Math.min(1, (n - t0) / dur);
      const p = from + (1 - from) * (u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2);
      board.setProgress(p);
      stage.style.setProperty('--p', p.toFixed(3));
      if (u < 1) requestAnimationFrame(step);
      else {
        stage.style.setProperty('--takeover', '1');
        setTimeout(() => (location.hash = '#/upload'), 360);
      }
    };
    if (scrollY > 2) scrollTo({ top: 0 });
    requestAnimationFrame(step);
  });

  return () => {
    disposed = true;
    removeEventListener('scroll', onScroll);
    removeEventListener('resize', onScroll);
    if (board) board.dispose();
  };
}

// ---------------------------------------------------------------- upload
function roughRect(w, h, seed = 4) {
  const r = rng(seed);
  const j = () => (r() - 0.5) * 5;
  const pad = 6;
  const pts = [
    [pad, pad],
    [w - pad, pad],
    [w - pad, h - pad],
    [pad, h - pad],
  ];
  let d = '';
  for (let i = 0; i < 4; i++) {
    const [x1, y1] = pts[i];
    const [x2, y2] = pts[(i + 1) % 4];
    const mx = (x1 + x2) / 2 + j() * 1.5;
    const my = (y1 + y2) / 2 + j() * 1.5;
    d += `M${x1 + j()} ${y1 + j()}Q${mx} ${my} ${x2 + j() + (i === 3 ? 4 : 0)} ${y2 + j()}`;
  }
  return d;
}

function upload(v) {
  const s = session();
  let mode = s.mode || 'doubles';
  let fileName = s.fileName || '';
  const prev = s.names || {};
  v.innerHTML = `
  <div class="page">
    <div class="page-head">
      <h1>Analyse a match</h1>
      <p>Add the video, say who played, and we'll do the rest. You can close this tab while it works.</p>
    </div>
    <form class="upload-grid" id="up" novalidate>
      <div>
        <label class="drop" id="drop">
          <svg class="frame" aria-hidden="true"><path id="drop-frame" fill="none" stroke="var(--ink)" stroke-width="2.5" stroke-linecap="round" stroke-dasharray="14 10"/></svg>
          <div id="drop-body"></div>
          <input type="file" accept="video/*" id="file" aria-describedby="drop-help" />
        </label>
        <p class="help" id="drop-help" style="margin-top:12px;color:var(--ink-3);font-size:var(--t-s)">MP4 or MOV from a phone or camera. The whole court should be in view, filmed from behind one baseline.</p>
      </div>
      <div class="form-col">
        <fieldset>
          <legend>What was played</legend>
          <div class="seg" role="radiogroup">
            <label><input type="radio" name="mode" value="doubles" ${mode === 'doubles' ? 'checked' : ''}/><span class="dots" aria-hidden="true"><i></i><i></i><i></i><i></i></span>Doubles</label>
            <label><input type="radio" name="mode" value="singles" ${mode === 'singles' ? 'checked' : ''}/><span class="dots" aria-hidden="true"><i></i><i></i></span>Singles</label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Who played</legend>
          <p class="help" id="names-help"></p>
          <div class="teams" id="teams"></div>
        </fieldset>
        <p class="form-error" id="err" role="alert" hidden></p>
        <div class="form-actions">
          <button class="btn" type="submit"><span class="puck" aria-hidden="true"></span>Start analysis</button>
          <button class="linkish" type="button" id="sample">Use the sample video</button>
        </div>
      </div>
    </form>
  </div>`;

  const drop = v.querySelector('#drop');
  const frame = v.querySelector('#drop-frame');
  const body = v.querySelector('#drop-body');
  const fileInput = v.querySelector('#file');
  const teams = v.querySelector('#teams');
  const help = v.querySelector('#names-help');
  const err = v.querySelector('#err');

  const sizeFrame = () => {
    const r = drop.getBoundingClientRect();
    frame.parentNode.setAttribute('viewBox', `0 0 ${r.width} ${r.height}`);
    frame.setAttribute('d', roughRect(r.width, r.height));
  };
  const ro = new ResizeObserver(sizeFrame);
  ro.observe(drop);

  function renderDrop() {
    body.innerHTML = fileName
      ? `<p class="big">Got it.</p><p class="file-name">${esc(fileName)}</p><p>Drop another file to replace it.</p>`
      : `<p class="big">Drop the match video here</p><p>or choose a file from this device</p><span class="btn ghost small" aria-hidden="true">Choose a video</span>`;
    fileInput.setAttribute('aria-label', fileName ? `Video chosen: ${fileName}. Choose another` : 'Choose a match video');
  }
  function renderTeams() {
    const n = mode === 'doubles' ? 2 : 1;
    help.textContent =
      mode === 'doubles'
        ? 'Put partners on the same team so we know who plays together. Order within a team doesn’t matter; you’ll check it after.'
        : 'One name each. You’ll check who is who once the video is read.';
    const col = (team, title, c) => `
      <div class="team-box" style="--c:var(${c})">
        <h3>${title}</h3>
        ${Array.from({ length: n }, (_, i) => {
          const val = (prev[team] && prev[team][i]) || '';
          return `<label class="field"><span>${n === 2 ? `Player ${i + 1}` : 'Name'}</span><input name="${team}-${i}" autocomplete="off" value="${esc(val)}" placeholder="Type a name"/></label>`;
        }).join('')}
      </div>`;
    teams.innerHTML = col('T1', mode === 'doubles' ? 'Blue team' : 'Blue side', '--blue') + col('T2', mode === 'doubles' ? 'Red team' : 'Red side', '--red');
  }
  renderDrop();
  renderTeams();

  v.querySelectorAll('input[name=mode]').forEach((r) =>
    r.addEventListener('change', () => {
      collect();
      mode = r.value;
      renderTeams();
    })
  );
  function collect() {
    for (const team of ['T1', 'T2']) {
      prev[team] = [...teams.querySelectorAll(`input[name^=${team}-]`)].map((i) => i.value.trim());
    }
  }
  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) {
      fileName = fileInput.files[0].name;
      renderDrop();
    }
  });
  ['dragenter', 'dragover'].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add('is-over');
    })
  );
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove('is-over')));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) {
      fileName = f.name;
      renderDrop();
    }
  });
  v.querySelector('#sample').addEventListener('click', async () => {
    fileName = `${mode}.mp4`;
    renderDrop();
    const { analysis } = await loadMatch(mode);
    collect();
    for (const team of ['T1', 'T2']) {
      const docNames = analysis.players.filter((p) => p.team === team).map((p) => p.name);
      prev[team] = (prev[team] || []).map((x, i) => x || docNames[i] || '');
      if (!prev[team].length) prev[team] = docNames;
    }
    renderTeams();
  });

  v.querySelector('#up').addEventListener('submit', async (e) => {
    e.preventDefault();
    collect();
    const n = mode === 'doubles' ? 2 : 1;
    const missing = [];
    if (!fileName) missing.push('a video');
    const empty = ['T1', 'T2'].flatMap((t) => (prev[t] || []).slice(0, n)).filter((x) => !x).length;
    if (empty) missing.push(empty === 1 ? 'one more name' : `${empty} more names`);
    if (missing.length) {
      err.hidden = false;
      err.textContent = `Add ${missing.join(' and ')} to start.`;
      return;
    }
    err.hidden = true;
    // first guess: team 1's names on T1 in id order, team 2's on T2
    const { analysis } = await loadMatch(mode);
    const assigned = {};
    for (const team of ['T1', 'T2']) {
      const ids = analysis.players.filter((p) => p.team === team).map((p) => p.id);
      ids.forEach((id, i) => (assigned[id] = prev[team][i]));
    }
    writeSession({ mode, key: mode, fileName, names: { T1: prev.T1.slice(0, n), T2: prev.T2.slice(0, n) }, assigned, confirmed: false });
    location.hash = '#/processing';
  });

  return () => ro.disconnect();
}

// ---------------------------------------------------------------- processing
const STAGES = [
  [0, 'Uploading the video'],
  [9, 'Finding the court'],
  [20, 'Tracking the players'],
  [44, 'Following the shuttle'],
  [64, 'Spotting every shot'],
  [80, 'Deciding the rallies'],
  [92, 'Adding up the numbers'],
];

function processing(v) {
  const s = session();
  v.innerHTML = `
  <div class="page">
    <div class="processing">
      <div>
        <p class="progress-num" aria-hidden="true"><span id="pnum">0</span><small>%</small></p>
        <div class="vh" role="progressbar" id="pbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-label="Analysis progress"></div>
        <p class="stage-label" id="plabel" aria-live="polite">${STAGES[0][1]}</p>
        <p style="margin:0;color:var(--ink-2)">${esc(s.fileName || 'Your video')}. You can leave this page; we'll keep going.</p>
        <ol class="stage-list" id="plist">${STAGES.map(([, l]) => `<li>${l}</li>`).join('')}</ol>
        <p style="margin-top:22px"><button class="linkish" id="skip">Skip the wait</button></p>
      </div>
      <svg class="trace-court" viewBox="-60 -60 1460 730" aria-hidden="true">
        <g id="printed" fill="none" stroke="#b9d3c2" stroke-width="5"></g>
        <path id="trace" fill="none" stroke="var(--blue)" stroke-width="10" stroke-linecap="round" stroke-linejoin="round" opacity=".9"/>
        <g id="puck"><circle r="26" fill="var(--red)"/><circle r="20" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="3"/></g>
      </svg>
    </div>
  </div>`;
  // court in centimetres / 1 (100 units per metre), length along x
  const X = (y) => y * 100;
  const Y = (x) => x * 100;
  const printed = v.querySelector('#printed');
  printed.innerHTML = `
    <rect x="0" y="0" width="1340" height="610" fill="var(--court-fill)"/>
    <path d="M0 0H1340V610H0Z M0 ${Y(0.46)}H1340 M0 ${Y(5.64)}H1340 M${X(4.72)} 0V610 M${X(8.68)} 0V610 M${X(0.76)} 0V610 M${X(12.64)} 0V610 M0 305H${X(4.72)} M${X(8.68)} 305H1340"/>
    <path d="M670 -25V635" stroke="var(--ink)" stroke-width="7"/>`;
  // the marker traces the court: outline, net, service lines
  const d = `M0 0H1340V610H0V0 M670 -25V635 M${X(4.72)} 0V610 M${X(8.68)} 610V0 M0 305H${X(4.72)} M1340 305H${X(8.68)}`;
  const trace = v.querySelector('#trace');
  trace.setAttribute('d', d);
  const L = trace.getTotalLength();
  trace.style.strokeDasharray = `${L} ${L}`;
  trace.style.strokeDashoffset = `${L}`;
  const puck = v.querySelector('#puck');

  const pnum = v.querySelector('#pnum');
  const pbar = v.querySelector('#pbar');
  const plabel = v.querySelector('#plabel');
  const items = [...v.querySelectorAll('#plist li')];
  const total = 11000;
  let start = performance.now();
  let raf = 0;
  let done = false;
  let lastStage = -1;
  const frameFn = (n) => {
    const u = Math.max(0, Math.min(1, (n - start) / total));
    // uneven pace: tracking and shuttle take longest
    const p = Math.round(100 * (u < 0.5 ? Math.pow(u * 2, 1.15) / 2 : 0.5 + Math.pow((u - 0.5) * 2, 0.9) / 2));
    pnum.textContent = p;
    pbar.setAttribute('aria-valuenow', p);
    const si = STAGES.reduce((acc, [at], i) => (p >= at ? i : acc), 0);
    if (si !== lastStage) {
      plabel.textContent = STAGES[si][1];
      items.forEach((li, i) => {
        li.classList.toggle('done', i < si);
        li.classList.toggle('now', i === si);
      });
      lastStage = si;
    }
    trace.style.strokeDashoffset = `${L * (1 - p / 100)}`;
    const pt = trace.getPointAtLength(Math.max(0, L * (p / 100)));
    puck.setAttribute('transform', `translate(${pt.x} ${pt.y})`);
    if (u < 1) raf = requestAnimationFrame(frameFn);
    else finish();
  };
  function finish() {
    if (done) return;
    done = true;
    pnum.textContent = '100';
    plabel.textContent = 'Done. Next, check who is who.';
    items.forEach((li) => {
      li.classList.add('done');
      li.classList.remove('now');
    });
    setTimeout(() => {
      if (location.hash === '#/processing') location.hash = '#/names';
    }, 900);
  }
  raf = requestAnimationFrame(frameFn);
  v.querySelector('#skip').addEventListener('click', () => {
    start = performance.now() - total;
  });
  return () => cancelAnimationFrame(raf);
}

// ---------------------------------------------------------------- names
async function names(v) {
  const key = matchKey();
  const { analysis } = await loadMatch(key);
  const s = session();
  const assigned = s.key === key && s.assigned ? { ...s.assigned } : Object.fromEntries(analysis.players.map((p) => [p.id, p.name || p.id]));
  const teams = ['T1', 'T2'];
  const byTeam = (t) => analysis.players.filter((p) => p.team === t);
  const doubles = analysis.video.mode === 'doubles';
  let picked = null;

  v.innerHTML = `
  <div class="page">
    <div class="page-head">
      <h1>Who's who?</h1>
      <p>Here is each player we found, with our guess at their name. If two are the wrong way round, tap one picture and then the other to swap them.</p>
    </div>
    <div class="names-grid" id="ng"></div>
    <p class="names-hint" id="hint" aria-live="polite"></p>
    <div class="names-actions">
      <button class="btn" id="ok"><span class="puck" aria-hidden="true"></span>These are right</button>
      <span style="color:var(--ink-3);font-size:var(--t-s)">You can still fix a single rally later, from the rally list.</span>
    </div>
  </div>`;
  const ng = v.querySelector('#ng');
  const hint = v.querySelector('#hint');
  const tilts = [-1.6, 1.2, 0.8, -1.1];

  function render(changed = []) {
    ng.innerHTML = teams
      .map((t, ti) => {
        const c = t === 'T1' ? '--blue' : '--red';
        return `<section class="names-team" style="--c:var(${c})">
          <h2>${doubles ? (t === 'T1' ? 'Blue team' : 'Red team') : t === 'T1' ? 'Blue side' : 'Red side'}</h2>
          <div class="people">
            ${byTeam(t)
              .map(
                (p, i) => `<button class="person" data-id="${p.id}" aria-pressed="${picked === p.id}" style="--tilt:${tilts[(ti * 2 + i) % 4]}deg">
                  <span class="pin" aria-hidden="true"></span>
                  <img src="${dataBase(key)}/players/${p.id}.jpg" alt="Player ${p.id.slice(1)} as seen in the video" loading="lazy"/>
                  <span class="tag">${esc(assigned[p.id] || 'No name')}</span>
                  <span class="pid">Player ${p.id.slice(1)} in the video</span>
                  ${picked === p.id ? `<svg class="loop" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true"><path d="${loopPath(50, 50, 47, 47, 9)}" fill="none" stroke="var(--ink)" stroke-width="1.6" vector-effect="non-scaling-stroke" stroke-linecap="round"/></svg>` : ''}
                </button>`
              )
              .join('')}
          </div>
        </section>`;
      })
      .join('');
    drawOn(ng.querySelectorAll('.loop path'), { duration: 380 });
    for (const id of changed) {
      const tag = ng.querySelector(`[data-id="${id}"] .tag`);
      if (tag && !prefersReducedMotion())
        tag.animate([{ transform: 'translateY(-8px)', opacity: 0 }, { transform: 'none', opacity: 1 }], { duration: 320, easing: 'ease-out' });
    }
  }
  render();

  ng.addEventListener('click', (e) => {
    const b = e.target.closest('.person');
    if (!b) return;
    const id = b.dataset.id;
    if (!picked) {
      picked = id;
      hint.textContent = `Now tap the player who should be ${assigned[id]}.`;
      render();
    } else if (picked === id) {
      picked = null;
      hint.textContent = '';
      render();
    } else {
      const a = picked;
      const ta = analysis.players.find((p) => p.id === a).team;
      const tb = analysis.players.find((p) => p.id === id).team;
      const changed = [a, id];
      if (ta === tb || !doubles) {
        [assigned[a], assigned[id]] = [assigned[id], assigned[a]];
        hint.textContent = `Swapped ${assigned[id]} and ${assigned[a]}.`;
      } else {
        // partners stay together: the other two swap as well
        const oa = byTeam(ta).find((p) => p.id !== a).id;
        const ob = byTeam(tb).find((p) => p.id !== id).id;
        [assigned[a], assigned[id]] = [assigned[id], assigned[a]];
        [assigned[oa], assigned[ob]] = [assigned[ob], assigned[oa]];
        changed.push(oa, ob);
        hint.textContent = `Swapped ${assigned[id]} and ${assigned[a]}. Partners stay together, so ${assigned[oa]} and ${assigned[ob]} swapped too.`;
      }
      picked = null;
      render(changed);
      ng.querySelector(`[data-id="${id}"]`).focus();
    }
  });

  v.querySelector('#ok').addEventListener('click', () => {
    writeSession({ key, mode: key, assigned, confirmed: true });
    location.hash = '#/match/watch';
  });
  void displayNames;
}

// start once every screen's constants exist
route();
