// Router and the flow screens: landing, upload, processing, name confirmation.
import { state, load, setMatch, nameOf, teamName, fastestShot, clock, esc, reducedMotion, label } from './data.js';
import { simulate } from './physics.js';

const main = document.getElementById('main');
let cleanup = null;

const routes = {
  '': landing,
  upload,
  processing,
  names,
  match: matchPage,
};

function parseHash() {
  const h = location.hash.replace(/^#\/?/, '');
  const [route, sub] = h.split('/');
  return { route: route || '', sub: sub || '' };
}

async function render() {
  const { route, sub } = parseHash();
  // A tab change within the match page keeps the page and only swaps the panel.
  if (route === 'match' && main.dataset.route === 'match' && main._switchTab) {
    main._switchTab(sub || 'watch');
    return;
  }
  if (cleanup) {
    try {
      cleanup();
    } catch (e) {
      console.error(e);
    }
    cleanup = null;
  }
  main._switchTab = null;
  main.dataset.route = route;
  document.body.dataset.route = route || 'landing';
  main.innerHTML = '';
  window.scrollTo(0, 0);
  const view = routes[route] || landing;
  try {
    cleanup = (await view(main, sub)) || null;
  } catch (e) {
    console.error(e);
    main.innerHTML = `<section class="page narrow"><h1 class="h1">This page could not load</h1>
      <p class="lede">${esc(e.message)}. Check that the prototype server is running from <code>design/prototypes</code>, then reload.</p></section>`;
  }
  updateNav(route);
}

function updateNav(route) {
  document.querySelectorAll('[data-nav]').forEach((a) => {
    a.toggleAttribute('aria-current', a.dataset.nav === route);
  });
}

window.addEventListener('hashchange', render);
render();

// ---------------------------------------------------------------- landing

async function landing(root) {
  root.innerHTML = `
  <section class="hero" data-hero>
    <div class="hero-pin">
      <canvas class="hero-canvas" aria-hidden="true"></canvas>
      <div class="hero-copy">
        <h1 class="display">Every shot of your match, measured.</h1>
        <p class="lede">Upload a club match or a highlight reel. Featherweight finds the court, follows the shuttle and gives you back every rally, stroke and speed.</p>
        <div class="actions">
          <a class="btn btn-primary" href="#/upload">Analyse a match</a>
          <a class="btn btn-quiet" href="#/match/watch">Open the sample match</a>
        </div>
      </div>
      <div class="readout" data-readout>
        <p class="readout-kicker" data-kicker>The fastest shot in the sample match</p>
        <div class="readout-num"><span class="num" data-speed>0</span><span class="unit">km/h</span></div>
        <svg class="decay" viewBox="0 0 260 96" aria-hidden="true">
          <line class="axis" x1="0" y1="88" x2="260" y2="88"/>
          <line class="axis" x1="0" y1="4" x2="0" y2="88"/>
          <path class="decay-line" data-decay d=""/>
          <circle class="decay-dot" data-dot r="3" cx="0" cy="4"/>
          <text class="decay-t" x="0" y="96" data-t0>0 s</text>
          <text class="decay-t end" x="260" y="96" data-t1></text>
        </svg>
        <p class="readout-cap" data-cap></p>
      </div>
      <button class="launch" type="button" data-launch>
        <span class="launch-line" aria-hidden="true"></span><span data-launch-label>Launch the shuttle</span>
      </button>
    </div>
  </section>
  <section class="steps page">
    <h2 class="h2">From video to analysis</h2>
    <ol class="step-list">
      <li><span class="step-n num">1</span><h3>Upload the video</h3><p>A full game or a highlight reel, filmed from behind one baseline. Type the players' names, partners together.</p></li>
      <li><span class="step-n num">2</span><h3>Let it run</h3><p>We find the court, track each player, follow the shuttle and split the match into rallies. A full match takes a few minutes.</p></li>
      <li><span class="step-n num">3</span><h3>Confirm who is who</h3><p>Tap two pictures to swap names if we guessed wrong. Then watch the match with the overlay, or read the analysis.</p></li>
    </ol>
    <div class="steps-cta"><a class="btn btn-primary" href="#/upload">Analyse a match</a></div>
  </section>`;

  const hero = root.querySelector('[data-hero]');
  const canvas = root.querySelector('.hero-canvas');
  const speedEl = root.querySelector('[data-speed]');
  const capEl = root.querySelector('[data-cap]');
  const kickerEl = root.querySelector('[data-kicker]');
  const readout = root.querySelector('[data-readout]');
  const decay = root.querySelector('[data-decay]');
  const dot = root.querySelector('[data-dot]');
  const t1 = root.querySelector('[data-t1]');
  const launchBtn = root.querySelector('[data-launch]');
  const launchLabel = root.querySelector('[data-launch-label]');
  const still = reducedMotion();
  if (still) hero.classList.add('is-still');

  const { analysis } = await load();
  const best = fastestShot(analysis);
  if (!best) {
    readout.hidden = true;
    return null;
  }
  let heroApi = null;
  let flight = null;
  try {
    const mod = await import('./hero.js');
    flight = mod.planFlight(best);
    heroApi = mod.createHero(canvas, flight, { onFrame: frame });
    heroApi.setStill(still);
  } catch (e) {
    console.error(e);
    hero.classList.add('no-3d');
  }

  const f = best.shot.flight;
  const who = nameOf(analysis, best.shot.hitter_id);
  const fam = label(best.shot.family || 'shot').toLowerCase();
  const dur = flight ? flight.duration : 0.4;
  t1.textContent = `${dur.toFixed(2)} s`;
  const vmax = f.initial_speed_kmh;
  const X = (t) => (t / dur) * 260;
  const Y = (v) => 88 - (v / vmax) * 84;
  const finalCap = `${esc(who)}'s ${fam}, ${clock(best.shot.time_s)} into the ${state.match} sample. It left the racket at about ${Math.round(vmax)} km/h, was down to ${Math.round(f.speed_settled_kmh)} km/h a tenth of a second later, and reached the other side at about ${flight ? Math.round(flight.world[flight.world.length - 1].v) : '–'} km/h.`;

  let lastP = -1;
  function frame({ p, fl, speed, t }) {
    readout.style.setProperty('--show', Math.min(1, Math.max(0, (p - 0.2) / 0.1)).toFixed(3));
    hero.style.setProperty('--fade', Math.max(0, 1 - p * 2.2, (p - 0.88) / 0.12).toFixed(3));
    speedEl.textContent = Math.round(speed);
    if (Math.abs(p - lastP) < 0.0005) return;
    lastP = p;
    if (fl > 0 && flight) {
      const d = [];
      for (const q of flight.world) {
        if (q.t > t) break;
        d.push(`${d.length ? 'L' : 'M'}${X(q.t).toFixed(1)},${Y(q.v).toFixed(1)}`);
      }
      decay.setAttribute('d', d.join(''));
      dot.setAttribute('cx', X(t).toFixed(1));
      dot.setAttribute('cy', Y(speed).toFixed(1));
    } else {
      decay.setAttribute('d', '');
      dot.setAttribute('cx', 0);
      dot.setAttribute('cy', Y(speed).toFixed(1));
    }
    kickerEl.textContent = fl > 0 ? `Off the racket at ${Math.round(vmax)} km/h. ${p >= 0.88 ? 'On arrival:' : 'Now:'}` : 'The fastest shot in the sample match';
    capEl.innerHTML = p >= 0.9 ? finalCap : 'Measured from the video by fitting a flight with gravity and drag. Speeds are approximate.';
    launchLabel.textContent = p >= 0.9 ? 'Launch it again' : 'Launch the shuttle';
  }

  // Scroll scrubs the launch while the hero is pinned.
  function progressFromScroll() {
    const r = hero.getBoundingClientRect();
    const range = r.height - window.innerHeight;
    if (range <= 0) return null;
    return Math.min(1, Math.max(0, -r.top / range));
  }
  let stillP = 0;
  function onScroll() {
    document.body.classList.toggle('bar-solid', hero.getBoundingClientRect().bottom < window.innerHeight - 20);
    if (!heroApi) return;
    if (still) return;
    const p = progressFromScroll();
    if (p != null) heroApi.setProgress(p);
  }
  window.addEventListener('scroll', onScroll, { passive: true });

  let auto = null;
  function launch() {
    if (!heroApi) return;
    if (still) {
      stillP = stillP >= 1 ? 0 : 1;
      heroApi.setProgress(stillP);
      heroApi.renderOnce();
      return;
    }
    const r = hero.getBoundingClientRect();
    const range = r.height - window.innerHeight;
    const top0 = window.scrollY + r.top;
    const from = progressFromScroll() >= 0.98 ? 0 : progressFromScroll();
    if (from === 0) window.scrollTo(0, top0);
    const t0 = performance.now();
    const ms = 4200 * (1 - from);
    cancelAnimationFrame(auto);
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      const e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
      window.scrollTo(0, top0 + range * (from + (1 - from) * e));
      if (k < 1) auto = requestAnimationFrame(step);
    };
    auto = requestAnimationFrame(step);
  }
  launchBtn.addEventListener('click', launch);
  canvas.addEventListener('click', launch);
  const stopAuto = () => cancelAnimationFrame(auto);
  window.addEventListener('wheel', stopAuto, { passive: true });
  window.addEventListener('touchstart', stopAuto, { passive: true });

  // Pause the renderer when the hero is off screen or the tab is hidden.
  let visible = true;
  const io = new IntersectionObserver(([en]) => {
    visible = en.isIntersecting;
    sync();
  });
  io.observe(canvas);
  const sync = () => {
    if (!heroApi) return;
    if (visible && !document.hidden && !still) heroApi.start();
    else heroApi.stop();
  };
  document.addEventListener('visibilitychange', sync);
  if (heroApi) {
    heroApi.setProgress(still ? 0 : progressFromScroll() || 0);
    heroApi.renderOnce();
    sync();
  }

  return () => {
    document.body.classList.remove('bar-solid');
    window.removeEventListener('scroll', onScroll);
    window.removeEventListener('wheel', stopAuto);
    window.removeEventListener('touchstart', stopAuto);
    document.removeEventListener('visibilitychange', sync);
    cancelAnimationFrame(auto);
    io.disconnect();
    heroApi && heroApi.dispose();
  };
}

