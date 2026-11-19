import { loadMatch, MATCH, asset, getState, setState, nameOf, firstName, teamName, teamPlayers, reducedMotion, esc, rallyNumber, labelText, outcomeText } from './data.js';

const main = document.getElementById('main');
let cleanup = [];
const onLeave = (fn) => cleanup.push(fn);
const qs = location.search;

export function toast(text) {
  const t = document.getElementById('toast');
  t.textContent = text;
  t.classList.add('show');
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => t.classList.remove('show'), 3200);
}

const routes = {
  '': landing,
  upload,
  processing,
  names,
  match: matchPage,
};

async function route() {
  cleanup.forEach((f) => { try { f(); } catch (e) { console.error(e); } });
  cleanup = [];
  const parts = location.hash.replace(/^#\/?/, '').split('/');
  const view = routes[parts[0]] ? parts[0] : '';
  document.body.dataset.view = view || 'landing';
  document.querySelectorAll('[data-nav]').forEach((a) => a.toggleAttribute('aria-current', a.dataset.nav === view));
  main.innerHTML = '';
  window.scrollTo(0, 0);
  await routes[view](parts.slice(1));
  if (view) main.focus({ preventScroll: true });
}
addEventListener('hashchange', route);
// the hall lights strike once per visit; later screens find them already on
const hall = document.getElementById('hall');
hall.addEventListener('animationstart', () => setTimeout(() => hall.classList.add('lit'), 2000), { once: true });
queueMicrotask(route); // after the whole module has run

/* ================= Landing ================= */
const PHONE = '(max-width: 760px)';
async function landing() {
  main.innerHTML = `
  <section class="hero" aria-labelledby="hero-title">
    <div class="hero-stage" id="stage">
      <div class="hero-fallback" style="background-image:url(${asset('poster.jpg')})"></div>
      <div class="hero-shade" aria-hidden="true"></div>
      <aside class="hero-readout" aria-label="The rally being replayed">
        <p class="readout-what" id="ro-what">Loading a rally</p>
        <div class="readout-row">
          <div class="readout-count"><span class="readout-num" id="ro-shot">0</span><span class="readout-unit" id="ro-of"></span></div>
          <div class="readout-stroke" id="ro-stroke"></div>
        </div>
        <p class="readout-hint"><span class="hint-mouse">Drag to look around the hall</span><span class="hint-touch">Swipe sideways to look around</span></p>
      </aside>
    </div>
    <div class="hero-copy">
      <h1 id="hero-title" class="hero-title"><span>Every rally,</span><span>back under</span><span>the lights</span></h1>
      <p class="hero-lede">Upload a video of your singles or doubles match. We find the court, follow every player and the shuttle, and give you each rally, stroke and speed to watch back.</p>
      <div class="hero-actions">
        <a class="btn btn-flood" href="#/upload">Analyse a match</a>
        <a class="link-quiet" href="#/match/watch">Open the sample match</a>
      </div>
    </div>
  </section>
  <section class="steps" aria-labelledby="steps-title">
    <h2 id="steps-title" class="section-title">From video to rally-by-rally in three steps</h2>
    <ol class="steps-list">
      <li><h3>Upload the video</h3><p>A whole game or a highlight reel, filmed from behind one end like a broadcast. Add the players' names.</p></li>
      <li><h3>Confirm who is who</h3><p>We show a picture of each person we found with the name we think fits. Tap two to swap them.</p></li>
      <li><h3>Watch and read the match</h3><p>Every rally with the hitter lit up, stroke and speed, plus where each of you stood, won and lost points.</p></li>
    </ol>
  </section>`;

  const match = await loadMatch();
  const stage = document.getElementById('stage');
  const what = document.getElementById('ro-what');
  const shotEl = document.getElementById('ro-shot');
  const ofEl = document.getElementById('ro-of');
  const strokeEl = document.getElementById('ro-stroke');
  let hero = null;
  const phoneMq = matchMedia(PHONE);
  async function build() {
    hero?.destroy();
    const { createHero } = await import('./hero.js');
    await Promise.all([document.fonts.load('800 100px Anybody'), document.fonts.load('600 40px Archivo')]).catch(() => {});
    if (!document.body.contains(stage)) return;
    hero = createHero(stage, match, {
      still: reducedMotion(),
      phone: phoneMq.matches,
      onShot: ({ index, total, shot, label, speed }) => {
        shotEl.textContent = index + 1;
        ofEl.textContent = ` of ${total} shots`;
        const who = shot.hitter_id ? firstName(match, shot.hitter_id) : 'Someone';
        strokeEl.textContent = `${who}, ${label.toLowerCase()}${speed?.kmh ? `, ${speed.kmh} km/h` : speed?.bound ? ', too fast to measure' : ''}`;
      },
    });
    const r = hero.rally;
    what.textContent = `Rally ${rallyNumber(r)} of ${teamName(match, 'T1')} v ${teamName(match, 'T2')}, rebuilt from the tracking`;
    stage.classList.add('live');
  }
  try {
    await build();
    const rebuild = () => build().catch(console.error);
    phoneMq.addEventListener('change', rebuild);
    onLeave(() => { phoneMq.removeEventListener('change', rebuild); hero?.destroy(); });
  } catch (e) {
    console.error(e);
    what.textContent = 'The 3D replay needs WebGL, so here is a still from the match instead.';
  }
}

/* ================= Upload ================= */
async function upload() {
  const s = getState();
  let mode = s.mode || MATCH;
  let file = s.fileName || null;
  const match = await loadMatch();
  const defaults = {
    T1: teamPlayers(match, 'T1').map((p) => p.name),
    T2: teamPlayers(match, 'T2').map((p) => p.name),
  };
  const entered = s.entered || null;

  main.innerHTML = `
  <section class="page upload" aria-labelledby="up-title">
    <h1 id="up-title" class="page-title">Analyse a match</h1>
    <div class="upload-grid">
    <form id="up-form" novalidate>
      <label class="drop" id="drop">
        <input type="file" id="file" accept="video/*" class="visually-hidden">
        <svg class="drop-lines" viewBox="0 0 610 300" preserveAspectRatio="none" aria-hidden="true">
          <rect x="1" y="1" width="608" height="298"/><line x1="46" y1="1" x2="46" y2="299"/><line x1="564" y1="1" x2="564" y2="299"/>
          <line x1="1" y1="40" x2="609" y2="40"/><line x1="305" y1="236" x2="305" y2="299"/><line x1="1" y1="236" x2="609" y2="236"/>
        </svg>
        <span class="drop-main" id="drop-main">${file ? esc(file) : 'Drop your match video here'}</span>
        <span class="drop-sub" id="drop-sub">${file ? 'Ready. Choose another file to replace it.' : 'or choose a file. MP4 or MOV, a whole game or a highlight reel.'}</span>
      </label>
      <button type="button" class="link-quiet" id="use-sample">Use the sample ${MATCH} video instead</button>

      <fieldset class="mode">
        <legend>What was played</legend>
        <label class="mode-opt"><input type="radio" name="mode" value="singles" ${mode === 'singles' ? 'checked' : ''}>
          <svg viewBox="0 0 40 70" aria-hidden="true"><rect x="2" y="2" width="36" height="66"/><line x1="2" y1="35" x2="38" y2="35"/><circle cx="20" cy="18" r="3.5"/><circle cx="20" cy="52" r="3.5"/></svg>
          <span>Singles<small>One player each side</small></span></label>
        <label class="mode-opt"><input type="radio" name="mode" value="doubles" ${mode === 'doubles' ? 'checked' : ''}>
          <svg viewBox="0 0 40 70" aria-hidden="true"><rect x="2" y="2" width="36" height="66"/><line x1="2" y1="35" x2="38" y2="35"/><circle cx="12" cy="18" r="3.5"/><circle cx="28" cy="22" r="3.5"/><circle cx="13" cy="50" r="3.5"/><circle cx="27" cy="54" r="3.5"/></svg>
          <span>Doubles<small>Two partners each side</small></span></label>
      </fieldset>

      <fieldset class="names-in">
        <legend>Who played</legend>
        <p class="hint" id="names-hint"></p>
        <div class="sides" id="sides"></div>
      </fieldset>
      <p class="form-error" id="form-error" role="alert"></p>
      <button class="btn btn-flood" type="submit">Start analysis</button>
    </form>
    <aside class="tips" aria-labelledby="tips-title">
      <svg viewBox="0 0 220 170" aria-hidden="true">
        <path class="tips-court" d="M62 20 H158 L196 132 H24 Z"/>
        <path class="tips-court-l" d="M110 20 V132 M43 76 H177"/>
        <path class="tips-cone" d="M110 164 L40 24 H180 Z"/>
        <circle class="tips-cam" cx="110" cy="160" r="6"/>
      </svg>
      <h2 id="tips-title">What works best</h2>
      <ul>
        <li>Filmed from behind one end, high enough to see all four corners of the court.</li>
        <li>A camera that stays still. Cuts between camera angles are fine.</li>
        <li>Anything from one rally to a whole match. Longer videos give fuller numbers.</li>
      </ul>
      <p>Analysis runs on our side, so you can close the page while it works.</p>
    </aside>
    </div>
  </section>`;

  const sides = document.getElementById('sides');
  const hint = document.getElementById('names-hint');
  function renderNames() {
    const per = mode === 'doubles' ? 2 : 1;
    hint.textContent = mode === 'doubles'
      ? 'Put partners on the same side so we know who plays together. The order within a side does not matter.'
      : 'Any order. You will match names to people after the analysis.';
    const val = (team, i) => esc(entered?.[team]?.[i] ?? (match.analysis.video.mode === mode ? defaults[team][i] ?? '' : ''));
    sides.innerHTML = ['T1', 'T2'].map((team, k) => `
      <div class="side side-${k + 1}">
        <h3>${mode === 'doubles' ? `Pair ${k + 1}` : `Player ${k + 1}`}</h3>
        ${Array.from({ length: per }, (_, i) => `
          <label class="field"><span>${mode === 'doubles' ? `Partner ${i + 1}` : 'Name'}</span>
          <input name="${team}-${i}" autocomplete="off" value="${val(team, i)}" required></label>`).join('')}
      </div>`).join('<div class="side-net" aria-hidden="true"></div>');
  }
  renderNames();

  const input = document.getElementById('file');
  const drop = document.getElementById('drop');
  const setFile = (name) => {
    file = name;
    document.getElementById('drop-main').textContent = name;
    document.getElementById('drop-sub').textContent = 'Ready. Choose another file to replace it.';
    drop.classList.add('has-file');
  };
  if (file) drop.classList.add('has-file');
  input.addEventListener('change', () => input.files[0] && setFile(input.files[0].name));
  ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
  drop.addEventListener('drop', (e) => { const f = e.dataTransfer.files[0]; if (f) setFile(f.name); });
  document.getElementById('use-sample').addEventListener('click', () => setFile(`${MATCH}.mp4 (sample)`));
  document.querySelectorAll('input[name=mode]').forEach((r) => r.addEventListener('change', () => { mode = r.value; renderNames(); }));

  document.getElementById('up-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const err = document.getElementById('form-error');
    const fd = new FormData(e.target);
    const names = { T1: [], T2: [] };
    for (const [k, v] of fd.entries()) if (/^T[12]-/.test(k)) names[k.slice(0, 2)].push(String(v).trim());
    if (!file) { err.textContent = 'Choose a video first, or use the sample video.'; return; }
    if ([...names.T1, ...names.T2].some((n) => !n)) { err.textContent = 'Fill in every name. Nicknames are fine.'; return; }
    if (mode !== match.analysis.video.mode) {
      err.textContent = `This prototype only has a ${match.analysis.video.mode} match to show. Switch to ${match.analysis.video.mode}, or open the prototype with ?match=${mode}.`;
      return;
    }
    // Guess: side 1's names on T1 in id order, side 2's on T2 (as the API does before confirmation).
    const guess = {};
    teamPlayers(match, 'T1').forEach((p, i) => (guess[p.id] = names.T1[i]));
    teamPlayers(match, 'T2').forEach((p, i) => (guess[p.id] = names.T2[i]));
    setState({ mode, fileName: file, entered: names, guess, names: null });
    location.hash = '#/processing';
  });
}

