// Analysis tab: whole-clip statistics per match, team and player.
// Every card checks its own sample size and steps aside when it is thin.
import { state, nameOf, teamMembers, esc, label, lower, pct } from './data.js';
import { courtSVG, NET, L, W } from './court.js';
import { solveForApex } from './physics.js';

const MIN = 5; // smallest sample we show a number for
const MIN_SAMPLES = 100; // 10 s of tracking for position maps

const firstWord = (s) => String(s).split(/\s+/)[0];
const median = (a) => {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
};
const plural = (w) => (/(sh|s)$/.test(w) ? `${w}es` : `${w}s`);
const ok = (html, span = 6, cls = '') => ({ ok: true, html, span, cls });
const held = (title, reason) => ({ ok: false, title, reason });

function card(title, body, { note = '', id = '' } = {}) {
  return `<h3 class="card-title" ${id ? `id="${id}"` : ''}>${title}</h3>${body}${note ? `<p class="note">${note}</p>` : ''}`;
}

// ------------------------------------------------------------- cards

function wonCard(A, S, entity) {
  if (entity.kind === 'player') return null;
  if (entity.kind === 'match') {
    const t1 = S.teams.find((t) => t.team === 'T1');
    const t2 = S.teams.find((t) => t.team === 'T2');
    const n = t1.rallies_won.n;
    if (n < MIN) return held('Rallies won', `${n} rallies with a known winner; we show this from ${MIN}`);
    const a = t1.rallies_won.count;
    const b = t2.rallies_won.count;
    const team = (t, cls) =>
      `<div class="won-team"><p class="big num ${cls}">${t.rallies_won.count}</p>
        <p class="who-line"><span class="swatch ${cls}"></span>${esc(t.names.map((x, i) => nameOf(A, t.person_ids[i])).join(' & '))}</p>
        <p class="dim">${t.won_by_winner} by their winners, ${t.won_by_opponent_error} by the other side's errors</p></div>`;
    return ok(
      card(
        'Rallies won',
        `<div class="won-split">${team(t1, 't1')}${team(t2, 't2')}</div>
         <div class="split-bar" aria-hidden="true"><span class="t1" style="flex:${a}"></span><span class="t2" style="flex:${b}"></span></div>`,
        { note: `Of ${n} rallies with a known winner. Counted per rally, so highlight reels work too. Single rally calls can be wrong; the totals are steadier.` },
      ),
      7,
    );
  }
  const t = entity.stats;
  const n = t.rallies_won.n;
  if (n < MIN) return held('Rallies won', `${n} rallies with a known winner; we show this from ${MIN}`);
  return ok(
    card(
      'Rallies won',
      `<p class="big num">${t.rallies_won.count}<span class="of"> of ${n}</span></p>
       <dl class="pairs">
         <div><dt>By their own winners</dt><dd class="num">${t.won_by_winner}</dd></div>
         <div><dt>By the other side's errors</dt><dd class="num">${t.won_by_opponent_error}</dd></div>
       </dl>`,
      { note: 'Single rally calls can be wrong; the totals are steadier.' },
    ),
    4,
  );
}

const H0 = { smash: 2.5, clear: 2.4, drop: 2.4, drive: 1.4, push: 1.0, block: 0.9, net_kill: 2.1, net: 0.8, lift: 0.8, serve_short: 1.0, serve_long: 1.0, serve: 1.0 };

