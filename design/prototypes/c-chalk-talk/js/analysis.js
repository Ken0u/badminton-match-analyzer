// Analysis: whole-clip statistics from stats.json, per team and per player.
// Numbers are drawn precisely; the marker voice is only in the annotations.
// A card whose data is null is left out; a card whose sample is thin (n < THIN)
// moves to the "needs more play" tray with the reason.

import { loadMatch, matchKey, displayNames, teamName, initials, firstName, label, cap, pct, esc, THIN, FUTURE, session, writeSession } from './data.js';
import { arrowPath, ringPath, crossPath, underlinePath } from './ink.js';

const HEX = { T1: '#1F57C3', T2: '#D3362D', ink: '#22262E', ink2: '#4A515C', mute: '#646B76', grid: '#E9ECEE', court: '#2E7D57', courtFill: '#E2EEE5' };
const TEAM_WORD = { T1: 'Blue', T2: 'Red' };

// Charts are drawn in their own units; on a phone they get a narrower drawing
// so the text inside keeps a readable size.
const MQ = matchMedia('(max-width: 600px)');
let NARROW = MQ.matches;

export async function renderAnalysis(v) {
  NARROW = MQ.matches;
  const onMq = () => location.hash.includes('analysis') && renderAnalysis(v);
  MQ.addEventListener('change', onMq, { once: true });
  const key = matchKey();
  const { analysis: A, stats: S } = await loadMatch(key);
  const names = displayNames(A);
  const doubles = S.mode === 'doubles';
  const s0 = session();
  let sel = (s0.analysisSel && s0.analysisSel[key]) || { kind: 'team', id: 'T1' };

  v.innerHTML = `
  <div class="page">
    <div class="match-head">
      <h1><span class="c-blue">${esc(teamName(A, 'T1', names))}</span> <span style="color:var(--ink-3);font-weight:600">v</span> <span class="c-red">${esc(teamName(A, 'T2', names))}</span></h1>
      <span class="meta">${doubles ? 'Doubles' : 'Singles'}, ${S.clip.rallies} rallies, ${S.clip.contacts} shots</span>
    </div>
    ${S.warnings.map((w) => `<p class="warn">${esc(w)}</p>`).join('')}
    <div id="clip"></div>
    <h2 class="section-title" id="sel-h">Team and player numbers</h2>
    <p class="section-sub">Pick a team or a player. Numbers with fewer than ${THIN} examples behind them are held back, because one or two shots say very little.</p>
    <div class="who-bar" id="who" role="group" aria-label="Show numbers for"></div>
    <div id="sel"></div>
    <div id="future"></div>
  </div>`;

  renderClip(v.querySelector('#clip'), S);
  const who = v.querySelector('#who');
  const selEl = v.querySelector('#sel');

  function renderWho() {
    who.innerHTML = ['T1', 'T2']
      .map((t) => {
        const team = S.teams.find((x) => x.team === t);
        const players = S.players.filter((p) => p.team === t);
        const c = HEX[t];
        const teamBtn = doubles
          ? `<button class="who-btn" data-kind="team" data-id="${t}" aria-pressed="${sel.kind === 'team' && sel.id === t}">
              <span class="mag pair" style="background:${c}">${players.map((p) => initials(names[p.person_id])[0]).join('')}</span>${esc(teamName(A, t, names))}</button>`
          : '';
        const pBtns = players
          .map(
            (p) =>
              `<button class="who-btn" data-kind="${doubles ? 'player' : 'team'}" data-id="${doubles ? p.person_id : t}" aria-pressed="${
                doubles ? sel.kind === 'player' && sel.id === p.person_id : sel.id === t
              }"><span class="mag" style="background:${c}">${esc(initials(names[p.person_id]))}</span>${esc(names[p.person_id])}</button>`
          )
          .join('');
        void team;
        return `<div class="who-group">${teamBtn}${pBtns}</div>`;
      })
      .join('');
  }
  function renderSel() {
    renderWho();
    selEl.innerHTML = '';
    selEl.appendChild(selection(S, A, sel, names, doubles));
  }
  who.addEventListener('click', (e) => {
    const b = e.target.closest('.who-btn');
    if (!b) return;
    sel = { kind: b.dataset.kind, id: b.dataset.id };
    const all = session().analysisSel || {};
    all[key] = sel;
    writeSession({ analysisSel: all });
    renderSel();
    who.querySelector(`[data-id="${sel.id}"]`).focus();
  });
  renderSel();

  if (FUTURE) v.querySelector('#future').innerHTML = futureSlot(S, names);
  else if (S.skills) v.querySelector('#future').innerHTML = futureSlot(S, names, S.skills);
  return () => MQ.removeEventListener('change', onMq);
}