// ---------------------------------------------------------------- upload

function courtBackdrop(orient) {
  // hairline court for the names form; landscape: x along the court
  if (orient === 'landscape') {
    return `<svg class="form-court landscape" viewBox="-0.3 -0.3 14 6.7" preserveAspectRatio="none" aria-hidden="true">
      <rect x="0" y="0" width="13.4" height="6.1"/>
      <line x1="0" y1="0.46" x2="13.4" y2="0.46"/><line x1="0" y1="5.64" x2="13.4" y2="5.64"/>
      <line x1="0.76" y1="0" x2="0.76" y2="6.1"/><line x1="12.64" y1="0" x2="12.64" y2="6.1"/>
      <line x1="4.72" y1="0" x2="4.72" y2="6.1"/><line x1="8.68" y1="0" x2="8.68" y2="6.1"/>
      <line x1="0" y1="3.05" x2="4.72" y2="3.05"/><line x1="8.68" y1="3.05" x2="13.4" y2="3.05"/>
      <line class="net" x1="6.7" y1="-0.25" x2="6.7" y2="6.35"/></svg>`;
  }
  return `<svg class="form-court portrait" viewBox="-0.3 -0.3 6.7 14" preserveAspectRatio="none" aria-hidden="true">
      <rect x="0" y="0" width="6.1" height="13.4"/>
      <line x1="0.46" y1="0" x2="0.46" y2="13.4"/><line x1="5.64" y1="0" x2="5.64" y2="13.4"/>
      <line x1="0" y1="0.76" x2="6.1" y2="0.76"/><line x1="0" y1="12.64" x2="6.1" y2="12.64"/>
      <line x1="0" y1="4.72" x2="6.1" y2="4.72"/><line x1="0" y1="8.68" x2="6.1" y2="8.68"/>
      <line x1="3.05" y1="0" x2="3.05" y2="4.72"/><line x1="3.05" y1="8.68" x2="3.05" y2="13.4"/>
      <line class="net" x1="-0.25" y1="6.7" x2="6.35" y2="6.7"/></svg>`;
}

