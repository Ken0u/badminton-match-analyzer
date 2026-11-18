// Analysis: whole-clip statistics per side and per player, every number with its sample size.
import { asset, nameOf, teamName, teamPlayers, sideNumber, labelText, pct, enough, MIN_N, FUTURE, esc } from './data.js';
import { courtLines, W, L } from './court.js';

const MIN_SAMPLES = 100; // 10 s of 10 Hz track before a heatmap means anything

export function renderAnalysis(root, match) {
  const S = match.stats;
  const doubles = S.mode === 'doubles';
  const subjects = [{ key: 'clip', label: 'Whole match' }];
  if (doubles) {
    for (const t of S.teams) subjects.push({ key: t.team, label: teamName(match, t.team), side: sideNumber(t.team), kind: 'team' });
    for (const p of S.players) subjects.push({ key: p.person_id, label: nameOf(match, p.person_id), side: sideNumber(p.team), kind: 'player', photo: p.person_id });
  } else {
    // in singles a side is one player: use the team numbers, which add rallies won
    for (const t of S.teams) subjects.push({ key: t.team, label: nameOf(match, t.person_ids[0]), side: sideNumber(t.team), kind: 'team', photo: t.person_ids[0] });
  }
  let current = new URLSearchParams(location.hash.split('?')[1] || '').get('who') || (doubles ? 'T1' : 'T1');
  if (!subjects.some((s) => s.key === current)) current = 'clip';

  root.innerHTML = `
  <div class="analysis">
    <div class="who" role="tablist" aria-label="Whose numbers">
      ${subjects.map((s) => `<button role="tab" class="who-btn ${s.side ? `side-${s.side}` : ''} ${s.kind === 'player' ? 'is-player' : ''}" data-key="${s.key}" aria-selected="${s.key === current}">
        ${s.photo ? `<img src="${asset(`players/${s.photo}.jpg`)}" alt="">` : s.kind === 'team' ? teamPlayers(match, s.key).map((p) => `<img src="${asset(`players/${p.id}.jpg`)}" alt="">`).join('') : ''}
        <span>${esc(s.label)}</span></button>`).join('')}
    </div>
    ${S.warnings?.length ? `<div class="warn">${S.warnings.map((w) => `<p>${esc(w)}</p>`).join('')}</div>` : ''}
    <div id="an-body" role="tabpanel"></div>
  </div>`;

  const body = root.querySelector('#an-body');
  root.querySelector('.who').addEventListener('click', (e) => {
    const b = e.target.closest('.who-btn');
    if (!b) return;
    current = b.dataset.key;
    root.querySelectorAll('.who-btn').forEach((x) => x.setAttribute('aria-selected', String(x === b)));
    draw();
  });
  root.querySelector('.who').addEventListener('keydown', (e) => {
    if (!['ArrowRight', 'ArrowLeft'].includes(e.key)) return;
    const btns = [...root.querySelectorAll('.who-btn')];
    const i = btns.indexOf(document.activeElement);
    const n = btns[(i + (e.key === 'ArrowRight' ? 1 : -1) + btns.length) % btns.length];
    n.focus(); n.click();
  });

  function draw() {
    const subj = subjects.find((s) => s.key === current);
    const data = subj.key === 'clip' ? S.clip : subj.kind === 'team' ? S.teams.find((t) => t.team === subj.key) : S.players.find((p) => p.person_id === subj.key);
    const held = [];
    const ctx = { match, S, subj, data, held, doubles };
    const blocks = [
      courtCard(ctx), headline(ctx), shotMix(ctx), finishing(ctx), speeds(ctx), serveReceive(ctx),
      formation(ctx), patterns(ctx), rallyLength(ctx), future(ctx),
    ].filter(Boolean);
    body.innerHTML = `
      <div class="an-grid">${blocks.join('')}</div>
      ${held.length ? `<section class="held" aria-labelledby="held-title">
        <h2 id="held-title">Not enough play yet</h2>
        <p>These need at least ${MIN_N} examples before the numbers say anything, so we hold them back for ${esc(subj.label)}:</p>
        <ul>${held.map((h) => `<li><b>${esc(h[0])}</b> ${esc(h[1])}</li>`).join('')}</ul>
        <p class="held-tip">A longer video, or a whole game instead of highlights, fills these in.</p>
      </section>` : ''}`;
    wireCourt(body, ctx);
  }
  draw();
}