// ---------------------------------------------------------------- clip
function renderClip(el, S) {
  const c = S.clip;
  const cards = [];
  const thin = [];
  const both = 'linear-gradient(90deg,#1F57C3 50%,#D3362D 50%)';

  if (c.rally_shots && c.rally_shots.n >= THIN) {
    cards.push(
      card({
        w: 4,
        owner: both,
        title: 'Rallies',
        sub: `${c.rallies} rallies in this video`,
        body: `<div class="big-num">${fmt(c.rally_shots.median)}<small>shots, typical rally</small></div>
          <dl class="kv" style="margin-top:14px">
            <dt>Typical length</dt><dd>${fmt(c.rally_seconds.median)} s</dd>
            <dt>Longest</dt><dd>${fmt(c.rally_shots.max)} shots</dd>
            <dt>Shots with no player found</dt><dd>${c.unattributed_contacts} of ${c.contacts}</dd>
          </dl>
          <p class="approx">Typical means the median: half the rallies are shorter. ${c.rallies_ended_at_landing.count} of ${c.rallies_ended_at_landing.n} rallies end where the shuttle landed; the rest end at the last shot, so they read a little short.</p>`,
      })
    );
    cards.push(
      card({
        w: 8,
        owner: both,
        title: 'How long the rallies were',
        sub: `Each bar counts rallies of that many shots, out of ${c.rally_shots.n}`,
        body: histogram(c.rally_shots, { unit: 'shots', color: HEX.ink2, note: true }),
      })
    );
  } else thin.push(['How long the rallies were', `${c.rallies} rallies`]);

  const pairs = (c.pairs || []).filter((p) => p.n >= THIN && p.count >= 2).slice(0, 5);
  if (pairs.length)
    cards.push(
      card({
        w: 6,
        owner: both,
        title: 'Shots that often follow each other',
        sub: `Out of ${pairs[0].n} back-and-forth pairs where both shots were recognised`,
        body: chain(pairs) + `<p class="note-hand" style="margin:12px 0 0">${esc(cap(label(pairs[0].labels[0])))} then ${esc(label(pairs[0].labels[1]))} is the pattern to watch.</p>`,
      })
    );
  const triples = (c.triples || []).filter((p) => p.n >= THIN && p.count >= 2).slice(0, 5);
  if (triples.length)
    cards.push(
      card({
        w: 6,
        owner: both,
        title: 'Three-shot patterns',
        sub: `Out of ${triples[0].n} three-shot runs`,
        body: chain(triples),
      })
    );
  el.innerHTML = `<h2 class="section-title" style="margin-top:8px">The whole match</h2><p class="section-sub">Both sides together.</p><div class="cards">${pack(cards)}</div>${tray(thin)}`;
}