/* ================= Processing ================= */
const STAGES = [
  ['Finding the court', 'Locating the lines in every camera angle'],
  ['Tracking players', 'Following each person around the court'],
  ['Following the shuttle', 'Spotting the shuttle in every frame'],
  ['Detecting shots', 'Finding each contact and naming the stroke'],
  ['Deciding rallies', 'Working out where rallies start, end and who won them'],
];
async function processing() {
  const s = getState();
  main.innerHTML = `
  <section class="page processing" aria-labelledby="pr-title">
    <div class="lamps" aria-hidden="true">${STAGES.map(() => '<span class="lamp"><i></i></span>').join('')}</div>
    <div class="proc-court" aria-hidden="true"><div class="proc-pool" id="pool"></div></div>
    <div class="proc-copy">
      <h1 id="pr-title" class="visually-hidden">Analysing your match</h1>
      <p class="proc-file">${esc(s.fileName || `${MATCH}.mp4`)}</p>
      <div class="proc-num" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-labelledby="stage-name" id="bar"><span id="pct">0</span><small>%</small></div>
      <p class="proc-stage" id="stage-name">${STAGES[0][0]}</p>
      <p class="proc-detail" id="stage-detail">${STAGES[0][1]}</p>
      <p class="proc-note">You can close this page. We will keep going and the match will be waiting for you.</p>
      <button class="link-quiet" id="skip">Skip ahead (prototype)</button>
    </div>
  </section>`;
  const lamps = [...document.querySelectorAll('.lamp')];
  const pctEl = document.getElementById('pct');
  const bar = document.getElementById('bar');
  const name = document.getElementById('stage-name');
  const detail = document.getElementById('stage-detail');
  const pool = document.getElementById('pool');
  const DURATION = reducedMotion() ? 6000 : 11000;
  const start = performance.now();
  let raf, shown = -1;
  const done = () => { location.hash = '#/names'; };
  function tick() {
    const now = performance.now();
    // uneven pace: tracking and the shuttle take longest
    const lin = Math.min((now - start) / DURATION, 1);
    const p = lin < 0.5 ? lin * 1.1 : 0.55 + (lin - 0.5) * 0.9;
    const v = Math.round(Math.min(p, 1) * 100);
    pctEl.textContent = v;
    bar.setAttribute('aria-valuenow', v);
    const st = Math.min(Math.floor(Math.min(p, 0.999) * STAGES.length), STAGES.length - 1);
    lamps.forEach((l, i) => { l.classList.toggle('on', i < st || v === 100); l.classList.toggle('warming', i === st && v < 100); });
    if (st !== shown) { shown = st; name.textContent = STAGES[st][0]; detail.textContent = STAGES[st][1]; }
    pool.style.setProperty('--lit', Math.min(p, 1).toFixed(3));
    if (lin >= 1) { clearInterval(raf); name.textContent = 'Done'; detail.textContent = 'Next, check who is who.'; later = setTimeout(done, 700); }
  }
  let later;
  raf = setInterval(tick, 80);
  tick();
  document.getElementById('skip').addEventListener('click', done);
  onLeave(() => { clearInterval(raf); clearTimeout(later); });
}

