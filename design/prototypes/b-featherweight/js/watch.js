// Watch tab: the real video with a live, minimal overlay synced to the playhead.
import { state, nameOf, teamOf, teamMembers, teamName, invert3, apply3, clock, esc, label, shotLabel } from './data.js';
import { courtLines } from './court.js';

const firstWord = (s) => String(s).split(/\s+/)[0];

export function mountWatch(root, ctx) {
  const { analysis, base } = ctx;
  const A = analysis;
  const fps = A.video.fps;
  const doubles = A.video.mode === 'doubles';
  const dur = A.video.duration_s;
  const rallies = A.rallies;
  const views = A.court.views.map((v) => ({ ...v, inv: invert3(v.homography) }));
  const tracks = A.tracks;
  const trackById = Object.fromEntries(tracks.persons.map((p) => [p.person_id, p]));
  const teamShort = (t) => teamMembers(A, t).map((id) => firstWord(nameOf(A, id))).join(' & ');
  const ids = A.players.map((p) => p.id);

  // ---- swaps (UI only, applied to this overlay) ----
  const swapFor = (frame) => {
    for (const r of rallies) {
      const s = state.swaps[r.id];
      if (s && frame >= r.start_frame && frame <= r.end_frame) return s;
    }
    return null;
  };
  const mapId = (id, frame) => {
    const s = swapFor(frame);
    if (!s || !id) return id;
    if (id === s[0]) return s[1];
    if (id === s[1]) return s[0];
    return id;
  };

  root.innerHTML = `
  <div class="watch page-wide">
    <div class="watch-main">
      <div class="vbox" style="aspect-ratio:${A.video.width}/${A.video.height}" data-vbox>
        <video data-video src="${base}video.mp4" poster="${base}poster.jpg" playsinline preload="metadata"></video>
        <svg class="ring-layer" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">
          <polygon class="ring" data-ring points=""/>
          <g data-ticks></g>
        </svg>
        <div class="hit-tag" data-tag hidden><span class="swatch" data-tag-sw></span><span data-tag-name></span></div>
        <div class="hud hud-tl" data-hud-clock aria-hidden="true"></div>
        <div class="hud hud-tr on-video" data-hud-court aria-hidden="true"></div>
        <div class="hud hud-bl on-video" data-hud-shot aria-hidden="true"></div>
        <div class="hud hud-br on-video" data-hud-won aria-hidden="true"></div>
        <button class="bigplay" type="button" data-bigplay aria-label="Play">
          <svg viewBox="0 0 40 40" aria-hidden="true"><path d="M15 11l15 9-15 9z"/></svg>
        </button>
      </div>
      <div class="dock" aria-hidden="true">
        <div class="hud" data-dock-shot></div>
        <div class="hud" data-dock-court></div>
        <div class="hud" data-dock-won></div>
      </div>
      <div class="transport">
        <button type="button" class="tbtn" data-play aria-label="Play">
          <svg viewBox="0 0 20 20" aria-hidden="true"><path data-play-icon d="M6 4l10 6-10 6z"/></svg>
        </button>
        <span class="tc num" data-tc>0:00</span>
        <div class="timeline">
          <svg viewBox="0 0 1000 30" preserveAspectRatio="none" aria-hidden="true">
            <line class="tl-base" x1="0" y1="15" x2="1000" y2="15"/>
            ${rallies
              .map((r) => {
                const x = (r.start_s / dur) * 1000;
                const w = Math.max(2, ((r.end_s - r.start_s) / dur) * 1000);
                const t = r.outcome && r.outcome.winner_team ? r.outcome.winner_team.toLowerCase() : 'unk';
                return `<rect class="tl-r ${t}" x="${x.toFixed(1)}" y="9" width="${w.toFixed(1)}" height="12"/>`;
              })
              .join('')}
            <line class="tl-head" data-head x1="0" y1="2" x2="0" y2="28"/>
          </svg>
          <input type="range" min="0" max="${dur}" step="0.1" value="0" aria-label="Seek in the match" data-seek>
        </div>
        <span class="tc num dim">${clock(dur)}</span>
        <button type="button" class="tbtn text" data-overlay aria-pressed="true">Overlay</button>
      </div>
      <p class="legend"><span><span class="swatch t1"></span>${esc(teamName(A, 'T1'))} won the rally</span><span><span class="swatch t2"></span>${esc(teamName(A, 'T2'))} won the rally</span><span><span class="swatch unk"></span>Result unknown</span></p>
    </div>
    <aside class="rallies" aria-label="Rallies">
      <h2 class="h3">Rallies <span class="count">${rallies.length}</span></h2>
      <ol class="rally-list" data-list></ol>
    </aside>
  </div>`;

  const $ = (s) => root.querySelector(s);
  const video = $('[data-video]');
  const vbox = $('[data-vbox]');
  const ring = $('[data-ring]');
  const ticks = $('[data-ticks]');
  const tag = $('[data-tag]');
  const tagName = $('[data-tag-name]');
  const tagSw = $('[data-tag-sw]');
  const hudClock = $('[data-hud-clock]');
  const hudCourt = [$('[data-hud-court]'), $('[data-dock-court]')];
  const hudShot = [$('[data-hud-shot]'), $('[data-dock-shot]')];
  const hudWon = [$('[data-hud-won]'), $('[data-dock-won]')];
  const seek = $('[data-seek]');
  const head = $('[data-head]');
  const tc = $('[data-tc]');
  const playBtn = $('[data-play]');
  const playIcon = $('[data-play-icon]');
  const bigPlay = $('[data-bigplay]');
  const list = $('[data-list]');

  // ---- mini court: static lines once, dots updated ----
  const courtMarkup = `<svg class="mini" viewBox="-0.8 -0.6 7.7 14.6">
      ${courtLines()}
      <g data-land></g>
      ${ids.map((id) => `<g class="pl ${teamOf(A, id).toLowerCase()} ${teamMembers(A, teamOf(A, id)).indexOf(id) ? 'second' : 'first'}" data-pl="${id}"><circle r="0.34"/></g>`).join('')}
    </svg>`;
  hudCourt.forEach((el) => (el.innerHTML = courtMarkup));

  // ---- helpers over the document ----
  const viewAt = (frame) => views.find((v) => frame >= v.start_frame && frame < v.end_frame) || null;
  const sampleAt = (t) => Math.max(0, Math.min(tracks.sample_frames.length - 1, Math.round(t * tracks.rate_hz)));
  function posAt(id, t) {
    const tr = trackById[id];
    if (!tr) return null;
    const k = sampleAt(t);
    for (let d = 0; d <= 3; d++) {
      for (const j of [k - d, k + d]) {
        if (j >= 0 && j < tr.x.length && tr.x[j] != null && tr.y[j] != null) return { x: tr.x[j], y: tr.y[j] };
      }
    }
    return null;
  }
  function rallyAt(t) {
    for (let i = 0; i < rallies.length; i++) {
      const r = rallies[i];
      if (t >= r.start_s - 0.4 && t <= r.end_s + 1.2) return i;
    }
    return -1;
  }
  const lastBefore = (t) => {
    let j = -1;
    rallies.forEach((r, i) => r.end_s < t && (j = i));
    return j;
  };

  // ---- rally list ----
  function outcomeText(r) {
    const o = r.outcome;
    const last = r.shots[r.shots.length - 1];
    if (!o || !last) return 'Result unknown';
    const who = esc(nameOf(A, mapId(last.hitter_id, last.frame)));
    const what = label(shotLabel(last)).toLowerCase();
    if (o.reason === 'winner') return `${who}'s ${what} winner`;
    if (o.detail === 'net') return `${who}'s ${what} into the net`;
    if (o.detail === 'out') return `${who}'s ${what} went out`;
    return `Error by ${who} on a ${what}`;
  }
  function swapOptions(r) {
    if (!doubles) return [[ids[0], ids[1]]];
    return [teamMembers(A, 'T1'), teamMembers(A, 'T2')];
  }
  function renderList() {
    list.innerHTML = rallies
      .map((r, i) => {
        const t = r.outcome && r.outcome.winner_team;
        const s = state.swaps[r.id];
        const opts = swapOptions(r);
        return `<li class="rally-row ${t ? t.toLowerCase() : 'unk'}" data-i="${i}">
          <button type="button" class="rally-jump" data-jump="${i}">
            <span class="rn num">${i + 1}</span>
            <span class="rbody">
              <span class="rmeta"><span class="num">${clock(r.start_s)}</span><span>${r.shots.length} shots</span><span>${(r.end_s - r.start_s).toFixed(1)} s</span></span>
              <span class="rres"><span class="swatch ${t ? t.toLowerCase() : 'unk'}"></span><span class="sr">${t ? `Won by ${esc(teamShort(t))}.` : 'Winner unknown.'}</span>${outcomeText(r)}</span>
            </span>
          </button>
          <div class="swap ${s ? 'is-done' : ''}"><p class="swap-q">${doubles ? 'Two players mixed up in this rally?' : 'Players mixed up in this rally?'}</p>
            ${
              s
                ? `<p class="swap-done">Swapped ${esc(nameOf(A, s[0]))} and ${esc(nameOf(A, s[1]))} in this rally. <button type="button" class="link" data-undo="${r.id}">Undo</button></p>`
                : opts
                    .map(
                      (o) =>
                        `<button type="button" class="chip" data-swap="${r.id}" data-a="${o[0]}" data-b="${o[1]}">Swap ${esc(nameOf(A, o[0]))} and ${esc(nameOf(A, o[1]))}</button>`,
                    )
                    .join('')
            }
          </div>
        </li>`;
      })
      .join('');
  }
  renderList();
  list.addEventListener('click', (e) => {
    const j = e.target.closest('[data-jump]');
    if (j) {
      const r = rallies[+j.dataset.jump];
      video.currentTime = Math.max(0, r.start_s - 0.6);
      update(true);
      return;
    }
    const sw = e.target.closest('[data-swap]');
    if (sw) {
      state.swaps[sw.dataset.swap] = [sw.dataset.a, sw.dataset.b];
      renderList();
      update(true);
      list.querySelector(`[data-undo="${sw.dataset.swap}"]`)?.focus();
      return;
    }
    const un = e.target.closest('[data-undo]');
    if (un) {
      delete state.swaps[un.dataset.undo];
      const row = un.closest('.rally-row');
      renderList();
      update(true);
      list.querySelector(`.rally-row[data-i="${row.dataset.i}"] .chip`)?.focus();
    }
  });

  // ---- overlay ----
  let lastRallyIdx = -2;
  let overlayOn = true;
  function project(view, x, y) {
    const p = apply3(view.inv, x, y);
    return p ? [p[0] * 1000, p[1] * 1000] : null;
  }

  function setShotPanel(html) {
    hudShot.forEach((el) => {
      if (el._html !== html) {
        el.innerHTML = html;
        el._html = html;
      }
    });
  }

  function update(force = false) {
    const t = video.currentTime || 0;
    const frame = Math.round(t * fps);
    seek.value = t;
    head.setAttribute('x1', ((t / dur) * 1000).toFixed(1));
    head.setAttribute('x2', ((t / dur) * 1000).toFixed(1));
    tc.textContent = clock(t);

    const ri = rallyAt(t);
    const rally = ri >= 0 ? rallies[ri] : null;
    let shot = null;
    let si = -1;
    if (rally) {
      rally.shots.forEach((s, i) => {
        if (s.time_s <= t + 0.02) {
          shot = s;
          si = i;
        }
      });
    }

    // rally clock
    if (rally) {
      const el = Math.max(0, Math.min(t, rally.end_s) - rally.start_s);
      hudClock.innerHTML = `<dl class="readings">
        <div><dt>Rally</dt><dd class="num">${ri + 1}</dd></div>
        <div><dt>Shots</dt><dd class="num">${Math.max(0, si + 1)}</dd></div>
        <div><dt>Time</dt><dd class="num">${el.toFixed(1)}<small>s</small></dd></div></dl>`;
    } else {
      hudClock.innerHTML = `<p class="between">Between rallies</p>`;
    }

    // last shot
    if (shot) {
      const hid = mapId(shot.hitter_id, shot.frame);
      const team = hid ? teamOf(A, hid) : null;
      const f = shot.flight;
      let speed = '';
      if (f && f.quality === 'good' && f.initial_speed_kmh != null) {
        speed = `<p class="spd"><span class="num">${Math.round(f.initial_speed_kmh)}</span><span class="u">km/h, approx.</span></p>`;
      } else if (f && f.quality === 'speed_bound') {
        speed = `<p class="spd bound">Too fast to measure at ${Math.round(fps)} frames a second</p>`;
      }
      const side = shot.side ? `<span class="side">${shot.side}</span>` : '';
      setShotPanel(`<p class="stroke">${label(shotLabel(shot))}${side}</p>
        <p class="who"><span class="swatch ${team ? team.toLowerCase() : 'unk'}"></span>${esc(nameOf(A, hid))}</p>${speed}`);
    } else {
      setShotPanel(`<p class="stroke dim">No shot yet</p>`);
    }

    // rallies won so far
    const won = { T1: 0, T2: 0 };
    rallies.forEach((r) => {
      if (r.end_s <= t && r.outcome && r.outcome.winner_team) won[r.outcome.winner_team]++;
    });
    const wonHtml = `<p class="won-mini"><span class="swatch t1"></span><span class="num">${won.T1}</span><span class="swatch t2"></span><span class="num">${won.T2}</span></p><p class="won-cap">rallies won so far</p>`;
    hudWon.forEach((el) => el._html !== wonHtml && ((el.innerHTML = wonHtml), (el._html = wonHtml)));

    // mini court players and landing
    const hitterNow = shot ? mapId(shot.hitter_id, shot.frame) : null;
    hudCourt.forEach((el) => {
      ids.forEach((id) => {
        const g = el.querySelector(`[data-pl="${id}"]`);
        // tracks are stored under document ids; a swap relabels them
        const src = mapId(id, frame);
        const p = posAt(src, t);
        if (!p || !overlayOn) {
          g.style.display = 'none';
          return;
        }
        g.style.display = '';
        g.setAttribute('transform', `translate(${p.x.toFixed(2)},${p.y.toFixed(2)})`);
        g.classList.toggle('is-hitter', id === hitterNow);
      });
      const land = el.querySelector('[data-land]');
      let lr = rally;
      if (!lr) {
        const j = lastBefore(t);
        lr = j >= 0 ? rallies[j] : null;
      }
      const ls = lr && lr.shots[lr.shots.length - 1];
      const L = ls && ls.landing && ls.landing.position && ls.landing.time_s <= t + 0.05 ? ls.landing.position : null;
      const key = L ? `${L.x},${L.y}` : '';
      if (land._key !== key) {
        land._key = key;
        land.innerHTML = L
          ? `<g transform="translate(${L.x},${L.y})" class="landing"><line x1="-0.32" y1="-0.32" x2="0.32" y2="0.32"/><line x1="-0.32" y1="0.32" x2="0.32" y2="-0.32"/></g>`
          : '';
      }
    });

    // hitter highlight in the picture
    const view = viewAt(frame);
    const hp = hitterNow && rally && view && overlayOn ? posAt(shot.hitter_id, t) : null;
    if (hp) {
      const pts = [];
      for (let k = 0; k < 40; k++) {
        const a = (k / 40) * Math.PI * 2;
        const q = project(view, hp.x + Math.cos(a) * 0.45, hp.y + Math.sin(a) * 0.45);
        if (q) pts.push(q.map((v) => v.toFixed(1)).join(','));
      }
      ring.setAttribute('points', pts.join(' '));
      ticks.innerHTML = [0, 1, 2, 3]
        .map((k) => {
          const a = (k / 4) * Math.PI * 2 + Math.PI / 4;
          const p1 = project(view, hp.x + Math.cos(a) * 0.55, hp.y + Math.sin(a) * 0.55);
          const p2 = project(view, hp.x + Math.cos(a) * 0.8, hp.y + Math.sin(a) * 0.8);
          return p1 && p2 ? `<line class="tick" x1="${p1[0]}" y1="${p1[1]}" x2="${p2[0]}" y2="${p2[1]}"/>` : '';
        })
        .join('');
      const c = project(view, hp.x, hp.y);
      if (c) {
        tag.hidden = false;
        tag.style.left = `${c[0] / 10}%`;
        tag.style.top = `${c[1] / 10}%`;
        tagName.textContent = nameOf(A, hitterNow);
        tagSw.className = `swatch ${teamOf(A, hitterNow).toLowerCase()}`;
      }
    } else {
      ring.setAttribute('points', '');
      ticks.innerHTML = '';
      tag.hidden = true;
    }

    // keep the current rally visible in the list
    const cur = ri >= 0 ? ri : -1;
    if (cur !== lastRallyIdx || force) {
      list.querySelectorAll('.rally-row').forEach((li) => li.classList.toggle('is-current', +li.dataset.i === cur));
      if (cur >= 0 && cur !== lastRallyIdx) {
        const li = list.querySelector(`.rally-row[data-i="${cur}"]`);
        if (li && list.scrollHeight > list.clientHeight) {
          list.scrollTo({ top: li.offsetTop - 8, behavior: video.paused ? 'auto' : 'smooth' });
        }
      }
      lastRallyIdx = cur;
    }
  }

  // ---- playback ----
  let raf = 0;
  const loop = () => {
    update();
    if (!video.paused) raf = requestAnimationFrame(loop);
  };
  const setPlaying = () => {
    const playing = !video.paused;
    vbox.classList.toggle('is-playing', playing);
    playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    bigPlay.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    playIcon.setAttribute('d', playing ? 'M5 4h3.5v12H5zM11.5 4H15v12h-3.5z' : 'M6 4l10 6-10 6z');
    cancelAnimationFrame(raf);
    if (playing) raf = requestAnimationFrame(loop);
  };
  const toggle = () => (video.paused ? video.play().catch(() => {}) : video.pause());
  video.addEventListener('play', setPlaying);
  video.addEventListener('pause', setPlaying);
  video.addEventListener('seeked', () => update(true));
  video.addEventListener('loadedmetadata', () => update(true));
  video.addEventListener('click', toggle);
  playBtn.addEventListener('click', toggle);
  bigPlay.addEventListener('click', toggle);
  seek.addEventListener('input', () => {
    video.currentTime = +seek.value;
    update();
  });
  $('[data-overlay]').addEventListener('click', (e) => {
    overlayOn = !overlayOn;
    e.currentTarget.setAttribute('aria-pressed', overlayOn);
    vbox.classList.toggle('overlay-off', !overlayOn);
    update(true);
  });
  const onKey = (e) => {
    if (e.target.closest('input, button, a, textarea, select')) return;
    if (e.key === ' ' || e.key === 'k') {
      e.preventDefault();
      toggle();
    } else if (e.key === 'ArrowRight') video.currentTime = Math.min(dur, video.currentTime + 5);
    else if (e.key === 'ArrowLeft') video.currentTime = Math.max(0, video.currentTime - 5);
  };
  document.addEventListener('keydown', onKey);

  // start at the first rally so the overlay has something to show
  video.currentTime = Math.max(0, (rallies[0] ? rallies[0].start_s : 0) + 2.2);
  update(true);

  return () => {
    cancelAnimationFrame(raf);
    document.removeEventListener('keydown', onKey);
    video.pause();
    video.removeAttribute('src');
    video.load();
  };
}