// ---------------------------------------------------------------- selection
function selection(S, A, sel, names, doubles) {
  const isTeam = sel.kind === 'team';
  const st = isTeam ? S.teams.find((t) => t.team === sel.id) : S.players.find((p) => p.person_id === sel.id);
  const team = isTeam ? sel.id : st.team;
  const color = HEX[team];
  const owner = isTeam && doubles ? { c: color, pair: true } : { c: color };
  const title = isTeam ? (doubles ? teamName(A, team, names) : names[S.players.find((p) => p.team === team).person_id]) : names[sel.id];
  const cards = [];
  const thin = [];
  const add = (cond, c, thinReason, name) => {
    if (cond === null) return; // no data at all: hide
    if (cond) cards.push(c());
    else thin.push([name, thinReason]);
  };

  // rallies won (teams)
  if (isTeam && st.rallies_won) {
    const rw = st.rallies_won;
    add(
      rw.n >= THIN,
      () =>
        card({
          w: 4,
          owner,
          title: 'Rallies won',
          sub: `Of ${rw.n} rallies where we could tell who won`,
          body: `<div class="big-num">${rw.count}<small>of ${rw.n}</small></div>
            <div class="split" role="img" aria-label="${st.won_by_winner} won with a winner, ${st.won_by_opponent_error} from the other side's errors">
              <span style="flex:${st.won_by_winner};background:${color}" data-tip="${st.won_by_winner} won with a winner"></span>
              <span style="flex:${st.won_by_opponent_error};background:${color};opacity:.35" data-tip="${st.won_by_opponent_error} won from the other side's errors"></span>
            </div>
            <div class="legend"><span><i style="background:${color}"></i>${st.won_by_winner} winners</span><span><i style="background:${color};opacity:.35"></i>${st.won_by_opponent_error} from their errors</span></div>
            ${
              st.won_by_opponent_error > st.won_by_winner
                ? `<p class="note-hand" style="margin:10px 0 0;color:${color}">More points came from their mistakes than from your winners.</p>`
                : st.won_by_winner > st.won_by_opponent_error
                ? `<p class="note-hand" style="margin:10px 0 0;color:${color}">You won more points than they gave away.</p>`
                : ''
            }`,
        }),
      `${rw.n} rallies with a known winner`,
      'Rallies won'
    );
  }

  // shot mix
  const sb = st.shots;
  add(
    sb ? sb.shots >= THIN : null,
    () =>
      card({
        w: isTeam ? 8 : 6,
        owner,
        title: 'Shot mix',
        sub: `${sb.shots} shots and ${sb.serves} serves. The tick shows how many of each were forehands.`,
        body: shotMix(sb, color),
      }),
    `${sb && sb.shots} shots`,
    'Shot mix'
  );

  // where they stood
  const pos = st.positions;
  add(
    pos ? pos.n >= 100 : null,
    () =>
      card({
        w: isTeam ? 4 : 6,
        owner,
        title: 'Where they stood',
        sub: `Feet during rallies, ${Math.round(pos.seconds)} s of tracking, shown at the near end`,
        body: heatmap(pos, color, isTeam && doubles),
      }),
    `${pos && Math.round(pos.seconds)} s of tracking`,
    'Where they stood'
  );

  // finishing
  const fin = st.finish;
  add(
    fin ? fin.ended >= THIN : null,
    () => card({ w: 8, owner, title: 'How their rallies ended', sub: `${fin.ended} rallies ended on their shot with a known result`, body: finish(fin, color) }),
    `${fin && fin.ended} rally-ending shots`,
    'How their rallies ended'
  );

  // landings
  const lands = (st.landings || []).filter((l) => l.result);
  add(
    st.landings ? lands.length >= THIN : null,
    () =>
      card({
        w: 4,
        owner,
        title: 'Where their last shots landed',
        sub: `${lands.length} rally-ending shots, hitter at the near end`,
        body: landings(lands, color),
      }),
    `${lands.length} landings`,
    'Where their last shots landed'
  );

  // serve
  const sv = st.serve;
  add(
    sv ? sv.serves >= THIN : null,
    () => card({ w: 4, owner, title: 'Serve', sub: `${sv.serves} serves that opened a rally`, body: serve(sv, color) }),
    `${sv && sv.serves} serves`,
    'Serve'
  );

  // receive
  const rc = st.receive;
  add(
    rc ? rc.returns >= THIN : null,
    () => card({ w: 4, owner, title: 'Return of serve', sub: `${rc.returns} returns`, body: receive(rc, color) }),
    `${rc && rc.returns} returns`,
    'Return of serve'
  );

  // distance
  const d = st.distance;
  add(
    d && d.per_minute_m != null ? d.tracked_s >= 30 : null,
    () =>
      card({
        w: 4,
        owner,
        title: 'Running',
        sub: `${Math.round(d.tracked_s)} s of rallies tracked${isTeam && doubles ? ', both partners added together' : ''}`,
        body: distance(d, color, isTeam && doubles ? S.players.filter((p) => p.team === team) : null, names),
      }),
    `${d && Math.round(d.tracked_s)} s tracked`,
    'Running'
  );

  // formation (doubles teams)
  if (isTeam && doubles) {
    const fm = st.formation;
    add(
      fm ? fm.attacking.front_back.n >= 50 && fm.defending.side_by_side.n >= 50 : null,
      () => card({ w: 4, owner, title: 'How the pair lined up', sub: `${Math.round(fm.seconds)} s with both partners tracked`, body: formation(fm, color) }),
      'too little time with both partners tracked',
      'How the pair lined up'
    );
  }

  // replies
  const rp = (st.replies || []).filter((r) => r.count >= 2);
  add(
    st.replies ? rp.length && rp[0].n >= THIN : null,
    () => card({ w: 4, owner, title: 'Their usual replies', sub: `The other side's shot, then theirs. Out of ${rp[0].n} replies.`, body: chain(rp.slice(0, 5), true) }),
    `${rp.length ? rp[0].n : 0} replies`,
    'Their usual replies'
  );

  // speeds
  if (S.shot_flights && st.speeds) {
    const rows = Object.entries(st.speeds).filter(([, s]) => s && s.initial_kmh && s.initial_kmh.n >= THIN);
    add(
      rows.length > 0,
      () => card({ w: 12, owner, title: 'How fast the shuttle left the racket', sub: 'Median speed for each shot type, with the middle 80% of shots as a line', body: speeds(st.speeds, color) }),
      'fewer than 5 measured shots of any type',
      'Shot speeds'
    );
  }

  const wrap = document.createElement('div');
  wrap.innerHTML = `<div class="sel-title"><h2 style="color:${color}">${esc(title)}</h2><span>${
    isTeam ? (doubles ? `${esc(names[st.person_ids[0]])} and ${esc(names[st.person_ids[1]])}` : `${TEAM_WORD[team]} side`) : `${TEAM_WORD[team]} team`
  }</span></div><div class="cards">${pack(cards)}</div>${tray(thin)}`;
  return wrap;
}

// ---------------------------------------------------------------- pieces
// Lay cards in rows of 12 columns; the last card of a short row widens to fill it.
function pack(cards) {
  const ws = cards.map((c) => +c.match(/data-w="(\d+)"/)[1]);
  const out = ws.slice();
  let used = 0;
  let rowLast = -1;
  ws.forEach((w, i) => {
    if (used + w > 12) {
      if (rowLast >= 0) out[rowLast] += 12 - used;
      used = 0;
    }
    used += w;
    rowLast = i;
  });
  if (rowLast >= 0) out[rowLast] += 12 - used;
  return cards.map((c, i) => c.replace('__SPAN__', out[i]).replace('class="card"', `class="card${out[i] > 6 ? ' wide' : ''}"`)).join('');
}

function card({ w = 4, owner, title, sub, body }) {
  const o = typeof owner === 'string' ? { c: owner, pair: true } : owner || { c: HEX.ink };
  return `<article class="card" data-w="${w}" style="--span:__SPAN__">
    <span class="owner ${o.pair ? 'pair' : ''}" style="background:${o.c}" aria-hidden="true"></span>
    <h3>${esc(title)}</h3>${sub ? `<p class="sub">${esc(sub)}</p>` : ''}${body}</article>`;
}

function tray(thin) {
  if (!thin.length) return '';
  return `<aside class="thin-tray" aria-label="Held back for lack of data">
    <h3>Needs more play</h3>
    <p>These stay off the board until there are at least ${THIN} examples behind them. A longer video, or a full game, usually fills them in.</p>
    <ul>${thin.map(([n, why]) => `<li><b>${esc(n)}</b>: only ${esc(why)}</li>`).join('')}</ul>
  </aside>`;
}