/* ================= Name confirmation ================= */
async function names() {
  const match = await loadMatch();
  const st = getState();
  const people = match.analysis.players;
  const assigned = {};
  people.forEach((p) => (assigned[p.id] = st.names?.[p.id] || st.guess?.[p.id] || p.name));
  const partners = st.entered || { T1: people.filter((p) => p.team === 'T1').map((p) => assigned[p.id]), T2: people.filter((p) => p.team === 'T2').map((p) => assigned[p.id]) };
  let picked = null;

  main.innerHTML = `
  <section class="page names" aria-labelledby="nm-title">
    <h1 id="nm-title" class="page-title">Who is who?</h1>
    <p class="lede">These are the people we followed, with the names we think fit. If two are the wrong way round, tap one and then the other to swap their names.</p>
    <div class="lineup" id="lineup"></div>
    <p class="form-error" id="nm-error" role="alert"></p>
    <div class="names-actions"><button class="btn btn-flood" id="confirm">Names look right</button></div>
  </section>`;

  const lineup = document.getElementById('lineup');
  function render() {
    lineup.innerHTML = ['T1', 'T2'].map((team, k) => `
      <div class="lineup-side side-${k + 1}">
        <h2>Side ${k + 1}</h2>
        <div class="lineup-row">
        ${people.filter((p) => p.team === team).map((p) => `
          <button class="person ${picked === p.id ? 'picked' : ''}" data-id="${p.id}" aria-pressed="${picked === p.id}">
            <span class="person-photo"><img src="${asset(`players/${p.id}.jpg`)}" alt=""></span>
            <span class="person-name">${esc(assigned[p.id])}</span>
            <span class="person-hint">${picked === p.id ? 'Now tap who to swap with' : picked ? 'Swap with this person' : 'Tap to swap'}</span>
          </button>`).join('')}
        </div>
      </div>`).join('<div class="lineup-net" aria-hidden="true"></div>');
    // partners entered together must stay on one side
    const err = document.getElementById('nm-error');
    const split = match.analysis.video.mode === 'doubles' && ['T1', 'T2'].some((team) => {
      const pair = partners[team];
      const sides = pair.map((n) => people.find((p) => assigned[p.id] === n)?.team);
      return sides[0] !== sides[1];
    });
    err.textContent = split ? 'Partners you entered together are now on different sides. Swap them back so each pair stands together.' : '';
    document.getElementById('confirm').disabled = split;
  }
  lineup.addEventListener('click', (e) => {
    const b = e.target.closest('.person');
    if (!b) return;
    const id = b.dataset.id;
    if (!picked) picked = id;
    else if (picked === id) picked = null;
    else {
      [assigned[picked], assigned[id]] = [assigned[id], assigned[picked]];
      toast(`Swapped ${assigned[id]} and ${assigned[picked]}`);
      picked = null;
    }
    render();
    lineup.querySelector(`[data-id="${id}"]`)?.focus();
  });
  render();
  document.getElementById('confirm').addEventListener('click', () => {
    setState({ names: assigned });
    location.hash = '#/match/watch';
  });
}