async function upload(root) {
  const u = state.upload;
  if (!u.mode) u.mode = state.match;
  root.innerHTML = `
  <section class="page upload">
    <header class="page-head">
      <h1 class="h1">Analyse a match</h1>
      <p class="lede">One video, the players' names, and a few minutes.</p>
    </header>
    <form class="upload-form" novalidate>
      <div class="field-block">
        <h2 class="h3" id="video-h">Video</h2>
        <label class="drop" data-drop>
          <input type="file" accept="video/*" data-file aria-labelledby="video-h">
          <svg class="drop-glyph" viewBox="0 0 40 40" aria-hidden="true"><path d="M20 27V9M13 16l7-7 7 7M8 31h24"/></svg>
          <span class="drop-main" data-drop-main>Drop a match video here, or choose a file</span>
          <span class="drop-sub" data-drop-sub>MP4 or MOV. Filmed from behind one baseline works best.</span>
        </label>
        <button type="button" class="link" data-sample>Use the sample video instead</button>
      </div>
      <fieldset class="field-block">
        <legend class="h3">Match type</legend>
        <div class="seg" role="radiogroup">
          <label><input type="radio" name="mode" value="singles"><span>Singles</span></label>
          <label><input type="radio" name="mode" value="doubles"><span>Doubles</span></label>
        </div>
      </fieldset>
      <fieldset class="field-block">
        <legend class="h3">Players</legend>
        <p class="help" data-names-help></p>
        <div class="court-form" data-court-form>
          ${courtBackdrop('landscape')}${courtBackdrop('portrait')}
          <div class="half" data-team="T1">
            <p class="team-tag"><span class="swatch t1"></span>Team 1</p>
            <label class="name-field"><span class="sr">Team 1, player 1</span><input name="T1-0" autocomplete="off" placeholder="Name"></label>
            <label class="name-field partner"><span class="sr">Team 1, player 2</span><input name="T1-1" autocomplete="off" placeholder="Partner's name"></label>
          </div>
          <div class="half" data-team="T2">
            <p class="team-tag"><span class="swatch t2"></span>Team 2</p>
            <label class="name-field"><span class="sr">Team 2, player 1</span><input name="T2-0" autocomplete="off" placeholder="Name"></label>
            <label class="name-field partner"><span class="sr">Team 2, player 2</span><input name="T2-1" autocomplete="off" placeholder="Partner's name"></label>
          </div>
        </div>
      </fieldset>
      <p class="form-error" data-error role="alert"></p>
      <div class="form-actions">
        <button class="btn btn-primary" type="submit">Start analysis</button>
        <span class="help">You can correct names after the analysis too.</span>
      </div>
    </form>
  </section>`;

  const form = root.querySelector('form');
  const fileInput = root.querySelector('[data-file]');
  const drop = root.querySelector('[data-drop]');
  const dropMain = root.querySelector('[data-drop-main]');
  const dropSub = root.querySelector('[data-drop-sub]');
  const err = root.querySelector('[data-error]');
  const help = root.querySelector('[data-names-help]');

  const showFile = () => {
    if (!u.file) return;
    drop.classList.add('has-file');
    dropMain.textContent = u.file.name;
    dropSub.textContent = u.file.size ? `${(u.file.size / 1e6).toFixed(1)} MB. Choose another file to replace it.` : 'Sample video. Choose a file to use your own.';
  };
  const setMode = (mode) => {
    u.mode = mode;
    form.querySelector(`input[value="${mode}"]`).checked = true;
    form.dataset.mode = mode;
    help.textContent =
      mode === 'doubles'
        ? 'Two names per team, so the analysis knows who partners whom.'
        : 'One name per side.';
    form.querySelectorAll('.partner input').forEach((i) => (i.disabled = mode !== 'doubles'));
  };
  form.querySelectorAll('input[name="mode"]').forEach((r) => r.addEventListener('change', () => setMode(r.value)));
  setMode(u.mode);
  ['T1', 'T2'].forEach((t) => [0, 1].forEach((i) => (form[`${t}-${i}`].value = u.names[t][i] || '')));
  showFile();

  fileInput.addEventListener('change', () => {
    const f = fileInput.files[0];
    if (f) {
      u.file = { name: f.name, size: f.size };
      showFile();
    }
  });
  ['dragenter', 'dragover'].forEach((ev) =>
    drop.addEventListener(ev, (e) => {
      e.preventDefault();
      drop.classList.add('is-over');
    }),
  );
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove('is-over')));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) {
      u.file = { name: f.name, size: f.size };
      showFile();
    }
  });
  root.querySelector('[data-sample]').addEventListener('click', async () => {
    const { analysis } = await load(u.mode);
    u.file = { name: analysis.video.name, size: 0 };
    const byTeam = { T1: [], T2: [] };
    analysis.players.forEach((p) => byTeam[p.team].push(p.name));
    // Enter the names in a different order than the pipeline will guess,
    // so the confirmation step has something to fix.
    u.names = { T1: [...byTeam.T1].reverse().concat(['']).slice(0, 2), T2: [...byTeam.T2, ''].slice(0, 2) };
    ['T1', 'T2'].forEach((t) => [0, 1].forEach((i) => (form[`${t}-${i}`].value = u.names[t][i] || '')));
    showFile();
    err.textContent = '';
  });

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    ['T1', 'T2'].forEach((t) => [0, 1].forEach((i) => (u.names[t][i] = form[`${t}-${i}`].value.trim())));
    const need = u.mode === 'doubles' ? 2 : 1;
    const missing = ['T1', 'T2'].some((t) => u.names[t].slice(0, need).some((n) => !n));
    if (!u.file) {
      err.textContent = 'Add a video first: drop one in, choose a file, or use the sample video.';
      drop.focus();
      return;
    }
    if (missing) {
      err.textContent = need === 2 ? 'Add a name for all four players.' : 'Add a name for both players.';
      const firstEmpty = [...form.querySelectorAll('.name-field input:not(:disabled)')].find((i) => !i.value.trim());
      firstEmpty && firstEmpty.focus();
      return;
    }
    setMatch(u.mode);
    state.confirmed = null;
    location.hash = '#/processing';
  });
  return null;
}