const fmt = (x) => (x == null ? '–' : Number.isInteger(x) ? String(x) : x.toFixed(1));

function histogram(dist, { color }) {
  const counts = dist.counts.slice();
  const bins = counts.map((c, i) => ({ c, lo: dist.edges[i], hi: dist.edges[i + 1] }));
  if (dist.above) bins.push({ c: dist.above, lo: dist.edges[dist.edges.length - 1], hi: null });
  const Wd = NARROW ? 360 : 640;
  const Hh = NARROW ? 190 : 200;
  const padL = 26;
  const padB = 26;
  const padT = 46;
  const max = Math.max(...bins.map((b) => b.c), 1);
  const bw = (Wd - padL) / bins.length;
  const y = (c) => Hh - padB - ((Hh - padB - padT) * c) / max;
  let s = `<svg class="chart" viewBox="0 0 ${Wd} ${Hh}" role="img" aria-label="Histogram of rally lengths in shots; median ${fmt(dist.median)} shots">`;
  const step = max > 6 ? Math.ceil(max / 3) : 1;
  for (let g = 0; g <= max; g += step) s += `<line class="grid" x1="${padL}" x2="${Wd}" y1="${y(g)}" y2="${y(g)}"/><text x="${padL - 6}" y="${y(g) + 4}" text-anchor="end">${g}</text>`;
  bins.forEach((b, i) => {
    const x = padL + i * bw + 1;
    const h = Hh - padB - y(b.c);
    const lab = b.hi == null ? `more than ${b.lo} shots` : `${b.lo} ${b.lo === 1 ? 'shot' : 'shots'}`;
    if (b.c > 0) s += `<path d="${barPath(x, y(b.c), Math.min(18, bw - 2), h)}" fill="${color}" data-tip="${b.c} ${b.c === 1 ? 'rally' : 'rallies'} of ${lab}"/>`;
    s += `<rect x="${padL + i * bw}" y="${padT - 10}" width="${bw}" height="${Hh - padB - padT + 10}" fill="transparent" data-tip="${b.c} ${b.c === 1 ? 'rally' : 'rallies'} of ${lab}"/>`;
    if (b.lo % 5 === 0 || b.lo === 1 || b.hi == null) s += `<text x="${x + Math.min(18, bw - 2) / 2}" y="${Hh - 8}" text-anchor="middle">${b.hi == null ? `${b.lo}+` : b.lo}</text>`;
  });
  // marker annotation pointing to the median
  const mi = Math.round(dist.median) - 1;
  if (mi >= 0 && mi < bins.length) {
    const mx = padL + mi * bw + Math.min(18, bw - 2) / 2;
    const my = y(bins[mi].c) - 6;
    const tx = Math.max(padL + 4, Math.min(Wd - 240, mx + 60));
    const a = arrowPath(tx - 6, 22, mx + 2, my, -0.25, 9);
    s += `<path d="${a.body}${a.head}" fill="none" stroke="${HEX.ink}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
    s += `<text class="ann" x="${tx}" y="20">half the rallies: ${fmt(dist.median)} shots or fewer</text>`;
  }
  s += '</svg>';
  return s;
}

function barPath(x, y, w, h, horizontal = false) {
  // 4px rounded data end, square at the baseline
  const r = Math.min(4, horizontal ? h / 2 : w / 2, horizontal ? w : h);
  if (h <= 0 || w <= 0) return '';
  if (horizontal) return `M${x} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + h - r}Q${x + w} ${y + h} ${x + w - r} ${y + h}H${x}Z`;
  return `M${x} ${y + h}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + h}Z`;
}

function chain(items, reply = false) {
  const max = items[0].count;
  const arrow = `<svg viewBox="0 0 22 12" aria-hidden="true"><path d="M1 7 Q10 2 19 6 M14 2 L19 6 L14 10" fill="none" stroke="${HEX.mute}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  return `<ol class="chain">${items
    .map(
      (p) => `<li><span class="seq">${p.labels.map((l, i) => `<span ${reply && i === 0 ? 'style="color:var(--ink-3)"' : ''}>${esc(label(l))}</span>`).join(arrow)}</span>
        <span class="count">${p.count} of ${p.n}</span>
        <span class="bar" aria-hidden="true"><span style="width:${(p.count / max) * 100}%"></span></span></li>`
    )
    .join('')}</ol>`;
}

function shotMix(sb, color) {
  const fams = Object.entries(sb.families).sort((a, b) => b[1].count - a[1].count);
  const fh = sb.forehand_by_family || {};
  const Wd = NARROW ? 360 : 600;
  const rowH = 30;
  const padL = NARROW ? 70 : 84;
  const padR = 120;
  const H = fams.length * rowH + 40;
  const max = Math.max(...fams.map(([, v]) => v.share || 0), 0.01);
  const x = (s) => padL + ((Wd - padL - padR) * s) / max;
  let s = `<svg class="chart" viewBox="0 0 ${Wd} ${H}" role="img" aria-label="Shot mix: ${fams.map(([k, v]) => `${label(k)} ${v.count}`).join(', ')}">`;
  fams.forEach(([k, v], i) => {
    const y = 32 + i * rowH;
    const w = x(v.share) - padL;
    const f = fh[k];
    const fTxt = f && f.n >= THIN ? `${pct(f.share)} forehand` : f && f.n ? 'too few to split' : '';
    s += `<text x="${padL - 10}" y="${y + 14}" text-anchor="end" style="font-size:13px;fill:${HEX.ink}">${esc(label(k))}</text>`;
    s += `<path d="${barPath(padL, y + 2, Math.max(2, w), 18, true)}" fill="${color}" data-tip="${v.count} of ${v.n} shots were ${esc(label(k))}s${f && f.n ? `, ${f.count} of ${f.n} with a known side on the forehand` : ''}"/>`;
    if (f && f.n >= THIN) {
      const fx = padL + w * f.share;
      s += `<line x1="${fx}" x2="${fx}" y1="${y - 1}" y2="${y + 23}" stroke="${HEX.ink}" stroke-width="2" stroke-linecap="round"/>`;
    }
    s += `<text class="val" x="${padL + w + 8}" y="${y + 15}">${v.count}</text><text x="${padL + w + 8 + String(v.count).length * 8 + 6}" y="${y + 15}">${fTxt}</text>`;
  });
  const top = fams[0];
  if (top && top[1].share >= 0.2) {
    const ty = 14;
    s += `<text class="ann" x="${padL}" y="${ty}" style="fill:${color}">mostly ${esc(label(top[0]))}s: ${top[1].count} of ${top[1].n}</text>`;
  }
  s += '</svg>';
  return s;
}

function courtSvg({ y0 = 0, y1 = 13.4, extra = '' } = {}, inner = '') {
  const x0 = -1;
  const w = 8.1;
  const h = y1 - y0;
  return `<svg class="chart court-chart" viewBox="${x0} ${y0} ${w} ${h}" role="img" ${extra}>
    <rect x="0" y="0" width="6.1" height="13.4" fill="${HEX.courtFill}"/>
    <g fill="none" stroke="${HEX.court}" stroke-width="0.04">
      <rect x="0" y="0" width="6.1" height="13.4"/>
      <path d="M0.46 0V13.4M5.64 0V13.4M0 4.72H6.1M0 8.68H6.1M0 0.76H6.1M0 12.64H6.1M3.05 0V4.72M3.05 8.68V13.4"/>
    </g>
    <line x1="-0.3" x2="6.4" y1="6.7" y2="6.7" stroke="${HEX.ink}" stroke-width="0.08"/>
    ${inner}</svg>`;
}

function heatmap(pos, color, pair) {
  const max = Math.max(...pos.counts.flat(), 1);
  let cells = '';
  pos.counts.forEach((row, ri) => {
    row.forEach((c, ci) => {
      if (!c) return;
      const x = pos.x_edges[ci];
      const y = pos.y_edges[ri];
      const w = pos.x_edges[ci + 1] - x;
      const h = pos.y_edges[ri + 1] - y;
      const a = 0.08 + 0.85 * Math.sqrt(c / max);
      cells += `<rect x="${x + 0.02}" y="${y + 0.02}" width="${w - 0.04}" height="${h - 0.04}" rx="0.06" fill="${color}" fill-opacity="${a.toFixed(2)}" data-tip="${((c / pos.n) * 100).toFixed(1)}% of the time here"/>`;
    });
  });
  // where the weight sits along the court (near end: 6.7 net .. 13.4 baseline)
  let sy = 0;
  let n = 0;
  pos.counts.forEach((row, ri) => {
    const yc = (pos.y_edges[ri] + pos.y_edges[ri + 1]) / 2;
    row.forEach((c) => {
      sy += c * yc;
      n += c;
    });
  });
  const my = n ? sy / n : 10;
  const zone = my < 8.9 ? 'near the net' : my < 11 ? 'mid-court' : 'at the back';
  const ann = `<text x="3.05" y="14.25" text-anchor="middle" style="font:700 0.46px Kalam;fill:${color}">mostly ${zone}</text>`;
  return courtSvg({ y0: 5.6, y1: 14.5, extra: `aria-label="Heatmap of feet positions, mostly ${zone}"` }, cells + ann);
}

function finish(fin, color) {
  const rows = Object.entries(fin.by_label).sort((a, b) => b[1].played - a[1].played);
  const enough = rows.filter(([, r]) => r.played >= THIN);
  const few = rows.filter(([, r]) => r.played < THIN);
  const worst = enough.filter(([, r]) => r.errors > 0).sort((a, b) => a[1].consistency.share - b[1].consistency.share)[0];
  const w = fin.winners;
  const e = fin.errors;
  return `<div style="display:grid;grid-template-columns:minmax(0,200px) minmax(0,1fr);gap:24px" class="fin-grid">
    <div>
      <div class="big-num">${w.count}<small>winners</small></div>
      <div class="big-num" style="margin-top:6px">${e.count}<small>errors</small></div>
      <div class="split" aria-hidden="true"><span style="flex:${w.count || 0.001};background:${color}"></span><span style="flex:${e.count || 0.001};background:${HEX.mute}"></span></div>
      <p class="approx" style="margin-top:4px">Of ${fin.ended} rallies that ended on their shot. A winner is a shot that won the rally; an error lost it.</p>
      ${worst ? `<p class="note-hand" style="margin:12px 0 0">Watch the ${esc(label(worst[0]))}: ${worst[1].errors} ${worst[1].errors === 1 ? 'error' : 'errors'} in ${worst[1].played}.</p>` : ''}
    </div>
    <div style="overflow-x:auto">
      <table class="plain-table">
        <thead><tr><th scope="col">Shot</th><th scope="col">Played</th><th scope="col">Winners</th><th scope="col">Errors</th><th scope="col">Kept in play</th></tr></thead>
        <tbody>${enough
          .map(
            ([k, r]) =>
              `<tr><td>${esc(cap(label(k)))}</td><td>${r.played}</td><td>${r.winners}</td><td>${r.errors}${r.errors ? ` <span style="color:var(--ink-3);font-size:var(--t-xs)">(${[r.errors_net && `${r.errors_net} net`, r.errors_out && `${r.errors_out} out`].filter(Boolean).join(', ') || '–'})</span>` : ''}</td><td>${pct(r.consistency.share)}</td></tr>`
          )
          .join('')}</tbody>
      </table>
      ${few.length ? `<p class="approx">Fewer than ${THIN} played, not shown: ${few.map(([k, r]) => `${label(k)} (${r.played})`).join(', ')}.</p>` : ''}
    </div>
  </div>`;
}

function landings(lands, color) {
  let inner = '';
  lands.forEach((l, i) => {
    const d = l.result === 'winner' ? ringPath(l.x, l.y, 0.26, i + 3) : crossPath(l.x, l.y, 0.2);
    inner += `<path d="${d}" fill="none" stroke="${l.result === 'winner' ? color : HEX.ink}" stroke-width="0.09" stroke-linecap="round" data-tip="${esc(cap(label(l.label)))}: ${l.result}${l.in_court ? ', landed in' : ', landed out'}"/>`;
    inner += `<circle cx="${l.x}" cy="${l.y}" r="0.34" fill="transparent" data-tip="${esc(cap(label(l.label)))}: ${l.result}${l.in_court ? ', landed in' : ', landed out'}"/>`;
  });
  const w = lands.filter((l) => l.result === 'winner').length;
  return (
    courtSvg({ y0: -1, y1: 14.6, extra: `aria-label="${lands.length} landing spots: ${w} winners, ${lands.length - w} errors"` }, inner) +
    `<div class="legend"><span><svg width="12" height="12" viewBox="0 0 12 12" style="display:inline;vertical-align:-1px;margin-right:6px"><circle cx="6" cy="6" r="4.5" fill="none" stroke="${color}" stroke-width="1.8"/></svg>winner</span><span><svg width="12" height="12" viewBox="0 0 12 12" style="display:inline;vertical-align:-1px;margin-right:6px"><path d="M2 2L10 10M10 2L2 10" stroke="${HEX.ink}" stroke-width="1.8"/></svg>error</span></div>`
  );
}

function serve(sv, color) {
  const st = sv.serve_types;
  const known = (st.short ? st.short.count : 0) + (st.long ? st.long.count : 0);
  const rows = [];
  rows.push(`<dt>Short serves</dt><dd>${st.short ? st.short.count : 0} of ${sv.serves}</dd>`);
  rows.push(`<dt>Long serves</dt><dd>${st.long ? st.long.count : 0} of ${sv.serves}</dd>`);
  if (sv.won.n >= THIN) rows.push(`<dt>Rallies won on serve</dt><dd>${sv.won.count} of ${sv.won.n}</dd>`);
  if (sv.faults.n >= THIN) rows.push(`<dt>Serve faults</dt><dd>${sv.faults.count}</dd>`);
  const shortShare = known ? (st.short ? st.short.count : 0) / known : 0;
  return `<div class="split" aria-hidden="true"><span style="flex:${st.short ? st.short.count : 0.001};background:${color}"></span><span style="flex:${st.long ? st.long.count : 0.001};background:${color};opacity:.35"></span></div>
    <dl class="kv" style="margin-top:12px">${rows.join('')}</dl>
    ${known >= THIN ? `<p class="note-hand" style="margin:12px 0 0;color:${color}">${shortShare >= 0.7 ? 'Short and low, nearly every time.' : shortShare <= 0.3 ? 'Mostly long: pushes them back.' : 'A good mix of short and long.'}</p>` : ''}`;
}

function receive(rc, color) {
  const fams = Object.entries(rc.families).sort((a, b) => b[1].count - a[1].count);
  return `<dl class="kv">${fams
    .slice(0, 4)
    .map(([k, v]) => `<dt>${esc(cap(label(k)))}</dt><dd>${v.count} of ${v.n}</dd>`)
    .join('')}${rc.won.n >= THIN ? `<dt style="padding-top:8px">Rallies won after returning</dt><dd style="padding-top:8px">${rc.won.count} of ${rc.won.n}</dd>` : ''}</dl>
    ${fams[0] && fams[0][1].share >= 0.5 ? `<p class="note-hand" style="margin:12px 0 0;color:${color}">Usually answers with a ${esc(label(fams[0][0]))}.</p>` : ''}`;
}

function distance(d, color, partners, names) {
  const covered = d.per_rally.filter((r) => r.covered);
  const maxM = Math.max(...covered.map((r) => r.metres), 1);
  const Wd = 300;
  const Hh = 60;
  const bw = Wd / Math.max(covered.length, 1);
  let spark = `<svg class="chart" viewBox="0 0 ${Wd} ${Hh + 14}" role="img" aria-label="Metres run in each well-tracked rally">`;
  covered.forEach((r, i) => {
    const h = (Hh * r.metres) / maxM;
    spark += `<path d="${barPath(i * bw + 1, Hh - h, Math.max(1.5, Math.min(10, bw - 2)), h)}" fill="${color}" data-tip="${r.rally_id.replace('rally-', 'Rally ')}: ${Math.round(r.metres)} m"/>`;
  });
  spark += `<line class="axis" x1="0" x2="${Wd}" y1="${Hh}" y2="${Hh}"/><text x="0" y="${Hh + 13}" style="font-size:11px">each rally, in order</text></svg>`;
  let comp = '';
  if (partners) {
    comp = `<dl class="kv" style="margin-top:10px">${partners
      .filter((p) => p.distance && p.distance.per_minute_m != null)
      .map((p) => `<dt>${esc(names[p.person_id])}</dt><dd>${Math.round(p.distance.per_minute_m)} m a minute</dd>`)
      .join('')}</dl>`;
  }
  return `<div class="big-num">${Math.round(d.per_minute_m)}<small>metres a minute</small></div>
    <dl class="kv" style="margin:12px 0 10px">
      <dt>In all</dt><dd>${Math.round(d.total_m)} m</dd>
      ${d.rally_m && d.rally_m.n >= THIN ? `<dt>Typical rally</dt><dd>${fmt(d.rally_m.median)} m</dd>` : ''}
    </dl>${spark}${comp}
    <p class="approx">Measured from the feet in the video, so it is a rough figure (give or take 15%). Best for comparing players in this match.</p>`;
}

function formation(fm, color) {
  const pucks = (layout) => {
    // two magnets on a half-court sketch
    const a = layout === 'fb' ? [[1.4, 1.0], [1.4, 2.6]] : [[0.75, 1.8], [2.05, 1.8]];
    return `<svg viewBox="0 0 2.8 3.4" width="64" height="78" aria-hidden="true">
      <rect x="0.1" y="0.1" width="2.6" height="3.2" fill="${HEX.courtFill}" stroke="${HEX.court}" stroke-width="0.04"/>
      <line x1="0" x2="2.8" y1="0.1" y2="0.1" stroke="${HEX.ink}" stroke-width="0.08"/>
      ${a.map(([x, y]) => `<circle cx="${x}" cy="${y}" r="0.34" fill="${color}" stroke="#fff" stroke-width="0.06"/>`).join('')}</svg>`;
  };
  const row = (title, part, pair) => `<div style="display:grid;grid-template-columns:auto 1fr;gap:14px;align-items:center">
      ${pucks(pair)}
      <div><div style="font-weight:600">${title}</div><div class="big-num" style="font-size:var(--t-2xl)">${pct(part.share)}<small>${pair === 'fb' ? 'front and back' : 'side by side'}</small></div>
      <div style="font-size:var(--t-xs);color:var(--ink-3)">${part.count} of ${part.n} moments</div></div></div>`;
  const att = fm.attacking.front_back;
  const def = fm.defending.side_by_side;
  const textbook = att.share >= 0.5 && def.share >= 0.5;
  return `<div style="display:grid;gap:14px" class="form-grid">
      ${row('When attacking', att, 'fb')}
      ${row('When defending', def, 'sbs')}
    </div>
    <p class="note-hand" style="margin:14px 0 0;color:${color}">${textbook ? 'Textbook: front and back to attack, side by side to defend.' : att.share < 0.5 ? 'Attacking side by side more often than front and back.' : 'Defending front and back more often than side by side.'}</p>
    <p class="approx">Attacking means after their own smash, drop or net kill; defending means after their lift or clear, or the other side's attack.</p>`;
}