function speedCard(A, S, speeds, contacts) {
  if (!S.shot_flights || !speeds) return held('Shot speed', 'no shot flights were measured for this video');
  const rows = [];
  const thin = [];
  Object.entries(speeds).forEach(([lab, sp]) => {
    const init = sp.initial_kmh;
    if (!init || init.n < MIN || init.median == null) {
      if (sp.shots > 0) thin.push(`${lower(lab)} (${init ? init.n : 0})`);
      return;
    }
    rows.push({ lab, sp });
  });
  if (!rows.length) return held('Shot speed', `fewer than ${MIN} well measured shots of any type`);
  rows.sort((a, b) => b.sp.initial_kmh.median - a.sp.initial_kmh.median);

  // side view at true proportions: x along the court, y height, same scale
  const SC = 284 / (L + 0.3);
  const PH = Math.round(6.2 * SC + 8);
  const fx = (x) => 8 + x * SC;
  const fy = (y) => PH - 4 - y * SC;
  const panels = rows
    .map(({ lab, sp }) => {
      const v0 = sp.initial_kmh.median / 3.6;
      const apex = sp.apex_m && sp.apex_m.n ? sp.apex_m.median : null;
      const cs = contacts.filter((c) => c.label === lab).map((c) => Math.abs(c.y - NET));
      const dnet = Math.min(6.4, Math.max(0.6, median(cs) ?? 3));
      let h0 = H0[lab] ?? 1.2;
      if (apex != null && ['smash', 'drive', 'net_kill', 'push', 'block'].includes(lab)) h0 = Math.min(h0, apex);
      const x0 = NET - dnet;
      const { pts } = solveForApex(v0, h0, apex, L - x0 + 0.4);
      const d = pts
        .filter((_, i) => i % 6 === 0 || i === pts.length - 1)
        .map((p, i) => `${i ? 'L' : 'M'}${fx(x0 + p.x).toFixed(1)},${fy(Math.max(0, p.y)).toFixed(1)}`)
        .join('');
      const marks = [];
      for (let k = 0, next = 0; k < pts.length; k++) {
        if (pts[k].t >= next) {
          marks.push(`<circle class="strobe" cx="${fx(x0 + pts[k].x).toFixed(1)}" cy="${fy(Math.max(0, pts[k].y)).toFixed(1)}" r="1.6"/>`);
          next += 0.05;
        }
      }
      const bound = sp.speed_bound ? `<p class="dim small">${sp.speed_bound} too fast to measure, left out</p>` : '';
      return `<figure class="arc-panel">
        <svg viewBox="0 0 300 ${PH}" aria-hidden="true">
          <line class="floor" x1="${fx(0)}" y1="${fy(0)}" x2="${fx(L)}" y2="${fy(0)}"/>
          <line class="netpost" x1="${fx(NET)}" y1="${fy(0)}" x2="${fx(NET)}" y2="${fy(1.55)}"/>
          <line class="nettape" x1="${fx(NET)}" y1="${fy(0.76)}" x2="${fx(NET)}" y2="${fy(1.524)}"/>
          <path class="flight" d="${d}"/>${marks.join('')}
          <circle class="origin" cx="${fx(x0)}" cy="${fy(h0)}" r="2.2"/>
        </svg>
        <figcaption>
          <span class="arc-label">${label(lab)}</span>
          <span class="arc-speed"><span class="num">${Math.round(sp.initial_kmh.median)}</span><span class="u">km/h</span></span>
          <span class="dim small">${sp.initial_kmh.n} shots, most between ${Math.round(sp.initial_kmh.p10)} and ${Math.round(sp.initial_kmh.p90)}</span>
          ${bound}
        </figcaption>
      </figure>`;
    })
    .join('');
  const top = rows[0];
  const settled = top.sp.settled_kmh && top.sp.settled_kmh.median;
  const lead =
    settled != null
      ? `<p class="lead">${plural(label(top.lab))} left the racket at about ${Math.round(top.sp.initial_kmh.median)} km/h. A tenth of a second later they were down to about ${Math.round(settled)} km/h. Feathers lose speed fast.`
      : '';
  return ok(
    card(
      'Shot speed by type',
      `${lead}<div class="arcs">${panels}</div>`,
      {
        note: `Speeds are approximate: they come from a ${Math.round(A.video.fps)} frames a second video, so compare shot types within this match rather than with a speed gun. Each arc is drawn from the middle speed and height with a standard drag model and starts where these shots were usually played from; dots are 50 ms apart. ${thin.length ? `Not enough measured shots to show: ${thin.join(', ')}.` : ''}`,
      },
    ),
    12,
  );
}