// ---------------------------------------------------------------- processing

const STAGES = [
  ['Finding the court', 0.08],
  ['Tracking players', 0.3],
  ['Following the shuttle', 0.55],
  ['Detecting shots', 0.72],
  ['Deciding rallies', 0.86],
  ['Measuring shot speeds', 0.96],
  ['Putting the match together', 1],
];

async function processing(root) {
  const fileName = (state.upload.file && state.upload.file.name) || `${state.match}.mp4`;
  // A clear's flight, for the progress arc (side view, net in the middle).
  const pts = simulate(70, 40, 1.0, { maxX: 12.9, dt: 0.002 });
  const sx = (x) => 20 + ((x + 0.4) / 13.4) * 560;
  const sy = (y) => 200 - y * 25;
  const d = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join('');
  root.innerHTML = `
  <section class="page processing">
    <p class="file-name">${esc(fileName)}</p>
    <div class="progress-num" aria-hidden="true"><span class="num" data-pct>0</span><span class="unit">%</span></div>
    <p class="stage" data-stage aria-live="polite">Starting</p>
    <div class="sr" role="progressbar" aria-label="Analysis progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" data-bar></div>
    <svg class="arc" viewBox="0 0 600 220" aria-hidden="true">
      <line class="floor" x1="20" y1="200" x2="580" y2="200"/>
      <line class="netl" x1="300" y1="200" x2="300" y2="${sy(1.55)}"/>
      <line class="netl thin" x1="300" y1="${sy(1.524)}" x2="300" y2="${sy(0.76)}"/>
      <path class="ghost" d="${d}"/>
      <path class="done" data-done d="${d}"/>
      <circle class="head" data-head r="4.5" cx="${sx(0)}" cy="${sy(1)}"/>
    </svg>
    <p class="help">A full match takes a few minutes. You can leave this page; the match will be ready in your list.</p>
    <div class="form-actions"><a class="link" href="#/names">Skip ahead (prototype)</a></div>
  </section>`;
  const pctEl = root.querySelector('[data-pct]');
  const stageEl = root.querySelector('[data-stage]');
  const bar = root.querySelector('[data-bar]');
  const done = root.querySelector('[data-done]');
  const head = root.querySelector('[data-head]');
  const len = done.getTotalLength();
  done.style.strokeDasharray = `${len}`;
  const total = reducedMotion() ? 5000 : 9000;
  const t0 = performance.now();
  let raf = 0;
  let lastStage = '';
  const tick = (now) => {
    const k = Math.min(1, (now - t0) / total);
    // uneven progress, like real stages
    const v = Math.min(1, k + 0.035 * Math.sin(k * 9) * (1 - k));
    pctEl.textContent = Math.floor(v * 100);
    bar.setAttribute('aria-valuenow', Math.floor(v * 100));
    done.style.strokeDashoffset = `${len * (1 - v)}`;
    const pt = done.getPointAtLength(len * v);
    head.setAttribute('cx', pt.x);
    head.setAttribute('cy', pt.y);
    const st = STAGES.find(([, end]) => v <= end) || STAGES[STAGES.length - 1];
    if (st[0] !== lastStage) {
      lastStage = st[0];
      stageEl.textContent = st[0];
    }
    if (k < 1) raf = requestAnimationFrame(tick);
    else setTimeout(() => (location.hash = '#/names'), 600);
  };
  raf = requestAnimationFrame(tick);
  return () => cancelAnimationFrame(raf);
}

