// Analysis: whole-clip statistics per side and per player, every number with
// its sample size. Cards whose numbers are missing or thin are held back and
// listed under "Not enough play yet". Ported from the approved prototype.
import { useState, type KeyboardEvent, type ReactNode } from "react";
import type { components } from "../api/client.js";
import { CourtLines, L, W } from "./court.js";
import { Face } from "./MatchPage.js";
import {
  MIN_N,
  enough,
  fmt,
  labelText,
  nameOf,
  pct,
  sideNumber,
  teamName,
  teamPlayers,
  type Match,
} from "./model.js";

type S = components["schemas"];
const MIN_SAMPLES = 100; // 10 s of 10 Hz track before a heatmap means anything

/** A skill profile, once the statistics carry one (step 6). */
interface Skills {
  attack: number;
  net_play: number;
  defence: number;
  consistency: number;
  movement: number;
  placement: number;
  best: string[];
  worst: string[];
}
/** The fields any one subject (whole match, a side, a player) may carry. */
interface Numbers {
  positions?: S["Grid"];
  contacts?: S["Spot"][] | number;
  landings?: S["LandingSpot"][];
  rallies_won?: S["Share"];
  won_by_winner?: number;
  won_by_opponent_error?: number;
  finish?: S["FinishStats"];
  distance?: S["DistanceStats"];
  person_ids?: string[];
  shots?: S["ShotBreakdown"];
  speeds?: Record<string, S["SpeedStats"]> | null;
  serve?: S["ServeStats"];
  receive?: S["ReturnStats"];
  formation?: S["Formation"] | null;
  pairs?: S["SequenceCount"][];
  replies?: S["SequenceCount"][];
  rally_shots?: S["Distribution"];
  rally_seconds?: S["Distribution"];
  skills?: Skills | null;
}
interface Subject {
  key: string;
  label: string;
  side?: number;
  kind?: "team" | "player";
  photos: string[];
}
interface Ctx {
  match: Match;
  stats: S["ClipStats"];
  subj: Subject;
  data: Numbers;
  held: [string, string][];
}

export function Analysis({ match }: { match: Match }) {
  const stats = match.stats;
  const [current, setCurrent] = useState("T1");
  if (!stats)
    return (
      <div className="analysis">
        <p className="lede">
          The statistics for this match are not available right now. Reload the
          page to try again.
        </p>
      </div>
    );
  const doubles = stats.mode === "doubles";
  const subjects: Subject[] = [
    { key: "clip", label: "Whole match", photos: [] },
  ];
  if (doubles) {
    for (const t of stats.teams)
      subjects.push({
        key: t.team,
        label: teamName(match, t.team),
        side: sideNumber(t.team),
        kind: "team",
        photos: teamPlayers(match, t.team).map((p) => p.id),
      });
    for (const p of stats.players)
      subjects.push({
        key: p.person_id,
        label: nameOf(match, p.person_id),
        side: sideNumber(p.team),
        kind: "player",
        photos: [p.person_id],
      });
  } else {
    // in singles a side is one player: use the team numbers, which add rallies won
    for (const t of stats.teams)
      subjects.push({
        key: t.team,
        label: nameOf(match, t.person_ids[0]),
        side: sideNumber(t.team),
        kind: "team",
        photos: t.person_ids.slice(0, 1),
      });
  }
  const subj = subjects.find((s) => s.key === current) ?? subjects[0]!;
  const data = (subj.key === "clip"
    ? stats.clip
    : subj.kind === "team"
      ? stats.teams.find((t) => t.team === subj.key)
      : stats.players.find(
          (p) => p.person_id === subj.key,
        )) as unknown as Numbers;
  const held: [string, string][] = [];
  const ctx: Ctx = { match, stats, subj, data, held };
  // In page order, so the held-back list reads top to bottom.
  courtModes(ctx);
  const blocks = [
    <CourtCard key={`court-${subj.key}`} {...ctx} />,
    headline(ctx),
    shotMix(ctx),
    finishing(ctx),
    speeds(ctx),
    serveReceive(ctx),
    formation(ctx),
    patterns(ctx),
    rallyLength(ctx),
    future(ctx),
  ];

  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft"].includes(e.key)) return;
    const i = subjects.findIndex((s) => s.key === subj.key);
    const n =
      subjects[
        (i + (e.key === "ArrowRight" ? 1 : -1) + subjects.length) %
          subjects.length
      ]!;
    setCurrent(n.key);
    e.currentTarget
      .querySelector<HTMLElement>(`[data-key="${n.key}"]`)
      ?.focus();
  };
  return (
    <div className="analysis">
      <div
        className="who"
        role="tablist"
        aria-label="Whose numbers"
        onKeyDown={onKey}
      >
        {subjects.map((s) => (
          <button
            key={s.key}
            role="tab"
            className={`who-btn${s.side ? ` side-${s.side}` : ""}${s.kind === "player" ? " is-player" : ""}`}
            data-key={s.key}
            aria-selected={s.key === subj.key}
            tabIndex={s.key === subj.key ? 0 : -1}
            onClick={() => setCurrent(s.key)}
          >
            {s.photos.map((id) => (
              <Face key={id} match={match} id={id} />
            ))}
            <span>{s.label}</span>
          </button>
        ))}
      </div>
      {stats.warnings?.length ? (
        <div className="warn">
          {stats.warnings.map((w) => (
            <p key={w}>{w}</p>
          ))}
        </div>
      ) : null}
      <div id="an-body" role="tabpanel">
        <div className="an-grid">{blocks.filter((b) => b !== null)}</div>
        {held.length ? (
          <section className="held" aria-labelledby="held-title">
            <h2 id="held-title">Not enough play yet</h2>
            <p>
              These need at least {MIN_N} examples before the numbers say
              anything, so we hold them back for {subj.label}:
            </p>
            <ul>
              {held.map(([what, why]) => (
                <li key={what}>
                  <b>{what}</b> {why}
                </li>
              ))}
            </ul>
            <p className="held-tip">
              A longer video, or a whole game instead of highlights, fills these
              in.
            </p>
          </section>
        ) : null}
      </div>
    </div>
  );
}