function landingCard(A, landings, who) {
  const n = landings.length;
  if (n < MIN) return held('Where rallies ended', `${n} rally-ending shots with a landing; we show this from ${MIN}`);
  const w = landings.filter((l) => l.result === 'winner').length;
  const e = landings.filter((l) => l.result === 'error').length;
  const marks = landings
    .map((l) => {
      if (l.result === 'winner') return `<circle class="lw" cx="${l.x}" cy="${l.y}" r="0.2"/>`;
      if (l.result === 'error') return `<circle class="le" cx="${l.x}" cy="${l.y}" r="0.2" vector-effect="non-scaling-stroke"/>`;
      return `<circle class="lu" cx="${l.x}" cy="${l.y}" r="0.12"/>`;
    })
    .join('');
  return ok(
    card(
      'Where rallies ended',
      `<div class="court-wrap tall">${courtSVG({ inner: marks, label: `Landing spots of ${n} rally-ending shots` })}
        <p class="end-label">Hit from this end</p></div>
       <p class="key"><span class="k lw"></span>Winner <span class="k le"></span>Error <span class="k lu"></span>Not called</p>
       <p class="lead small-lead">${w} winners and ${e} errors among ${n} rally-ending shots${who ? ` by ${esc(who)}` : ''}.</p>`,
      { note: 'Only the last shot of a rally has a measured landing. Every shot is turned so the hitter stands at the near end.' },
    ),
    4,
  );
}

function positionsCard(grid, title = 'Where they stood') {
  if (!grid || grid.n < MIN_SAMPLES) return held(title, `${grid ? (grid.n / 10).toFixed(0) : 0} s of tracking; we show this from ${MIN_SAMPLES / 10} s`);
  let max = 0;
  grid.counts.forEach((row) => row.forEach((c) => (max = Math.max(max, c))));
  const dots = [];
  let front = 0;
  let mid = 0;
  let back = 0;
  grid.counts.forEach((row, r) => {
    const y = (grid.y_edges[r] + grid.y_edges[r + 1]) / 2;
    row.forEach((c, k) => {
      if (!c) return;
      const x = (grid.x_edges[k] + grid.x_edges[k + 1]) / 2;
      if (y < NET) return;
      if (y < 8.68) front += c;
      else if (y < 11.0) mid += c;
      else back += c;
      const rad = 0.03 + 0.21 * Math.sqrt(c / max);
      dots.push(`<circle class="heat" cx="${x.toFixed(2)}" cy="${y.toFixed(2)}" r="${rad.toFixed(3)}" style="opacity:${(0.35 + 0.65 * Math.sqrt(c / max)).toFixed(2)}"/>`);
    });
  });
  const tot = front + mid + back || 1;
  return ok(
    card(
      title,
      `<div class="court-wrap">${courtSVG({ half: 'near', inner: dots.join(''), label: 'Time spent in each part of the half court' })}</div>
       <dl class="tri">
         <div><dt>Front</dt><dd class="num">${Math.round((front / tot) * 100)}<small>%</small></dd></div>
         <div><dt>Middle</dt><dd class="num">${Math.round((mid / tot) * 100)}<small>%</small></dd></div>
         <div><dt>Back</dt><dd class="num">${Math.round((back / tot) * 100)}<small>%</small></dd></div>
       </dl>`,
      { note: `From ${Math.round(grid.seconds)} s of rallies, feet positions turned to the near end. Larger dots mean more time.` },
    ),
    4,
  );
}