/* ---------------- court maps on a lit, tilted court ---------------- */
function courtCard({ subj, data, held }) {
  const modes = [];
  const pos = data.positions;
  if (pos && enough(pos.n, MIN_SAMPLES)) modes.push(['stood', 'Where they stood']);
  else if (pos) held.push(['Where they stood', `only ${(pos.n / 10).toFixed(0)} s of tracking`]);
  if (Array.isArray(data.contacts)) { if (enough(data.contacts.length)) modes.push(['hit', 'Where they hit from']); else held.push(['Where they hit from', `${data.contacts.length} contacts`]); }
  if (Array.isArray(data.landings)) { if (enough(data.landings.length)) modes.push(['ended', subj.key === 'clip' ? 'Where rallies ended' : 'Where their rallies ended']); else held.push(['Where rallies ended', `${data.landings.length} landings`]); }
  if (!modes.length) return null;
  return `<section class="an-court" aria-labelledby="map-title">
    <div class="map-head">
      <h2 id="map-title" class="an-title">On court</h2>
      <div class="seg" role="radiogroup" aria-label="Map">${modes.map(([k, l], i) => `<button role="radio" aria-checked="${i === 0}" data-map="${k}">${l}</button>`).join('')}</div>
    </div>
    <div class="lit-court" data-side="${subj.side || 0}">
      <div class="lit-floor"><div class="lit-tilt" id="lit-tilt"></div></div>
    </div>
    <p class="map-cap" id="map-cap"></p>
  </section>`;
}

function wireCourt(body, ctx) {
  const tilt = body.querySelector('#lit-tilt');
  if (!tilt) return;
  const cap = body.querySelector('#map-cap');
  const { data, subj } = ctx;
  const sideCls = subj.side ? `side-${subj.side}` : 'side-0';
  function show(mode) {
    let under = '', over = '', text = '';
    if (mode === 'stood') {
      const g = data.positions;
      let max = 0; g.counts.forEach((r) => r.forEach((c) => (max = Math.max(max, c))));
      for (let r = 0; r < g.counts.length; r++) for (let c = 0; c < g.counts[r].length; c++) {
        const v = g.counts[r][c]; if (!v) continue;
        const x = g.x_edges[c], y = g.y_edges[r];
        under += `<rect x="${x}" y="${y}" width="${g.x_edges[c + 1] - x + 0.02}" height="${g.y_edges[r + 1] - y + 0.02}" fill-opacity="${Math.pow(v / max, 0.65).toFixed(3)}"/>`;
      }
      under = `<g class="heat" filter="url(#soft)">${under}</g>`;
      text = `The brighter the mat, the longer they stood there. ${Math.round(g.seconds)} s of rallies, shown from their own end.`;
    } else if (mode === 'hit') {
      over = `<g class="dots ${sideCls}">${data.contacts.map((s) => `<circle cx="${s.x}" cy="${s.y}" r="0.13"/>`).join('')}</g>`;
      text = `Each dot is where their feet were when they hit: ${data.contacts.length} contacts, shown from their own end.`;
    } else {
      const ls = data.landings;
      const won = ls.filter((l) => l.result === 'winner').length, lost = ls.filter((l) => l.result === 'error').length;
      over = `<g class="lands">${ls.map((l) => `<g transform="translate(${l.x},${l.y})" class="${l.result || 'unknown'}">${l.result === 'error'
        ? '<circle r="0.24"/><path d="M-0.15 -0.15 L0.15 0.15 M0.15 -0.15 L-0.15 0.15"/>' : '<circle r="0.2"/>'}</g>`).join('')}</g>`;
      text = `Where the shuttle came down at the end of ${subj.key === 'clip' ? 'each rally' : 'their rallies'}: ${won} winners (filled) and ${lost} errors (crossed). Turned so the last hitter is at the near end.`;
    }
    tilt.innerHTML = `<svg viewBox="-1 -1 ${W + 2} ${L + 2}" class="court lit" aria-label="${esc(cap.textContent)}" role="img">
      <defs><filter id="soft" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="0.28"/></filter>
      <radialGradient id="matlight" cx="50%" cy="62%" r="60%"><stop offset="0" stop-color="#2a8a67"/><stop offset="1" stop-color="#123f31"/></radialGradient></defs>
      <rect x="-1" y="-1" width="${W + 2}" height="${L + 2}" fill="url(#matlight)" rx="0.1"/>
      <rect x="0" y="6.7" width="${W}" height="6.7" class="own-half"/>
      ${under}${courtLines({ width: 0.05 })}${over}</svg>`;
    cap.textContent = text;
    tilt.querySelector('svg').setAttribute('aria-label', text);
  }
  const seg = body.querySelectorAll('[data-map]');
  seg.forEach((b) => b.addEventListener('click', () => {
    seg.forEach((x) => x.setAttribute('aria-checked', String(x === b)));
    show(b.dataset.map);
  }));
  show(seg[0].dataset.map);
}