function speeds(sp, color) {
  const order = ['serve_short', 'serve_long', 'net', 'block', 'push', 'drive', 'lift', 'drop', 'clear', 'net_kill', 'smash'];
  const rows = Object.entries(sp)
    .filter(([, s]) => s && s.initial_kmh)
    .sort((a, b) => (order.indexOf(a[0]) + 99) % 99 - ((order.indexOf(b[0]) + 99) % 99));
  const good = rows.filter(([, s]) => s.initial_kmh.n >= THIN);
  const few = rows.filter(([, s]) => s.initial_kmh.n < THIN);
  const maxV = Math.min(400, Math.ceil(Math.max(...good.map(([, s]) => s.initial_kmh.p90 || 0), 100) / 50) * 50);
  const Wd = NARROW ? 360 : 760;
  const padL = NARROW ? 84 : 100;
  const padR = NARROW ? 70 : 190;
  const rowH = 30;
  const H = good.length * rowH + 44;
  const x = (v) => padL + ((Wd - padL - padR) * Math.min(v, maxV)) / maxV;
  let s = `<svg class="chart" viewBox="0 0 ${Wd} ${H}" role="img" aria-label="Median speed by shot: ${good.map(([k, v]) => `${label(k)} ${Math.round(v.initial_kmh.median)} km/h`).join(', ')}">`;
  for (let g = 0; g <= maxV; g += NARROW ? 100 : 50) s += `<line class="grid" x1="${x(g)}" x2="${x(g)}" y1="10" y2="${H - 22}"/><text x="${x(g)}" y="${H - 6}" text-anchor="middle">${g}</text>`;
  s += `<text x="${Wd - padR + 10}" y="${H - 6}" style="font-size:11px">km/h</text>`;
  let fastest = null;
  good.forEach(([k, v], i) => {
    const y = 22 + i * rowH;
    const q = v.initial_kmh;
    s += `<text x="${padL - 12}" y="${y + 4}" text-anchor="end" style="font-size:13px;fill:${HEX.ink}">${esc(cap(label(k)))}</text>`;
    s += `<line x1="${x(q.p10)}" x2="${x(q.p90)}" y1="${y}" y2="${y}" stroke="${color}" stroke-opacity=".35" stroke-width="6" stroke-linecap="round"/>`;
    if (q.p90 > maxV) s += `<path d="M${x(maxV) + 2} ${y - 5} L${x(maxV) + 9} ${y} L${x(maxV) + 2} ${y + 5}" fill="${color}" fill-opacity=".5"/>`;
    s += `<circle cx="${x(q.median)}" cy="${y}" r="6" fill="${color}" stroke="#fff" stroke-width="2"/>`;
    s += `<rect x="${padL}" y="${y - rowH / 2}" width="${Wd - padL - padR}" height="${rowH}" fill="transparent" data-tip="${esc(cap(label(k)))}: median ${Math.round(q.median)} km/h; middle 80% between ${Math.round(q.p10)} and ${Math.round(q.p90)} km/h; ${q.n} measured of ${v.shots} played"/>`;
    s += `<text class="val" x="${Wd - padR + 10}" y="${y + 4}">${Math.round(q.median)}</text><text x="${Wd - padR + 40}" y="${y + 4}">${NARROW ? `of ${q.n}` : `${q.n} measured${v.speed_bound ? `, ${v.speed_bound} too fast` : ''}`}</text>`;
    if (!fastest || q.median > fastest.m) fastest = { k, m: q.median, y, x: x(q.median) };
  });
  s += '</svg>';
  const bound = Object.values(sp).reduce((a, v) => a + ((v && v.speed_bound) || 0), 0);
  return `${s}
    ${fastest ? `<p class="note-hand" style="margin:6px 0 0;color:${color}">Fastest type: the ${esc(label(fastest.k))}, around ${Math.round(fastest.m)} km/h.</p>` : ''}
    <p class="approx">These speeds are approximate. They come from following the shuttle in the video, so single shots can be far off; compare shot types and players within this match rather than with other videos.${
      bound ? ` ${bound} ${bound === 1 ? 'hit was' : 'hits were'} too fast to measure and ${bound === 1 ? 'is' : 'are'} left out, so the hardest shots read a little low.` : ''
    }${few.length ? ` Fewer than ${THIN} measured, not shown: ${few.map(([k, v]) => `${label(k)} (${v.initial_kmh.n})`).join(', ')}.` : ''}</p>`;
}