function shotMixCard(shots) {
  if (!shots || shots.shots < MIN) return held('Shot mix', `${shots ? shots.shots : 0} shots; we show this from ${MIN}`);
  const fams = Object.entries(shots.families).filter(([, s]) => s.count > 0).sort((a, b) => b[1].count - a[1].count);
  const max = fams[0][1].share;
  const fbf = shots.forehand_by_family || {};
  const rows = fams
    .map(([k, s]) => {
      const fh = fbf[k] && fbf[k].n >= MIN ? fbf[k].share : null;
      return `<li><span class="mix-l">${label(k)}</span>
        <span class="stem" aria-hidden="true"><span style="width:${((s.share / max) * 100).toFixed(1)}%"></span></span>
        <span class="mix-v num">${pct(s.share)}</span>
        <span class="mix-n dim">${s.count}</span>
        <span class="mix-fh dim">${fh == null ? '' : `${Math.round(fh * 100)}% forehand`}</span></li>`;
    })
    .join('');
  const sd = shots.sides;
  return ok(
    card(
      'Shot mix',
      `<p class="lead small-lead">${shots.shots} shots, ${pct(sd.forehand.share)} forehand and ${pct(sd.backhand.share)} backhand.</p>
       <ul class="mix">${rows}</ul>`,
      { note: 'Serves are counted separately. Forehand shares show where a shot type has 5 or more shots with a known side.' },
    ),
    6,
  );
}

function finishCard(finish) {
  if (!finish || finish.ended < MIN) return held('Finishing', `${finish ? finish.ended : 0} rally-ending shots; we show this from ${MIN}`);
  const rows = Object.entries(finish.by_label)
    .filter(([, b]) => b.played >= MIN && b.consistency && b.consistency.share != null)
    .sort((a, b) => b[1].played - a[1].played);
  const tbl = rows
    .map(
      ([k, b]) => `<tr><th scope="row">${label(k)}</th><td class="num">${b.played}</td>
      <td><span class="gauge" aria-hidden="true"><span style="width:${(b.consistency.share * 100).toFixed(1)}%"></span></span><span class="num">${pct(b.consistency.share)}</span></td>
      <td class="num">${b.winners}</td><td class="num">${b.errors}${b.errors ? `<span class="dim small"> ${[b.errors_out ? `${b.errors_out} out` : '', b.errors_net ? `${b.errors_net} net` : ''].filter(Boolean).join(', ')}</span>` : ''}</td></tr>`,
    )
    .join('');
  return ok(
    card(
      'Finishing',
      `<p class="big num">${finish.winners.count}<span class="of"> winners</span> ${finish.errors.count}<span class="of"> errors</span></p>
       <p class="dim">from ${finish.ended} rally-ending shots with a known result</p>
       ${rows.length ? `<div class="table-wrap"><table class="fin"><thead><tr><th scope="col">Shot</th><th scope="col">Played</th><th scope="col">Kept in play</th><th scope="col">Winners</th><th scope="col">Errors</th></tr></thead><tbody>${tbl}</tbody></table></div>` : ''}`,
      { note: `Shot types played fewer than ${MIN} times are left out of the table.` },
    ),
    6,
  );
}

function serveCard(serve) {
  if (!serve || serve.serves < MIN) return held('Serve', `${serve ? serve.serves : 0} serves; we show this from ${MIN}`);
  const st = serve.serve_types;
  const pos = serve.positions.map((p) => `<circle class="pos" cx="${p.x}" cy="${p.y}" r="0.16"/>`).join('');
  return ok(
    card(
      'Serve',
      `<div class="side-by">
        <div class="court-wrap small">${courtSVG({ half: 'near', inner: pos, label: 'Where they served from' })}</div>
        <dl class="stack">
          <div><dt>Serves</dt><dd class="num">${serve.serves}</dd></div>
          <div><dt>Short</dt><dd class="num">${pct(st.short.share)}</dd></div>
          <div><dt>Long</dt><dd class="num">${pct(st.long.share)}</dd></div>
          ${serve.won.n >= MIN ? `<div><dt>Rallies won on serve</dt><dd class="num">${serve.won.count}<small> of ${serve.won.n}</small></dd></div>` : ''}
          ${serve.faults.n >= MIN ? `<div><dt>Faults</dt><dd class="num">${serve.faults.count}</dd></div>` : ''}
        </dl></div>`,
      { note: 'Dots are where the server stood.' },
    ),
    4,
  );
}