// ---------------------------------------------------------------- names

async function names(root) {
  const { analysis, base } = await load();
  const doubles = analysis.video.mode === 'doubles';
  // Guess: team 1's entered names on T1 in id order, team 2's on T2.
  const typed = state.upload.names;
  const guess = {};
  const byTeam = { T1: [], T2: [] };
  analysis.players.forEach((p) => byTeam[p.team].push(p.id));
  ['T1', 'T2'].forEach((t) =>
    byTeam[t].forEach((id, i) => {
      guess[id] = (typed[t] && typed[t][i]) || nameOf(analysis, id);
    }),
  );
  if (state.confirmed) Object.assign(guess, state.confirmed);
  let picked = null;

  root.innerHTML = `
  <section class="page names">
    <header class="page-head">
      <h1 class="h1">Who is who?</h1>
      <p class="lede">These are the people we found, with our guess at their names. If two are wrong, tap one and then the other to swap them.${doubles ? ' Partners stay together, so picking across teams swaps both pairs.' : ''}</p>
    </header>
    <div class="teams" data-teams></div>
    <p class="sr" aria-live="polite" data-live></p>
    <div class="form-actions">
      <button class="btn btn-primary" type="button" data-confirm>Confirm names</button>
      <span class="help">You can fix a single rally later from the Watch tab.</span>
    </div>
  </section>`;
  const teamsEl = root.querySelector('[data-teams]');
  const live = root.querySelector('[data-live]');

  function draw(changed = []) {
    teamsEl.innerHTML = ['T1', 'T2']
      .map(
        (t) => `
      <div class="team-col">
        <h2 class="h3"><span class="swatch ${t.toLowerCase()}"></span>${t === 'T1' ? 'Team 1' : 'Team 2'}</h2>
        <div class="people">
          ${byTeam[t]
            .map(
              (id) => `
            <button type="button" class="person ${picked === id ? 'is-picked' : ''} ${changed.includes(id) ? 'is-changed' : ''}" data-id="${id}" aria-pressed="${picked === id}">
              <span class="photo"><img src="${base}players/${id}.jpg" alt="" loading="lazy"></span>
              <span class="pname">${esc(guess[id])}</span>
              <span class="pmeta">${picked === id ? 'Now tap the person to swap with' : 'Tap to swap'}</span>
            </button>`,
            )
            .join('')}
        </div>
      </div>`,
      )
      .join('');
    teamsEl.querySelectorAll('.person').forEach((b) => b.addEventListener('click', () => pick(b.dataset.id)));
  }
  function pick(id) {
    if (!picked) {
      picked = id;
      draw();
      teamsEl.querySelector(`[data-id="${id}"]`).focus();
      live.textContent = `${guess[id]} picked. Choose who to swap with.`;
      return;
    }
    if (picked === id) {
      picked = null;
      draw();
      teamsEl.querySelector(`[data-id="${id}"]`).focus();
      return;
    }
    const a = picked;
    const b = id;
    const ta = analysis.players.find((p) => p.id === a).team;
    const tb = analysis.players.find((p) => p.id === b).team;
    let changed = [a, b];
    if (doubles && ta !== tb) {
      // keep partners together: swap the two teams' names
      const A = byTeam[ta];
      const B = byTeam[tb];
      const na = A.map((x) => guess[x]);
      const nb = B.map((x) => guess[x]);
      A.forEach((x, i) => (guess[x] = nb[i]));
      B.forEach((x, i) => (guess[x] = na[i]));
      changed = [...A, ...B];
      live.textContent = 'Swapped both pairs between the teams.';
    } else {
      [guess[a], guess[b]] = [guess[b], guess[a]];
      live.textContent = `Swapped. ${guess[a]} and ${guess[b]}.`;
    }
    picked = null;
    draw(changed);
    teamsEl.querySelector(`[data-id="${b}"]`).focus();
  }
  draw();
  root.querySelector('[data-confirm]').addEventListener('click', () => {
    state.confirmed = { ...guess };
    location.hash = '#/match/watch';
  });
  return null;
}