/* ---------------- court maps on a lit, tilted court ---------------- */
type MapMode = "stood" | "hit" | "ended";
function courtModes(
  { subj, data, held }: Ctx,
  quiet = false,
): [MapMode, string][] {
  const modes: [MapMode, string][] = [];
  const hold = (what: string, why: string) => !quiet && held.push([what, why]);
  const pos = data.positions;
  if (pos && enough(pos.n, MIN_SAMPLES))
    modes.push(["stood", "Where they stood"]);
  else if (pos)
    hold("Where they stood", `only ${(pos.n / 10).toFixed(0)} s of tracking`);
  if (Array.isArray(data.contacts)) {
    if (enough(data.contacts.length))
      modes.push(["hit", "Where they hit from"]);
    else hold("Where they hit from", `${data.contacts.length} contacts`);
  }
  if (Array.isArray(data.landings)) {
    if (enough(data.landings.length))
      modes.push([
        "ended",
        subj.key === "clip"
          ? "Where rallies ended"
          : "Where their rallies ended",
      ]);
    else hold("Where rallies ended", `${data.landings.length} landings`);
  }
  return modes;
}

function CourtCard(ctx: Ctx) {
  const modes = courtModes(ctx, true);
  const [mode, setMode] = useState<MapMode | null>(null);
  if (!modes.length) return null;
  const { data, subj } = ctx;
  const shown = modes.find(([k]) => k === mode)?.[0] ?? modes[0]![0];
  const sideCls = subj.side ? `side-${subj.side}` : "side-0";
  let under: ReactNode = null,
    over: ReactNode = null,
    text = "";
  if (shown === "stood" && data.positions) {
    const g = data.positions;
    let max = 0;
    g.counts.forEach((r) => r.forEach((c) => (max = Math.max(max, c))));
    const cells: ReactNode[] = [];
    g.counts.forEach((row, r) =>
      row.forEach((v, c) => {
        if (!v) return;
        const x = g.x_edges[c]!,
          y = g.y_edges[r]!;
        cells.push(
          <rect
            key={`${r}-${c}`}
            x={x}
            y={y}
            width={g.x_edges[c + 1]! - x + 0.02}
            height={g.y_edges[r + 1]! - y + 0.02}
            fillOpacity={Math.pow(v / max, 0.65).toFixed(3)}
          />,
        );
      }),
    );
    under = (
      <g className="heat" filter="url(#soft)">
        {cells}
      </g>
    );
    text = `The brighter the mat, the longer they stood there. ${Math.round(g.seconds)} s of rallies, shown from their own end.`;
  } else if (shown === "hit" && Array.isArray(data.contacts)) {
    over = (
      <g className={`dots ${sideCls}`}>
        {data.contacts.map((s, i) => (
          <circle key={i} cx={s.x} cy={s.y} r={0.13} />
        ))}
      </g>
    );
    text = `Each dot is where their feet were when they hit: ${data.contacts.length} contacts, shown from their own end.`;
  } else if (data.landings) {
    const ls = data.landings;
    const won = ls.filter((l) => l.result === "winner").length,
      lost = ls.filter((l) => l.result === "error").length;
    over = (
      <g className="lands">
        {ls.map((l, i) => (
          <g
            key={i}
            transform={`translate(${l.x},${l.y})`}
            className={l.result || "unknown"}
          >
            {l.result === "error" ? (
              <>
                <circle r={0.24} />
                <path d="M-0.15 -0.15 L0.15 0.15 M0.15 -0.15 L-0.15 0.15" />
              </>
            ) : (
              <circle r={0.2} />
            )}
          </g>
        ))}
      </g>
    );
    text = `Where the shuttle came down at the end of ${subj.key === "clip" ? "each rally" : "their rallies"}: ${won} winners (filled) and ${lost} errors (crossed). Turned so the last hitter is at the near end.`;
  }
  return (
    <section className="an-court" aria-labelledby="map-title">
      <div className="map-head">
        <h2 id="map-title" className="an-title">
          On court
        </h2>
        <div className="seg" role="radiogroup" aria-label="Map">
          {modes.map(([k, l]) => (
            <button
              key={k}
              role="radio"
              aria-checked={k === shown}
              onClick={() => setMode(k)}
            >
              {l}
            </button>
          ))}
        </div>
      </div>
      <div className="lit-court" data-side={subj.side ?? 0}>
        <div className="lit-floor">
          <div className="lit-tilt">
            <svg
              viewBox={`-1 -1 ${W + 2} ${L + 2}`}
              className="court lit"
              role="img"
              aria-label={text}
            >
              <defs>
                <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
                  <feGaussianBlur stdDeviation="0.28" />
                </filter>
                <radialGradient id="matlight" cx="50%" cy="62%" r="60%">
                  <stop offset="0" stopColor="#2a8a67" />
                  <stop offset="1" stopColor="#123f31" />
                </radialGradient>
              </defs>
              <rect
                x={-1}
                y={-1}
                width={W + 2}
                height={L + 2}
                fill="url(#matlight)"
                rx={0.1}
              />
              <rect x={0} y={6.7} width={W} height={6.7} className="own-half" />
              {under}
              <CourtLines width={0.05} />
              {over}
            </svg>
          </div>
        </div>
      </div>
      <p className="map-cap">{text}</p>
    </section>
  );
}