function receiveCard(receive) {
  if (!receive || receive.returns < MIN) return held('Return of serve', `${receive ? receive.returns : 0} returns; we show this from ${MIN}`);
  const fams = Object.entries(receive.families).sort((a, b) => b[1].count - a[1].count).slice(0, 4);
  return ok(
    card(
      'Return of serve',
      `<dl class="stack">
        <div><dt>Returns</dt><dd class="num">${receive.returns}</dd></div>
        ${fams.map(([k, s]) => `<div><dt>${label(k)}</dt><dd class="num">${pct(s.share)}</dd></div>`).join('')}
        ${receive.won.n >= MIN ? `<div><dt>Rallies won when returning</dt><dd class="num">${receive.won.count}<small> of ${receive.won.n}</small></dd></div>` : ''}
      </dl>`,
    ),
    4,
  );
}

function distanceCard(d) {
  if (!d || d.tracked_s < 30 || d.coverage < 0.5) return held('Distance covered', `${d ? Math.round(d.tracked_s) : 0} s tracked; we show this from 30 s with half the rally time tracked`);
  const max = Math.max(...d.per_rally.map((r) => r.metres || 0), 1);
  const stems = d.per_rally
    .map((r, i) => {
      const x = 4 + i * (292 / Math.max(1, d.per_rally.length - 1));
      const h = ((r.metres || 0) / max) * 52;
      return `<line class="${r.covered ? 'st' : 'st thin'}" x1="${x.toFixed(1)}" y1="60" x2="${x.toFixed(1)}" y2="${(60 - h).toFixed(1)}"/>`;
    })
    .join('');
  return ok(
    card(
      'Distance covered',
      `<p class="big num">${Math.round(d.per_minute_m)}<span class="of"> m a minute</span></p>
       <dl class="pairs">
         <div><dt>In all tracked rallies</dt><dd class="num">${Math.round(d.total_m)} m</dd></div>
         ${d.rally_m && d.rally_m.n >= MIN ? `<div><dt>In a typical rally</dt><dd class="num">${d.rally_m.median.toFixed(1)} m</dd></div>` : ''}
       </dl>
       <svg class="stems" viewBox="0 0 300 64" aria-hidden="true"><line class="base" x1="0" y1="60" x2="300" y2="60"/>${stems}</svg>
       <p class="dim small">Each line is one rally, in match order.</p>`,
      { note: `About 15% either way. Best for comparing players and rallies in this match. ${Math.round(d.coverage * 100)}% of rally time was tracked.` },
    ),
    4,
  );
}

function formationCard(f) {
  if (!f || f.seconds < 20) return held('Partner positions', `${f ? Math.round(f.seconds) : 0} s with both partners tracked; we show this from 20 s`);
  const block = (name, s, attacking) => {
    if (!s || s.front_back.n < MIN * 10) return `<div class="form-col"><h4>${name}</h4><p class="dim">Not enough time in this phase.</p></div>`;
    const fb = s.front_back.share;
    return `<div class="form-col"><h4>${name}</h4>
      <div class="glyphs">
        <figure class="${fb >= 0.5 ? 'is-main' : ''}"><svg viewBox="-0.3 6.4 6.7 7.3" aria-hidden="true"><rect class="g-court" x="0" y="6.7" width="6.1" height="6.7"/><line class="g-net" x1="-0.2" y1="6.7" x2="6.3" y2="6.7"/><circle cx="3.05" cy="8.2" r="0.45"/><circle cx="3.05" cy="11.6" r="0.45"/></svg>
          <figcaption><span class="num">${pct(fb)}</span> front and back</figcaption></figure>
        <figure class="${fb < 0.5 ? 'is-main' : ''}"><svg viewBox="-0.3 6.4 6.7 7.3" aria-hidden="true"><rect class="g-court" x="0" y="6.7" width="6.1" height="6.7"/><line class="g-net" x1="-0.2" y1="6.7" x2="6.3" y2="6.7"/><circle cx="1.6" cy="10.3" r="0.45"/><circle cx="4.5" cy="10.3" r="0.45"/></svg>
          <figcaption><span class="num">${pct(1 - fb)}</span> side by side</figcaption></figure>
      </div></div>`;
  };
  return ok(
    card(
      'Partner positions',
      `<div class="form-cols">${block('When attacking', f.attacking, true)}${block('When defending', f.defending, false)}</div>`,
      { note: `From ${Math.round(f.seconds)} s with both partners tracked. Attacking follows their own smash, drop or net kill; defending follows their lift or clear.` },
    ),
    6,
  );
}