// ---------------------------------------------------------------- coming later
function futureSlot(S, names, real) {
  const fake = real || {
    preview: true,
    skills: { attack: 0.72, 'net play': 0.55, defence: 0.48, consistency: 0.81, movement: 0.63, placement: 0.59 },
    best: ['Backhand drive', 'Net kill', 'Short serve'],
    worst: ['Lift under pressure', 'Clear', 'Backhand block'],
  };
  const keys = Object.keys(fake.skills);
  const R = 110;
  const cx = 150;
  const cy = 140;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (i / keys.length) * Math.PI * 2;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  let s = `<svg class="chart" viewBox="0 0 300 280" style="max-width:360px" role="img" aria-label="Skill hexagon preview with made-up numbers">`;
  for (const k of [0.25, 0.5, 0.75, 1]) s += `<polygon points="${keys.map((_, i) => pt(i, R * k).join(',')).join(' ')}" fill="none" stroke="${HEX.grid}" stroke-width="1"/>`;
  s += `<polygon points="${keys.map((k, i) => pt(i, R * fake.skills[k]).join(',')).join(' ')}" fill="${HEX.T1}" fill-opacity=".12" stroke="${HEX.T1}" stroke-width="2" stroke-linejoin="round"/>`;
  keys.forEach((k, i) => {
    const [x, y] = pt(i, R + 18);
    s += `<text x="${x}" y="${y + 4}" text-anchor="middle" style="font-size:12px;fill:${HEX.ink}">${cap(k)}</text>`;
  });
  s += '</svg>';
  return `<section class="future" aria-label="Coming later">
    ${fake.preview ? '<span class="stamp">Preview with made-up numbers</span>' : ''}
    <div class="future-grid">
      <div>
        <h3>Skill shape</h3>
        <p class="sub" style="font-size:var(--t-s);color:var(--ink-2)">Attack, net play, defence, consistency, movement and placement on one shape. Coming once the numbers behind it are reliable.</p>
        ${s}
      </div>
      <div>
        <h3>Best and worst shots</h3>
        <div class="best-worst">
          <div><h4>Working well</h4><ol>${fake.best.map((b) => `<li>${esc(b)}</li>`).join('')}</ol></div>
          <div><h4>Needs work</h4><ol>${fake.worst.map((b) => `<li>${esc(b)}</li>`).join('')}</ol></div>
        </div>
      </div>
    </div>
  </section>`;
}

void firstName;
void underlinePath;