/* ================= Match page ================= */
async function matchPage([tab = 'watch']) {
  const match = await loadMatch();
  const rallies = match.analysis.rallies;
  const won = { T1: 0, T2: 0 };
  rallies.forEach((r) => r.outcome?.winner_team && won[r.outcome.winner_team]++);
  const unknown = rallies.filter((r) => !r.outcome?.winner_team).length;
  const sideBlock = (team, k) => `
    <div class="sb-side sb-${k}">
      <div class="sb-faces">${teamPlayers(match, team).map((p) => `<img src="${asset(`players/${p.id}.jpg`)}" alt="">`).join('')}</div>
      <div class="sb-names">${teamPlayers(match, team).map((p) => `<span>${esc(nameOf(match, p.id))}</span>`).join('')}</div>
      <div class="sb-won"><span class="sb-num" data-won="${team}">${won[team]}</span><small>rallies won</small></div>
    </div>`;
  main.innerHTML = `
  <section class="matchpage" aria-labelledby="mp-title">
    <header class="scoreboard">
      <h1 id="mp-title" class="visually-hidden">${esc(teamName(match, 'T1'))} v ${esc(teamName(match, 'T2'))}</h1>
      ${sideBlock('T1', 1)}
      <div class="sb-mid"><span>${rallies.length} rallies</span>${unknown ? `<span>${unknown} with no result</span>` : ''}<span>${Math.round(match.analysis.video.duration_s / 60)} min of video</span></div>
      ${sideBlock('T2', 2)}
    </header>
    <nav class="tabs" aria-label="Match views">
      <a href="#/match/watch${''}" class="tab" ${tab === 'watch' ? 'aria-current="page"' : ''}>Watch</a>
      <a href="#/match/analysis" class="tab" ${tab === 'analysis' ? 'aria-current="page"' : ''}>Analysis</a>
    </nav>
    <div id="tab-body"></div>
  </section>`;
  const body = document.getElementById('tab-body');
  if (tab === 'analysis') {
    const { renderAnalysis } = await import('./analysis.js');
    renderAnalysis(body, match);
  } else {
    const { renderWatch } = await import('./watch.js');
    const off = renderWatch(body, match, { toast });
    onLeave(off);
  }
}

export { labelText, outcomeText, qs };