function repliesCard(replies, title, intro) {
  const list = (replies || []).filter((r) => r.n >= MIN && r.count >= 2).slice(0, 6);
  if (list.length < 2) return held(title, 'not enough repeated sequences yet');
  const max = list[0].share;
  return ok(
    card(
      title,
      `<p class="dim">${intro}</p><ol class="seq">${list
        .map(
          (r) => `<li><span class="seq-l">${r.labels.map((x, i) => (i ? lower(x) : label(x))).join(', then ')}</span>
          <span class="stem" aria-hidden="true"><span style="width:${((r.share / max) * 100).toFixed(1)}%"></span></span>
          <span class="num">${r.count}</span><span class="dim small">of ${r.n}</span></li>`,
        )
        .join('')}</ol>`,
    ),
    6,
  );
}

function rallyShapeCard(clip) {
  const rs = clip.rally_shots;
  const sec = clip.rally_seconds;
  if (!rs || rs.n < MIN) return held('Rally length', `${rs ? rs.n : 0} rallies; we show this from ${MIN}`);
  const max = Math.max(...rs.counts, rs.above || 0, 1);
  const stems = rs.counts
    .map((c, i) => {
      if (!c) return `<line class="st0" x1="${10 + i * 9.4}" y1="70" x2="${10 + i * 9.4}" y2="69"/>`;
      const x = 10 + i * 9.4;
      const y = 70 - (c / max) * 58;
      return `<line class="st" x1="${x}" y1="70" x2="${x}" y2="${y}"/><circle class="st-dot" cx="${x}" cy="${y}" r="2"/>`;
    })
    .join('');
  const ax = 10 + 30 * 9.4;
  const above = rs.above
    ? `<line class="st" x1="${ax}" y1="70" x2="${ax}" y2="${70 - (rs.above / max) * 58}"/><circle class="st-dot" cx="${ax}" cy="${70 - (rs.above / max) * 58}" r="2"/><text x="${ax}" y="84" class="ax end">31+</text>`
    : '';
  const mx = 10 + (rs.median - 1) * 9.4;
  return ok(
    card(
      'Rally length',
      `<p class="big num">${Math.round(rs.median)}<span class="of"> shots in a typical rally</span></p>
       <p class="dim">Lasting about ${sec.median.toFixed(1)} s. One in ten went past ${Math.round(rs.p90)} shots.</p>
       <svg class="hist" viewBox="0 0 320 88" role="img" aria-label="Rallies by number of shots">
         <line class="base" x1="4" y1="70" x2="316" y2="70"/>
         <line class="median" x1="${mx}" y1="4" x2="${mx}" y2="70"/>
         <text class="ax" x="${mx + 4}" y="10">typical</text>
         ${stems}${above}
         <text class="ax" x="10" y="84">1</text><text class="ax" x="${10 + 9 * 9.4}" y="84">10</text><text class="ax" x="${10 + 19 * 9.4}" y="84">20</text><text class="ax" x="${10 + 29 * 9.4}" y="84">30</text>
       </svg>`,
      { note: `${clip.rallies} rallies. A highlight reel shows only some rallies, so this describes the clip, not the whole match.` },
    ),
    5,
  );
}

// ------------------------------------------------------------- future slot