// ---------------------------------------------------------------- match page

async function matchPage(root, sub) {
  const ctx = await load();
  const { analysis } = ctx;
  const won = { T1: 0, T2: 0 };
  analysis.rallies.forEach((r) => r.outcome && r.outcome.winner_team && won[r.outcome.winner_team]++);
  root.innerHTML = `
  <section class="match">
    <header class="match-head page-wide">
      <div class="match-title">
        <p class="match-kind">${analysis.video.mode === 'doubles' ? 'Doubles' : 'Singles'}, ${esc(analysis.video.name)}, ${clock(analysis.video.duration_s)}</p>
        <h1 class="teams-line">
          <span class="tl t1"><span class="swatch t1"></span>${esc(teamName(analysis, 'T1'))}</span>
          <span class="tl t2"><span class="swatch t2"></span>${esc(teamName(analysis, 'T2'))}</span>
        </h1>
      </div>
      <div class="won-total" aria-label="Rallies won: team 1 ${won.T1}, team 2 ${won.T2}">
        <span class="num t1">${won.T1}</span><span class="won-sep"></span><span class="num t2">${won.T2}</span>
        <span class="won-label">rallies won</span>
      </div>
      <nav class="tabs" aria-label="Match views">
        <a href="#/match/watch" data-tab="watch">Watch</a>
        <a href="#/match/analysis" data-tab="analysis">Analysis</a>
      </nav>
    </header>
    <div class="panel" data-panel></div>
  </section>`;
  const panel = root.querySelector('[data-panel]');
  let current = null;
  let panelCleanup = null;
  async function switchTab(tab) {
    tab = tab === 'analysis' ? 'analysis' : 'watch';
    if (tab === current) return;
    current = tab;
    root.querySelectorAll('[data-tab]').forEach((a) => {
      if (a.dataset.tab === tab) a.setAttribute('aria-current', 'page');
      else a.removeAttribute('aria-current');
    });
    panelCleanup && panelCleanup();
    panelCleanup = null;
    panel.innerHTML = '';
    if (tab === 'watch') {
      const { mountWatch } = await import('./watch.js');
      panelCleanup = mountWatch(panel, ctx);
    } else {
      const { mountAnalysis } = await import('./analysis.js');
      panelCleanup = mountAnalysis(panel, ctx);
    }
  }
  root._switchTab = switchTab;
  main._switchTab = switchTab;
  await switchTab(sub || 'watch');
  return () => panelCleanup && panelCleanup();
}