/* ---------------- headline numbers ---------------- */
function headline({ subj, data, held, S }) {
  const items = [];
  if (subj.key === 'clip') {
    const c = S.clip;
    items.push(big(c.rallies, 'rallies'), big(c.contacts, 'shots played'));
    if (enough(c.rally_shots.n)) items.push(big(fmt(c.rally_shots.median), 'shots in a typical rally', `half of the ${c.rally_shots.n} rallies were longer`));
    if (enough(c.rally_seconds.n)) items.push(big(fmt(c.rally_seconds.median, 1), 'seconds in a typical rally'));
  } else {
    if (data.rallies_won) {
      if (enough(data.rallies_won.n)) items.push(big(data.rallies_won.count, `of ${data.rallies_won.n} rallies won`, `${data.won_by_winner} with their own winners, ${data.won_by_opponent_error} on the other side's errors`));
      else held.push(['Rallies won', `${data.rallies_won.n} rallies with a known winner`]);
    }
    const f = data.finish;
    if (f && enough(f.ended)) items.push(big(`${f.winners.count}<i>/</i>${f.errors.count}`, 'winners and errors', `of the ${f.ended} rallies ${subj.kind === 'player' ? 'they' : 'this side'} finished`));
    else if (f) held.push(['Winners and errors', `${f.ended} rallies finished`]);
    const d = data.distance;
    if (d && d.tracked_s >= 30) {
      items.push(big(Math.round(d.total_m), 'metres covered', `${Math.round(d.per_minute_m)} m per minute of rally${subj.kind === 'team' && data.person_ids?.length > 1 ? ', both partners added together' : ''}`));
      if (d.coverage < 0.8) items.push(`<p class="fine">Tracked for ${pct(d.coverage)} of rally time, so the real distance is higher.</p>`);
    } else if (d) held.push(['Distance', `${Math.round(d.tracked_s)} s tracked`]);
  }
  if (!items.length) return null;
  const spark = subj.key !== 'clip' && data.distance && enough(data.distance.per_rally.filter((r) => r.covered).length) ? distanceStrip(data.distance) : '';
  return `<section class="an-head" aria-label="Headline numbers">${items.join('')}${spark}</section>`;
}
function big(value, label, note = '') {
  return `<div class="bignum"><span class="bn-v">${value}</span><span class="bn-l">${label}</span>${note ? `<span class="bn-n">${note}</span>` : ''}</div>`;
}
function fmt(v, d = 0) { return v == null ? '–' : Number(v).toFixed(d); }
function distanceStrip(d) {
  const rs = d.per_rally.filter((r) => r.covered);
  const max = Math.max(...rs.map((r) => r.metres));
  return `<figure class="dstrip"><div class="dstrip-bars">${rs.map((r) => `<span style="height:${(r.metres / max) * 100}%" title="${r.rally_id.replace('rally-', 'Rally ')}: ${Math.round(r.metres)} m"></span>`).join('')}</div>
    <figcaption>Metres per rally, in match order. Typical rally ${fmt(d.rally_m.median)} m, longest ${fmt(d.rally_m.max)} m.</figcaption></figure>`;
}