/* ---------------- headline numbers ---------------- */
function Big({
  value,
  label,
  note,
}: {
  value: ReactNode;
  label: string;
  note?: string;
}) {
  return (
    <div className="bignum">
      <span className="bn-v">{value}</span>
      <span className="bn-l">{label}</span>
      {note ? <span className="bn-n">{note}</span> : null}
    </div>
  );
}
function headline({ subj, data, held, stats }: Ctx) {
  const items: ReactNode[] = [];
  if (subj.key === "clip") {
    const c = stats.clip;
    items.push(<Big key="r" value={c.rallies} label="rallies" />);
    items.push(<Big key="c" value={c.contacts} label="shots played" />);
    if (enough(c.rally_shots.n))
      items.push(
        <Big
          key="s"
          value={fmt(c.rally_shots.median)}
          label="shots in a typical rally"
          note={`half of the ${c.rally_shots.n} rallies were longer`}
        />,
      );
    if (enough(c.rally_seconds.n))
      items.push(
        <Big
          key="t"
          value={fmt(c.rally_seconds.median, 1)}
          label="seconds in a typical rally"
        />,
      );
  } else {
    if (data.rallies_won) {
      if (enough(data.rallies_won.n))
        items.push(
          <Big
            key="w"
            value={data.rallies_won.count}
            label={`of ${data.rallies_won.n} rallies won`}
            note={`${data.won_by_winner} with their own winners, ${data.won_by_opponent_error} on the other side's errors`}
          />,
        );
      else
        held.push([
          "Rallies won",
          `${data.rallies_won.n} rallies with a known winner`,
        ]);
    }
    const f = data.finish;
    if (f && enough(f.ended))
      items.push(
        <Big
          key="f"
          value={
            <>
              {f.winners.count}
              <i>/</i>
              {f.errors.count}
            </>
          }
          label="winners and errors"
          note={`of the ${f.ended} rallies ${subj.kind === "player" ? "they" : "this side"} finished`}
        />,
      );
    else if (f)
      held.push(["Winners and errors", `${f.ended} rallies finished`]);
    const d = data.distance;
    if (d && d.tracked_s >= 30) {
      items.push(
        <Big
          key="d"
          value={Math.round(d.total_m)}
          label="metres covered"
          note={`${Math.round(d.per_minute_m ?? 0)} m per minute of rally${subj.kind === "team" && (data.person_ids?.length ?? 0) > 1 ? ", both partners added together" : ""}`}
        />,
      );
      if (d.coverage != null && d.coverage < 0.8)
        items.push(
          <p key="cov" className="fine">
            Tracked for {pct(d.coverage)} of rally time, so the real distance is
            higher.
          </p>,
        );
    } else if (d)
      held.push(["Distance", `${Math.round(d.tracked_s)} s tracked`]);
  }
  if (!items.length) return null;
  const d = data.distance;
  const spark =
    subj.key !== "clip" &&
    d &&
    enough(d.per_rally.filter((r) => r.covered).length) ? (
      <DistanceStrip d={d} />
    ) : null;
  return (
    <section key="head" className="an-head" aria-label="Headline numbers">
      {items}
      {spark}
    </section>
  );
}
function DistanceStrip({ d }: { d: S["DistanceStats"] }) {
  const rs = d.per_rally.filter((r) => r.covered);
  const max = Math.max(...rs.map((r) => r.metres));
  return (
    <figure className="dstrip">
      <div className="dstrip-bars">
        {rs.map((r) => (
          <span
            key={r.rally_id}
            style={{ height: `${(r.metres / max) * 100}%` }}
            title={`${r.rally_id.replace("rally-", "Rally ")}: ${Math.round(r.metres)} m`}
          ></span>
        ))}
      </div>
      <figcaption>
        Metres per rally, in match order. Typical rally {fmt(d.rally_m.median)}{" "}
        m, longest {fmt(d.rally_m.max)} m.
      </figcaption>
    </figure>
  );
}