const FAKE_SKILLS = {
  axes: [
    ['Attack', 0.74],
    ['Net play', 0.58],
    ['Defence', 0.66],
    ['Consistency', 0.81],
    ['Movement', 0.62],
    ['Placement', 0.49],
  ],
  best: ['Backhand drive, kept in play 19 of 20', 'Smash from the back, 4 winners'],
  worst: ['Net shot, 3 into the net', 'Lift from the forehand corner, 2 out'],
};

function futureSection(skills) {
  if (!skills) return '';
  const cx = 110;
  const cy = 110;
  const R = 86;
  const n = skills.axes.length;
  const pt = (i, r) => {
    const a = -Math.PI / 2 + (i / n) * Math.PI * 2;
    return [cx + Math.cos(a) * r, cy + Math.sin(a) * r];
  };
  const ring = (f) => skills.axes.map((_, i) => pt(i, R * f).map((v) => v.toFixed(1)).join(',')).join(' ');
  const shape = skills.axes.map(([, v], i) => pt(i, R * v).map((q) => q.toFixed(1)).join(',')).join(' ');
  const labels = skills.axes
    .map(([name, v], i) => {
      const [x, y] = pt(i, R + 16);
      const anchor = Math.abs(x - cx) < 4 ? 'middle' : x > cx ? 'start' : 'end';
      return `<text x="${x.toFixed(1)}" y="${(y + 4).toFixed(1)}" text-anchor="${anchor}" class="hx-l">${name} <tspan class="hx-v">${Math.round(v * 100)}</tspan></text>`;
    })
    .join('');
  return `<section class="future" aria-labelledby="future-h">
    <div class="future-head"><h2 class="h2" id="future-h">Skills and standout shots</h2>
      ${state.future ? '<p class="preview-stamp">Preview with made-up numbers. Not from this match.</p>' : ''}</div>
    <div class="future-body">
      <svg class="hexagon" viewBox="-60 -10 340 240" role="img" aria-label="Skill profile">
        ${[0.25, 0.5, 0.75, 1].map((f) => `<polygon class="hx-ring" points="${ring(f)}"/>`).join('')}
        ${skills.axes.map((_, i) => `<line class="hx-ax" x1="${cx}" y1="${cy}" x2="${pt(i, R)[0].toFixed(1)}" y2="${pt(i, R)[1].toFixed(1)}"/>`).join('')}
        <polygon class="hx-shape" points="${shape}"/>${labels}
      </svg>
      <div class="bw">
        <h3 class="card-title">Working well</h3><ul class="plain">${skills.best.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>
        <h3 class="card-title">Costing rallies</h3><ul class="plain">${skills.worst.map((s) => `<li>${esc(s)}</li>`).join('')}</ul>
      </div>
    </div>
  </section>`;
}

// ------------------------------------------------------------- page