/* ---------------- shot mix ---------------- */
function shotMix({ data, held }) {
  const b = data.shots;
  if (!b) return null;
  if (!enough(b.shots)) { held.push(['Shot mix', `${b.shots} shots`]); return null; }
  const fams = Object.entries(b.families).filter(([, v]) => v.count > 0).sort((a, z) => z[1].count - a[1].count);
  const top = fams[0][1].share;
  const rows = fams.map(([k, v]) => {
    const fh = b.forehand_by_family?.[k];
    return `<li><span class="bar-l">${labelText(k)}</span>
      <span class="bar"><span class="bar-f" style="width:${(v.share / top) * 100}%"></span></span>
      <span class="bar-v">${v.count}<small>${pct(v.share)}</small></span>
      <span class="bar-x">${fh && enough(fh.n) ? `${pct(fh.share)} forehand` : ''}</span></li>`;
  }).join('');
  const sides = b.sides;
  return `<section class="an-sec an-mix" aria-labelledby="mix-t">
    <h2 id="mix-t" class="an-title">Strokes played</h2>
    <p class="an-sub">${b.shots} shots and ${b.serves} serves. ${pct(sides.forehand.share)} forehand, ${pct(sides.backhand.share)} backhand.</p>
    <ol class="bars">${rows}</ol></section>`;
}

/* ---------------- finishing ---------------- */
function finishing({ data, held }) {
  const f = data.finish;
  if (!f) return null;
  const rows = Object.entries(f.by_label).filter(([, v]) => enough(v.played)).sort((a, z) => z[1].played - a[1].played);
  const thin = Object.entries(f.by_label).filter(([, v]) => v.played > 0 && !enough(v.played)).map(([k]) => labelText(k).toLowerCase());
  if (rows.length < 2) { held.push(['Stroke by stroke', 'fewer than two strokes with 5 or more shots']); return null; }
  return `<section class="an-sec an-finish" aria-labelledby="fin-t">
    <h2 id="fin-t" class="an-title">How often each stroke kept the rally going</h2>
    <p class="an-sub">Kept in play: the share of shots that were not errors. Winners and errors only count shots that ended a rally.</p>
    <table class="tbl">
      <thead><tr><th scope="col">Stroke</th><th scope="col">Played</th><th scope="col">Kept in play</th><th scope="col">Winners</th><th scope="col">Errors</th></tr></thead>
      <tbody>${rows.map(([k, v]) => `<tr><th scope="row">${labelText(k)}</th><td>${v.played}</td>
        <td><span class="keep"><span style="width:${(v.consistency.share || 0) * 100}%"></span></span>${pct(v.consistency.share)}</td>
        <td>${v.winners || '–'}</td><td>${v.errors ? `${v.errors}<small>${[v.errors_net && `${v.errors_net} net`, v.errors_out && `${v.errors_out} out`].filter(Boolean).join(', ')}</small>` : '–'}</td></tr>`).join('')}</tbody>
    </table>
    ${thin.length ? `<p class="fine">Not shown, under ${MIN_N} shots: ${thin.join(', ')}.</p>` : ''}
  </section>`;
}

/* ---------------- speeds ---------------- */
function speeds({ data, held, S }) {
  const sp = data.speeds;
  if (!sp || !S.shot_flights) return null;
  const rows = Object.entries(sp).filter(([, v]) => enough(v.initial_kmh?.n)).sort((a, z) => z[1].initial_kmh.median - a[1].initial_kmh.median);
  if (!rows.length) { held.push(['Shot speeds', 'fewer than 5 measured shots of any stroke']); return null; }
  const MAX = 360;
  const tick = [0, 100, 200, 300];
  return `<section class="an-sec an-speed" aria-labelledby="sp-t">
    <h2 id="sp-t" class="an-title">Shot speed, roughly</h2>
    <p class="an-sub">Speed leaving the racket, estimated from the video. Good for comparing strokes in this match; any single number can be well off.</p>
    <ul class="speeds">${rows.map(([k, v]) => {
      const s = v.initial_kmh;
      return `<li><span class="sp-l">${labelText(k)}</span>
        <span class="sp-track"><span class="sp-range" style="left:${(s.p10 / MAX) * 100}%;width:${(Math.min(s.p90, MAX) - s.p10) / MAX * 100}%"></span><span class="sp-med" style="left:${(s.median / MAX) * 100}%"></span></span>
        <span class="sp-v">${Math.round(s.median)}<small> km/h</small></span>
        <span class="sp-n">${s.n} measured${v.speed_bound ? `, ${v.speed_bound} too fast to measure` : ''}</span></li>`;
    }).join('')}</ul>
    <div class="sp-axis" aria-hidden="true">${tick.map((t) => `<span style="left:${(t / MAX) * 100}%">${t}</span>`).join('')}</div>
    <p class="fine">The line is the middle speed, the band covers most shots. The hardest smashes are too fast for this frame rate to clock and are left out, so smash numbers run low.</p>
  </section>`;
}