/* ---------------- shot mix ---------------- */
function shotMix({ data, held }: Ctx) {
  const b = data.shots;
  if (!b) return null;
  if (!enough(b.shots)) {
    held.push(["Shot mix", `${b.shots} shots`]);
    return null;
  }
  const fams = Object.entries(b.families)
    .filter(([, v]) => v.count > 0)
    .sort((a, z) => z[1].count - a[1].count);
  const top = fams[0]?.[1].share || 1;
  const sides = b.sides;
  return (
    <section key="mix" className="an-sec an-mix" aria-labelledby="mix-t">
      <h2 id="mix-t" className="an-title">
        Strokes played
      </h2>
      <p className="an-sub">
        {b.shots} shots and {b.serves} serves. {pct(sides.forehand?.share)}{" "}
        forehand, {pct(sides.backhand?.share)} backhand.
      </p>
      <ol className="bars">
        {fams.map(([k, v]) => {
          const fh = b.forehand_by_family?.[k];
          return (
            <li key={k}>
              <span className="bar-l">{labelText(k)}</span>
              <span className="bar">
                <span
                  className="bar-f"
                  style={{ width: `${((v.share ?? 0) / top) * 100}%` }}
                ></span>
              </span>
              <span className="bar-v">
                {v.count}
                <small>{pct(v.share)}</small>
              </span>
              <span className="bar-x">
                {fh && enough(fh.n) ? `${pct(fh.share)} forehand` : ""}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/* ---------------- finishing ---------------- */
function finishing({ data, held }: Ctx) {
  const f = data.finish;
  if (!f) return null;
  const rows = Object.entries(f.by_label)
    .filter(([, v]) => enough(v.played))
    .sort((a, z) => z[1].played - a[1].played);
  const thin = Object.entries(f.by_label)
    .filter(([, v]) => v.played > 0 && !enough(v.played))
    .map(([k]) => labelText(k).toLowerCase());
  if (rows.length < 2) {
    held.push([
      "Stroke by stroke",
      "fewer than two strokes with 5 or more shots",
    ]);
    return null;
  }
  return (
    <section key="fin" className="an-sec an-finish" aria-labelledby="fin-t">
      <h2 id="fin-t" className="an-title">
        How often each stroke kept the rally going
      </h2>
      <p className="an-sub">
        Kept in play: the share of shots that were not errors. Winners and
        errors only count shots that ended a rally.
      </p>
      <table className="tbl">
        <thead>
          <tr>
            <th scope="col">Stroke</th>
            <th scope="col">Played</th>
            <th scope="col">Kept in play</th>
            <th scope="col">Winners</th>
            <th scope="col">Errors</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k}>
              <th scope="row">{labelText(k)}</th>
              <td>{v.played}</td>
              <td>
                <span className="keep">
                  <span
                    style={{ width: `${(v.consistency.share || 0) * 100}%` }}
                  ></span>
                </span>
                {pct(v.consistency.share)}
              </td>
              <td>{v.winners || "–"}</td>
              <td>
                {v.errors ? (
                  <>
                    {v.errors}
                    <small>
                      {[
                        v.errors_net && `${v.errors_net} net`,
                        v.errors_out && `${v.errors_out} out`,
                      ]
                        .filter(Boolean)
                        .join(", ")}
                    </small>
                  </>
                ) : (
                  "–"
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {thin.length ? (
        <p className="fine">
          Not shown, under {MIN_N} shots: {thin.join(", ")}.
        </p>
      ) : null}
    </section>
  );
}

/* ---------------- speeds ---------------- */
function speeds({ data, held, stats }: Ctx) {
  const sp = data.speeds;
  if (!sp || !stats.shot_flights) return null;
  const rows = Object.entries(sp)
    .filter(([, v]) => enough(v.initial_kmh?.n) && v.initial_kmh.median != null)
    .sort(
      (a, z) => (z[1].initial_kmh.median ?? 0) - (a[1].initial_kmh.median ?? 0),
    );
  if (!rows.length) {
    held.push(["Shot speeds", "fewer than 5 measured shots of any stroke"]);
    return null;
  }
  const MAX = 360;
  const ticks = [0, 100, 200, 300];
  return (
    <section key="sp" className="an-sec an-speed" aria-labelledby="sp-t">
      <h2 id="sp-t" className="an-title">
        Shot speed, roughly
      </h2>
      <p className="an-sub">
        Speed leaving the racket, estimated from the video. Good for comparing
        strokes in this match; any single number can be well off.
      </p>
      <ul className="speeds">
        {rows.map(([k, v]) => {
          const s = v.initial_kmh;
          const p10 = s.p10 ?? s.median ?? 0,
            p90 = s.p90 ?? s.median ?? 0,
            median = s.median ?? 0;
          const uncertain = v.speed_bound + v.good - s.n;
          return (
            <li key={k}>
              <span className="sp-l">{labelText(k)}</span>
              <span className="sp-track">
                <span
                  className="sp-range"
                  style={{
                    left: `${(p10 / MAX) * 100}%`,
                    width: `${((Math.min(p90, MAX) - p10) / MAX) * 100}%`,
                  }}
                ></span>
                <span
                  className="sp-med"
                  style={{ left: `${(Math.min(median, MAX) / MAX) * 100}%` }}
                ></span>
              </span>
              <span className="sp-v">
                {Math.round(median)}
                <small> km/h</small>
              </span>
              <span className="sp-n">
                {s.n} estimated
                {uncertain > 0
                  ? `, ${uncertain} with uncertain launch speed`
                  : ""}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="sp-axis" aria-hidden="true">
        {ticks.map((t) => (
          <span key={t} style={{ left: `${(t / MAX) * 100}%` }}>
            {t}
          </span>
        ))}
      </div>
      <p className="fine">
        The line is the middle speed, the band covers most shots. Shots with
        unresolved launch speeds are excluded.
      </p>
    </section>
  );
}

/* ---------------- serve and receive ---------------- */
function serveReceive({ data, held }: Ctx) {
  const sv = data.serve,
    rc = data.receive;
  if (!sv && !rc) return null;
  const parts: ReactNode[] = [];
  if (sv && enough(sv.serves)) {
    parts.push(
      <div key="sv" className="sr">
        <h3>Serving</h3>
        <p className="sr-big">
          {sv.serves}
          <small> serves</small>
        </p>
        <dl>
          <div>
            <dt>Short</dt>
            <dd>{pct(sv.serve_types.short?.share)}</dd>
          </div>
          <div>
            <dt>Long</dt>
            <dd>{pct(sv.serve_types.long?.share)}</dd>
          </div>
          {enough(sv.won.n) ? (
            <div>
              <dt>Rallies won</dt>
              <dd>
                {sv.won.count} of {sv.won.n}
              </dd>
            </div>
          ) : null}
          {enough(sv.faults.n) ? (
            <div>
              <dt>Faults</dt>
              <dd>{sv.faults.count}</dd>
            </div>
          ) : null}
        </dl>
      </div>,
    );
  } else if (sv) held.push(["Serving", `${sv.serves} serves`]);
  if (rc && enough(rc.returns)) {
    const fams = Object.entries(rc.families)
      .sort((a, z) => z[1].count - a[1].count)
      .slice(0, 3);
    parts.push(
      <div key="rc" className="sr">
        <h3>Returning serve</h3>
        <p className="sr-big">
          {rc.returns}
          <small> returns</small>
        </p>
        <dl>
          {fams.map(([k, v]) => (
            <div key={k}>
              <dt>{labelText(k)}</dt>
              <dd>{pct(v.share)}</dd>
            </div>
          ))}
          {enough(rc.won.n) ? (
            <div>
              <dt>Rallies won</dt>
              <dd>
                {rc.won.count} of {rc.won.n}
              </dd>
            </div>
          ) : null}
        </dl>
      </div>,
    );
  } else if (rc) held.push(["Returning serve", `${rc.returns} returns`]);
  if (!parts.length) return null;
  return (
    <section key="sr" className="an-sec an-sr" aria-labelledby="sr-t">
      <h2 id="sr-t" className="an-title">
        Serve and return
      </h2>
      <div className="sr-row">{parts}</div>
    </section>
  );
}

/* ---------------- doubles formation ---------------- */
function formation({ data, held, subj }: Ctx) {
  const f = data.formation;
  if (!f || subj.kind !== "team") return null;
  const atk = f.attacking,
    def = f.defending;
  const okA = enough(atk.front_back.n, 50),
    okD = enough(def.side_by_side.n, 50);
  if (!okA && !okD) {
    held.push([
      "Formation",
      `${Math.round(f.seconds)} s with both partners tracked`,
    ]);
    return null;
  }
  const diagram = (kind: "fb" | "sbs") => (
    <svg viewBox="0 0 40 36" aria-hidden="true">
      <rect x="2" y="2" width="36" height="32" />
      <line x1="2" y1="4" x2="38" y2="4" className="net" />
      {kind === "fb" ? (
        <>
          <circle cx="20" cy="12" r="3.4" />
          <circle cx="20" cy="27" r="3.4" />
        </>
      ) : (
        <>
          <circle cx="11" cy="20" r="3.4" />
          <circle cx="29" cy="20" r="3.4" />
        </>
      )}
    </svg>
  );
  return (
    <section key="fm" className="an-sec an-form" aria-labelledby="fm-t">
      <h2 id="fm-t" className="an-title">
        How the pair lined up
      </h2>
      <div className="form-row">
        {okA ? (
          <div className="form">
            {diagram("fb")}
            <p>
              <b>{pct(atk.front_back.share)}</b> front and back when attacking
            </p>
            <span className="fine">
              {Math.round(atk.front_back.n / 10)} s of attacking play
            </span>
          </div>
        ) : null}
        {okD ? (
          <div className="form">
            {diagram("sbs")}
            <p>
              <b>{pct(def.side_by_side.share)}</b> side by side when defending
            </p>
            <span className="fine">
              {Math.round(def.side_by_side.n / 10)} s of defending play
            </span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

/* ---------------- patterns ---------------- */
function patterns({ data, held, subj }: Ctx) {
  const list = subj.key === "clip" ? data.pairs : data.replies;
  if (!list) return null;
  const rows = list.filter((p) => p.count >= 3 && enough(p.n)).slice(0, 5);
  if (!rows.length) {
    held.push(["Patterns", "no pair of strokes came up 3 times"]);
    return null;
  }
  const intro =
    subj.key === "clip"
      ? "The strokes that most often followed each other."
      : "Their most common answers to the other side’s stroke.";
  return (
    <section key="pt" className="an-sec an-pat" aria-labelledby="pt-t">
      <h2 id="pt-t" className="an-title">
        Patterns
      </h2>
      <p className="an-sub">{intro}</p>
      <ol className="pat">
        {rows.map((p) => (
          <li key={p.labels.join(">")}>
            <span className="pat-a">{labelText(p.labels[0] ?? "unknown")}</span>
            <svg viewBox="0 0 40 12" aria-hidden="true">
              <path d="M2 10 Q20 -4 38 10" />
            </svg>
            <span className="pat-b">
              {labelText(p.labels[1] ?? "unknown").toLowerCase()}
            </span>
            <span className="pat-n">
              {p.count} of {p.n}
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/* ---------------- rally length (whole match) ---------------- */
function rallyLength({ data, subj, held }: Ctx) {
  if (subj.key !== "clip" || !data.rally_shots) return null;
  const d = data.rally_shots;
  if (!enough(d.n)) {
    held.push(["Rally length", `${d.n} rallies`]);
    return null;
  }
  const above = d.above ?? 0;
  const max = Math.max(...d.counts, above, 1);
  return (
    <section key="len" className="an-sec an-len" aria-labelledby="len-t">
      <h2 id="len-t" className="an-title">
        Rally length
      </h2>
      <p className="an-sub">
        Shots per rally across {d.n} rallies. Typical: {fmt(d.median)} shots.
      </p>
      <div
        className="hist"
        role="img"
        aria-label="Histogram of shots per rally"
      >
        {d.counts.map((c, i) => (
          <span
            key={i}
            style={{ height: `${(c / max) * 100}%` }}
            title={`${i + 1} shots: ${c}`}
          ></span>
        ))}
        <span
          className="above"
          style={{ height: `${(above / max) * 100}%` }}
          title={`Over 30 shots: ${above}`}
        ></span>
      </div>
      <div className="hist-axis">
        <span>1</span>
        <span>10</span>
        <span>20</span>
        <span>30+</span>
      </div>
    </section>
  );
}

/* ---------------- coming later: renders only when the data exists ---------------- */
function future({ data }: Ctx) {
  const skills = data.skills;
  if (!skills) return null;
  const axes = [
    "attack",
    "net_play",
    "defence",
    "consistency",
    "movement",
    "placement",
  ] as const;
  const names = {
    attack: "Attack",
    net_play: "Net play",
    defence: "Defence",
    consistency: "Consistency",
    movement: "Movement",
    placement: "Placement",
  };
  const R = 80,
    c = 100;
  const pt = (i: number, v: number) => {
    const a = -Math.PI / 2 + (i * Math.PI * 2) / 6;
    return [c + Math.cos(a) * R * v, c + Math.sin(a) * R * v] as const;
  };
  const ring = (v: number) => axes.map((_, i) => pt(i, v).join(",")).join(" ");
  return (
    <section key="fu" className="an-sec an-future" aria-labelledby="fu-t">
      <h2 id="fu-t" className="an-title">
        Skill profile
      </h2>
      <div className="fu-row">
        <svg
          className="hex"
          viewBox="0 0 200 200"
          role="img"
          aria-label={`Skill profile: ${axes.map((a) => `${names[a]} ${skills[a]}`).join(", ")}`}
        >
          {[0.25, 0.5, 0.75, 1].map((v) => (
            <polygon key={v} className="hex-ring" points={ring(v)} />
          ))}
          {axes.map((a, i) => (
            <line
              key={a}
              className="hex-axis"
              x1={c}
              y1={c}
              x2={pt(i, 1)[0]}
              y2={pt(i, 1)[1]}
            />
          ))}
          <polygon
            className="hex-val"
            points={axes
              .map((a, i) => pt(i, skills[a] / 100).join(","))
              .join(" ")}
          />
          {axes.map((a, i) => {
            const [x, y] = pt(i, 1.2);
            return (
              <text key={a} x={x} y={y} textAnchor="middle">
                {names[a]}
              </text>
            );
          })}
        </svg>
        <div className="bw">
          <h3>Best shots</h3>
          <ol>
            {skills.best.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ol>
          <h3>Worth working on</h3>
          <ol>
            {skills.worst.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
}