export function mountAnalysis(root, ctx) {
  const { analysis: A, stats: S, base } = ctx;
  const doubles = A.video.mode === 'doubles';
  const lenses = [{ key: 'match', kind: 'match', title: 'Whole match' }];
  ['T1', 'T2'].forEach((t) => {
    const ts = S.teams.find((x) => x.team === t);
    if (doubles) lenses.push({ key: t, kind: 'team', team: t, title: teamMembers(A, t).map((id) => nameOf(A, id)).join(' & '), stats: ts });
    teamMembers(A, t).forEach((id) => {
      lenses.push({ key: id, kind: 'player', team: t, id, title: nameOf(A, id), stats: S.players.find((p) => p.person_id === id) });
    });
  });
  let active = 'match';

  root.innerHTML = `
  <div class="analysis page-wide">
    <nav class="lens" aria-label="Show statistics for">
      ${lenses
        .map(
          (l) => `<button type="button" class="lens-b ${l.kind}" data-lens="${l.key}" aria-pressed="false">
          ${l.kind === 'player' ? `<img src="${base}players/${l.id}.jpg" alt="">` : l.kind === 'team' ? `<span class="pair"><span class="swatch ${l.team.toLowerCase()}"></span><span class="swatch ${l.team.toLowerCase()} hollow"></span></span>` : '<span class="pair all"><span class="swatch t1"></span><span class="swatch t2"></span></span>'}
          <span>${esc(l.title)}</span></button>`,
        )
        .join('')}
    </nav>
    <div class="analysis-body" data-body tabindex="-1"></div>
  </div>`;
  const body = root.querySelector('[data-body]');

  const allContacts = S.players.flatMap((p) => p.contacts);

  function draw() {
    const l = lenses.find((x) => x.key === active);
    root.querySelectorAll('[data-lens]').forEach((b) => b.setAttribute('aria-pressed', b.dataset.lens === active));
    let cards = [];
    let heading = '';
    let sub = '';
    if (l.kind === 'match') {
      heading = 'Whole match';
      sub = `${S.clip.rallies} rallies and ${S.clip.contacts} shots, for both sides together.`;
      cards = [
        wonCard(A, S, l),
        rallyShapeCard(S.clip),
        speedCard(A, S, S.clip.speeds, allContacts),
        landingCard(A, S.clip.landings),
        shotMixCard(S.clip.shots),
        repliesCard(S.clip.pairs, 'Common exchanges', 'Two shots in a row, one by each side.'),
      ];
      [null, null, null, 4, 8, 12].forEach((sp, i) => sp && cards[i] && cards[i].ok && (cards[i].span = sp));
    } else {
      const st = l.stats;
      heading = l.kind === 'team' ? teamMembers(A, l.team).map((id) => nameOf(A, id)).join(' and ') : l.title;
      sub = l.kind === 'team' ? 'Both partners added together.' : `${st.shots.contacts} shots, ${st.shots.serves} of them serves.`;
      cards = [
        wonCard(A, S, l),
        distanceCard(st.distance),
        positionsCard(st.positions),
        speedCard(A, S, st.speeds, st.contacts),
        landingCard(A, st.landings, l.kind === 'player' ? l.title : null),
        serveCard(st.serve),
        receiveCard(st.receive),
        shotMixCard(st.shots),
        finishCard(st.finish),
        l.kind === 'team' ? formationCard(st.formation) : null,
        repliesCard(st.replies, 'Their replies', "The other side's shot, then theirs."),
      ];
    }
    cards = cards.filter(Boolean);
    const shown = cards.filter((c) => c.ok);
    const heldBack = cards.filter((c) => !c.ok);
    const warn = S.warnings && S.warnings.length ? `<p class="warn">${S.warnings.map(esc).join(' ')}</p>` : '';
    const skills = ctx.skills || (state.future ? FAKE_SKILLS : null);
    body.innerHTML = `
      <header class="lens-head">
        ${l.kind === 'player' ? `<img class="lens-photo" src="${base}players/${l.id}.jpg" alt="">` : ''}
        <div><h2 class="h2">${esc(heading)}</h2><p class="dim">${esc(sub)}</p></div>
      </header>${warn}
      ${shown.length ? `<div class="cards">${shown.map((c) => `<section class="card span-${c.span} ${c.cls}">${c.html}</section>`).join('')}</div>` : `<div class="empty"><p class="lead">Not enough of this match was measured to say anything reliable yet.</p><p class="dim">That usually means a short clip or a camera that cuts away often. Longer rallies filmed from behind the baseline give the most to work with.</p></div>`}
      ${
        heldBack.length
          ? `<aside class="held"><h3 class="card-title">Held back for now</h3><p class="dim">These need a bigger sample before the numbers mean anything. A longer clip will fill them in.</p>
            <ul>${heldBack.map((h) => `<li><span>${h.title}</span><span class="dim">${h.reason}</span></li>`).join('')}</ul></aside>`
          : ''
      }
      ${futureSection(skills)}`;
  }
  root.querySelector('.lens').addEventListener('click', (e) => {
    const b = e.target.closest('[data-lens]');
    if (!b) return;
    active = b.dataset.lens;
    draw();
  });
  draw();
  return null;
}