/* ---------------- serve and receive ---------------- */
function serveReceive({ data, held }) {
  const sv = data.serve, rc = data.receive;
  if (!sv && !rc) return null;
  const parts = [];
  if (sv && enough(sv.serves)) {
    parts.push(`<div class="sr"><h3>Serving</h3>
      <p class="sr-big">${sv.serves}<small> serves</small></p>
      <dl>
        <div><dt>Short</dt><dd>${pct(sv.serve_types.short.share)}</dd></div>
        <div><dt>Long</dt><dd>${pct(sv.serve_types.long.share)}</dd></div>
        ${enough(sv.won.n) ? `<div><dt>Rallies won</dt><dd>${sv.won.count} of ${sv.won.n}</dd></div>` : ''}
        ${enough(sv.faults.n) ? `<div><dt>Faults</dt><dd>${sv.faults.count}</dd></div>` : ''}
      </dl></div>`);
  } else if (sv) held.push(['Serving', `${sv.serves} serves`]);
  if (rc && enough(rc.returns)) {
    const fams = Object.entries(rc.families).sort((a, z) => z[1].count - a[1].count).slice(0, 3);
    parts.push(`<div class="sr"><h3>Returning serve</h3>
      <p class="sr-big">${rc.returns}<small> returns</small></p>
      <dl>${fams.map(([k, v]) => `<div><dt>${labelText(k)}</dt><dd>${pct(v.share)}</dd></div>`).join('')}
      ${enough(rc.won.n) ? `<div><dt>Rallies won</dt><dd>${rc.won.count} of ${rc.won.n}</dd></div>` : ''}</dl></div>`);
  } else if (rc) held.push(['Returning serve', `${rc.returns} returns`]);
  if (!parts.length) return null;
  return `<section class="an-sec an-sr" aria-labelledby="sr-t"><h2 id="sr-t" class="an-title">Serve and return</h2><div class="sr-row">${parts.join('')}</div></section>`;
}

/* ---------------- doubles formation ---------------- */
function formation({ data, held, subj }) {
  const f = data.formation;
  if (!f || subj.kind !== 'team') return null;
  const atk = f.attacking, def = f.defending;
  const okA = enough(atk.front_back.n, 50), okD = enough(def.side_by_side.n, 50);
  if (!okA && !okD) { held.push(['Formation', `${Math.round(f.seconds)} s with both partners tracked`]); return null; }
  const diagram = (kind) => kind === 'fb'
    ? '<svg viewBox="0 0 40 36" aria-hidden="true"><rect x="2" y="2" width="36" height="32"/><line x1="2" y1="4" x2="38" y2="4" class="net"/><circle cx="20" cy="12" r="3.4"/><circle cx="20" cy="27" r="3.4"/></svg>'
    : '<svg viewBox="0 0 40 36" aria-hidden="true"><rect x="2" y="2" width="36" height="32"/><line x1="2" y1="4" x2="38" y2="4" class="net"/><circle cx="11" cy="20" r="3.4"/><circle cx="29" cy="20" r="3.4"/></svg>';
  return `<section class="an-sec an-form" aria-labelledby="fm-t">
    <h2 id="fm-t" class="an-title">How the pair lined up</h2>
    <div class="form-row">
      ${okA ? `<div class="form">${diagram('fb')}<p><b>${pct(atk.front_back.share)}</b> front and back when attacking</p><span class="fine">${Math.round(atk.front_back.n / 10)} s of attacking play</span></div>` : ''}
      ${okD ? `<div class="form">${diagram('sbs')}<p><b>${pct(def.side_by_side.share)}</b> side by side when defending</p><span class="fine">${Math.round(def.side_by_side.n / 10)} s of defending play</span></div>` : ''}
    </div></section>`;
}

/* ---------------- patterns ---------------- */
function patterns({ data, held, subj }) {
  const list = subj.key === 'clip' ? data.pairs : data.replies;
  if (!list) return null;
  const rows = list.filter((p) => p.count >= 3 && enough(p.n)).slice(0, 5);
  if (!rows.length) { held.push(['Patterns', 'no pair of strokes came up 3 times']); return null; }
  const intro = subj.key === 'clip' ? 'The strokes that most often followed each other.' : 'Their most common answers to the other side’s stroke.';
  return `<section class="an-sec an-pat" aria-labelledby="pt-t">
    <h2 id="pt-t" class="an-title">Patterns</h2><p class="an-sub">${intro}</p>
    <ol class="pat">${rows.map((p) => `<li><span class="pat-a">${labelText(p.labels[0])}</span><svg viewBox="0 0 40 12" aria-hidden="true"><path d="M2 10 Q20 -4 38 10"/></svg><span class="pat-b">${labelText(p.labels[1]).toLowerCase()}</span><span class="pat-n">${p.count} of ${p.n}</span></li>`).join('')}</ol>
  </section>`;
}

/* ---------------- rally length (whole match) ---------------- */
function rallyLength({ data, subj, held }) {
  if (subj.key !== 'clip') return null;
  const d = data.rally_shots;
  if (!enough(d.n)) { held.push(['Rally length', `${d.n} rallies`]); return null; }
  const max = Math.max(...d.counts, d.above);
  return `<section class="an-sec an-len" aria-labelledby="len-t">
    <h2 id="len-t" class="an-title">Rally length</h2>
    <p class="an-sub">Shots per rally across ${d.n} rallies. Typical: ${fmt(d.median)} shots.</p>
    <div class="hist" role="img" aria-label="Histogram of shots per rally">${d.counts.map((c, i) => `<span style="height:${(c / max) * 100}%" title="${i + 1} shots: ${c}"></span>`).join('')}<span class="above" style="height:${(d.above / max) * 100}%" title="Over 30 shots: ${d.above}"></span></div>
    <div class="hist-axis"><span>1</span><span>10</span><span>20</span><span>30+</span></div>
  </section>`;
}

/* ---------------- coming later: renders only when the data exists ---------------- */
function future({ data, subj }) {
  const skills = data.skills ?? (FUTURE && subj.key !== 'clip' ? fakeSkills(subj.key) : null);
  if (!skills) return null;
  const axes = ['attack', 'net_play', 'defence', 'consistency', 'movement', 'placement'];
  const names = { attack: 'Attack', net_play: 'Net play', defence: 'Defence', consistency: 'Consistency', movement: 'Movement', placement: 'Placement' };
  const R = 80, c = 100;
  const pt = (i, v) => { const a = -Math.PI / 2 + (i * Math.PI * 2) / 6; return [c + Math.cos(a) * R * v, c + Math.sin(a) * R * v]; };
  const ring = (v) => axes.map((_, i) => pt(i, v).join(',')).join(' ');
  return `<section class="an-sec an-future ${skills.preview ? 'is-preview' : ''}" aria-labelledby="fu-t">
    ${skills.preview ? '<p class="stamp">Preview with made-up numbers. This part is coming later.</p>' : ''}
    <h2 id="fu-t" class="an-title">Skill profile</h2>
    <div class="fu-row">
      <svg class="hex" viewBox="0 0 200 200" role="img" aria-label="Skill profile: ${axes.map((a) => `${names[a]} ${skills[a]}`).join(', ')}">
        ${[0.25, 0.5, 0.75, 1].map((v) => `<polygon class="hex-ring" points="${ring(v)}"/>`).join('')}
        ${axes.map((_, i) => `<line class="hex-axis" x1="${c}" y1="${c}" x2="${pt(i, 1)[0]}" y2="${pt(i, 1)[1]}"/>`).join('')}
        <polygon class="hex-val" points="${axes.map((a, i) => pt(i, skills[a] / 100).join(',')).join(' ')}"/>
        ${axes.map((a, i) => { const [x, y] = pt(i, 1.2); return `<text x="${x}" y="${y}" text-anchor="middle">${names[a]}</text>`; }).join('')}
      </svg>
      <div class="bw">
        <h3>Best shots</h3><ol>${skills.best.map((b) => `<li>${esc(b)}</li>`).join('')}</ol>
        <h3>Worth working on</h3><ol>${skills.worst.map((b) => `<li>${esc(b)}</li>`).join('')}</ol>
      </div>
    </div>
  </section>`;
}
function fakeSkills(key) {
  let h = 0; for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) % 997;
  const v = (k) => 45 + ((h * (k + 3)) % 45);
  return { preview: true, attack: v(1), net_play: v(2), defence: v(3), consistency: v(4), movement: v(5), placement: v(6),
    best: ['Smash from the back tramline, rally 11', 'Net kill after a tight net shot, rally 17'],
    worst: ['Lift that fell short, rally 8', 'Backhand drive into the net, rally 24'] };
}
