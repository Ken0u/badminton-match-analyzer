// Watch: the real video with an overlay drawn like court lines and light.
// Per-frame drawing is imperative (refs), as in the approved prototype; React
// owns the structure, the rally list and the swap fix.
import { useEffect, useRef, useState, type PointerEvent } from "react";
import {
  errorText,
  posterUrl,
  swapRally,
  undoSwaps,
  videoSource,
} from "./api.js";
import { courtSegments, CourtLines } from "./court.js";
import { Face } from "./MatchPage.js";
import {
  applyH,
  clock,
  firstName,
  initials,
  labelText,
  nameOf,
  positionAt,
  rallyEnd,
  rallyNumber,
  rallySwaps,
  shotLabel,
  sideNumber,
  speedOf,
  teamName,
  teamOf,
  viewAt,
  type Match,
  type PersonId,
  type Rally,
  type Shot,
  type View,
} from "./model.js";
import { useToast } from "./shell.js";

const GAUGE_MAX = 300; // km/h at the right end of the little gauge
const esc = (s: string) =>
  s.replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );

function useMedia(query: string) {
  const [on, setOn] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const mq = matchMedia(query);
    const change = () => setOn(mq.matches);
    mq.addEventListener("change", change);
    return () => mq.removeEventListener("change", change);
  }, [query]);
  return on;
}

export function resultSentence(match: Match, r: Rally) {
  const o = r.outcome;
  const last = r.shots[r.shots.length - 1];
  if (!o || !o.winner_team) return "Result unknown";
  const who = last?.hitter_id
    ? nameOf(match, last.hitter_id)
    : "the last hitter";
  const stroke = last ? labelText(shotLabel(last)).toLowerCase() : "shot";
  const team = teamName(match, o.winner_team);
  if (o.reason === "winner") return `${team} won it with ${who}'s ${stroke}`;
  if (o.detail === "net")
    return `${team} won it. ${who}'s ${stroke} went into the net`;
  if (o.detail === "out") return `${team} won it. ${who}'s ${stroke} went out`;
  return `${team} won it on ${who}'s error`;
}

function MiniCourt({ match }: { match: Match }) {
  return (
    <div className="hud-mini" aria-label="Positions from above">
      <svg
        viewBox="-0.9 -0.9 7.9 15.2"
        role="img"
        aria-label="Players from above"
      >
        <rect
          className="court-mat"
          x={-0.9}
          y={-0.9}
          width={7.9}
          height={15.2}
          rx={0.2}
        />
        <CourtLines width={0.07} />
        <g className="mini-landing"></g>
        {match.analysis.players.map((p) => (
          <g
            key={p.id}
            className={`mini-p side-${sideNumber(p.team)}`}
            data-pid={p.id}
          >
            <circle r={0.42} />
            <text dy={0.17}>{initials(nameOf(match, p.id))}</text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export function Watch({
  match,
  refresh,
}: {
  match: Match;
  refresh: () => Promise<void>;
}) {
  const toast = useToast();
  const A = match.analysis;
  const { width: VW, height: VH, duration_s: DUR } = A.video;
  const rallies = A.rallies;
  const people = A.players;
  const wide = useMedia("(min-width: 861px)");
  const [src, setSrc] = useState<string | null>(null);
  const [videoError, setVideoError] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [linesOn, setLinesOn] = useState(true);
  const [open, setOpen] = useState<string | null>(null);
  const [chosen, setChosen] = useState<PersonId[]>([]);
  const [busy, setBusy] = useState(false);

  const matchRef = useRef(match);
  matchRef.current = match;
  const root = useRef<HTMLDivElement>(null);
  const video = useRef<HTMLVideoElement>(null);
  const scrub = useRef<HTMLInputElement>(null);
  const rl = useRef<HTMLOListElement>(null);
  const updateRef = useRef<() => void>(() => {});
  const seekRef = useRef<(s: number) => void>(() => {});
  const jumpRef = useRef<(dir: number) => void>(() => {});
  const toggleRef = useRef<() => void>(() => {});

  useEffect(() => {
    const ctl = new AbortController();
    videoSource(match.id, ctl.signal).then(setSrc, () => {});
    return () => ctl.abort();
  }, [match.id]);

  /* ---- the per-frame overlay, HUD, mini court and score ---- */
  useEffect(() => {
    const el = root.current!;
    const v = video.current!;
    const $ = <T extends Element = HTMLElement>(sel: string) =>
      el.querySelector<T>(sel);
    const ovLines = $<SVGGElement>(".ov-lines")!,
      ovHit = $<SVGGElement>(".ov-hit")!,
      ovLand = $<SVGGElement>(".ov-land")!;
    const H = {
      stroke: $("#h-stroke")!,
      who: $("#h-who")!,
      speed: $("#h-speed")!,
      speedNote: $("#h-speed-note")!,
      speedCell: $("#h-speed-cell")!,
      gauge: $("#h-gauge")!,
      shots: $("#h-shots")!,
      time: $("#h-time")!,
      rallyK: $("#h-rally-k")!,
      w1: $("#h-w1")!,
      w2: $("#h-w2")!,
      cur: $("#cur")!,
      head: $("#tl-head")!,
    };
    let lastView: View | null | undefined;
    let lastMatch = matchRef.current;
    function drawLines(view: View | null) {
      if (view === lastView) return;
      lastView = view;
      if (!view) {
        ovLines.innerHTML = "";
        return;
      }
      const { width: w, height: h } = matchRef.current.analysis.video;
      ovLines.innerHTML = courtSegments()
        .map(([a, b]) => {
          const [x1, y1] = applyH(view.inverse, a[0], a[1]);
          const [x2, y2] = applyH(view.inverse, b[0], b[1]);
          return `<line x1="${x1 * w}" y1="${y1 * h}" x2="${x2 * w}" y2="${y2 * h}"/>`;
        })
        .join("");
    }

    // the spotlight follows a smoothed position, so tracking jitter does not shake it
    const spot = { id: null as string | null, x: 0, y: 0, t: -1 };
    function drawHitter(
      view: View | null,
      shot: Shot | null,
      t: number,
      strength: number,
    ) {
      const m = matchRef.current;
      const { width: w, height: h } = m.analysis.video;
      if (!view || !shot?.hitter_id || strength <= 0) {
        ovHit.innerHTML = "";
        spot.id = null;
        return;
      }
      const raw = positionAt(m, shot.hitter_id, t) || shot.hitter_position;
      if (!raw) {
        ovHit.innerHTML = "";
        return;
      }
      const dt = t - spot.t;
      if (spot.id !== shot.hitter_id || dt < 0 || dt > 0.5) {
        spot.x = raw.x;
        spot.y = raw.y;
      } else {
        const k = 1 - Math.exp(-dt / 0.18);
        spot.x += (raw.x - spot.x) * k;
        spot.y += (raw.y - spot.y) * k;
      }
      spot.id = shot.hitter_id;
      spot.t = t;
      const pts: [number, number][] = [];
      for (let i = 0; i < 32; i++) {
        const a = (i / 32) * Math.PI * 2;
        const [x, y] = applyH(
          view.inverse,
          spot.x + Math.cos(a) * 0.55,
          spot.y + Math.sin(a) * 0.55,
        );
        pts.push([x * w, y * h]);
      }
      const xs = pts.map((p) => p[0]),
        ys = pts.map((p) => p[1]);
      const c = applyH(view.inverse, spot.x, spot.y);
      const cx = c[0] * w,
        cy = c[1] * h;
      const bw = Math.max(...xs) - Math.min(...xs);
      const bh = bw * 2.4;
      const left = Math.min(...xs),
        right = Math.max(...xs);
      const side = sideNumber(teamOf(m, shot.hitter_id));
      ovHit.style.opacity = strength.toFixed(2);
      ovHit.innerHTML = `
        <polygon class="beam" points="${cx - bw * 0.12},${cy - bh * 1.15} ${cx + bw * 0.12},${cy - bh * 1.15} ${right},${cy} ${left},${cy}" fill="url(#beam)"/>
        <ellipse cx="${cx}" cy="${cy}" rx="${bw * 0.6}" ry="${(Math.max(...ys) - Math.min(...ys)) * 0.6}" fill="url(#pool)"/>
        <polygon class="ring side-${side}" points="${pts.map((p) => p.join(",")).join(" ")}"/>
        <g class="tag side-${side}" transform="translate(${right + 8},${cy + 4})">
          <line x1="0" y1="0" x2="14" y2="0"/><text x="18" y="5">${esc(nameOf(m, shot.hitter_id))}</text>
        </g>`;
    }

    function drawLanding(rally: Rally | null, t: number) {
      const { width: w, height: h } = matchRef.current.analysis.video;
      const last = rally?.shots[rally.shots.length - 1];
      const L = last?.landing;
      if (!rally || !L || !L.image || t < L.time_s || t > rallyEnd(rally) + 3) {
        ovLand.innerHTML = "";
        return;
      }
      const x = L.image.x * w,
        y = L.image.y * h;
      ovLand.innerHTML = `<g transform="translate(${x},${y})" class="${L.in_court ? "in" : "out"}">
        <ellipse rx="22" ry="8"/><line x1="-6" y1="-6" x2="6" y2="6"/><line x1="6" y1="-6" x2="-6" y2="6"/>
        <text y="-16">${L.in_court ? "In" : "Out"}</text></g>`;
    }

    let shownShot: string | null = null,
      currentId: string | null | undefined;
    /** A new shot: show the estimate immediately; only the gauge animates. */
    function showSpeed(shot: Shot) {
      const sp = speedOf(shot);
      const cell = H.speedCell;
      cell.className = "hud-cell hud-speed";
      if (sp?.kmh) {
        const end = sp.kmh;
        H.speedNote.textContent = sp.settled
          ? "estimated at +0.1 s; launch speed uncertain"
          : "estimated leaving the racket";
        H.gauge.style.width = `${Math.min(end / GAUGE_MAX, 1) * 100}%`;
        H.speed.innerHTML = `${end}<small> km/h</small>`;
        void cell.offsetWidth;
        cell.classList.add("fresh");
      } else if (sp?.bound) {
        cell.classList.add("dim");
        H.speed.textContent = "Uncertain";
        H.speedNote.textContent = "The track does not resolve launch speed.";
        H.gauge.style.width = "0";
        void cell.offsetWidth;
        cell.classList.add("fresh");
      } else {
        cell.classList.add("dim");
        H.speed.textContent = "–";
        H.speedNote.textContent = "not measured for this shot";
        H.gauge.style.width = "0";
      }
    }

    function update() {
      const m = matchRef.current;
      const all = m.analysis.rallies;
      if (m !== lastMatch) {
        // A fix rebuilt the document: redraw everything from it.
        lastMatch = m;
        lastView = undefined;
        shownShot = null;
      }
      const t = v.currentTime || 0;
      const frame = Math.round(t * m.analysis.video.fps);
      const view = viewAt(m, frame);
      drawLines(view);
      H.cur.textContent = clock(t);
      if (scrub.current && document.activeElement !== scrub.current)
        scrub.current.value = String(t);
      H.head.style.left = `${(t / m.analysis.video.duration_s) * 100}%`;

      // the rally under the playhead, or the one just finished
      let rally =
        all.find((r) => t >= r.start_s - 0.2 && t <= rallyEnd(r) + 0.2) ?? null;
      const inRally = !!rally;
      if (!rally)
        rally = [...all].reverse().find((r) => rallyEnd(r) < t) ?? null;

      let shot: Shot | null = null,
        idx = -1;
      if (rally) {
        for (let i = 0; i < rally.shots.length; i++)
          if (rally.shots[i]!.time_s <= t + 0.02) idx = i;
        shot = idx >= 0 ? rally.shots[idx]! : null;
      }
      // hitter light: on from the contact until the next one, fading once the rally is over
      const next =
        rally && idx + 1 < rally.shots.length
          ? rally.shots[idx + 1]!.time_s
          : null;
      let strength = 0;
      if (shot && inRally)
        strength = next ? 1 : Math.max(0, 1 - (t - shot.time_s - 1.2) / 1.0);
      drawHitter(view, shot, t, Math.min(strength, 1));
      drawLanding(rally, t);

      if (rally && inRally) {
        H.rallyK.textContent = `Rally ${rallyNumber(rally)}`;
        H.shots.textContent = String(idx + 1);
        H.time.textContent = `${Math.max(0, Math.min(t, rallyEnd(rally)) - rally.start_s).toFixed(1)} s`;
      } else {
        H.rallyK.textContent = rally
          ? `After rally ${rallyNumber(rally)}`
          : "Before the first rally";
        H.shots.textContent = rally ? String(rally.shots.length) : "–";
        H.time.textContent = rally
          ? `${(rallyEnd(rally) - rally.start_s).toFixed(1)} s`
          : "";
      }
      if (shot) {
        H.stroke.textContent = labelText(shotLabel(shot));
        H.who.textContent = [
          shot.hitter_id ? nameOf(m, shot.hitter_id) : null,
          shot.side,
        ]
          .filter(Boolean)
          .join(", ");
        if (shot.id !== shownShot) {
          shownShot = shot.id;
          showSpeed(shot);
        }
      } else {
        H.stroke.textContent = "–";
        H.who.textContent = "";
        H.speed.textContent = "–";
        H.speedNote.textContent = "";
        H.speedCell.className = "hud-cell hud-speed dim";
        H.gauge.style.width = "0";
        shownShot = null;
      }

      // rallies won up to the playhead
      let w1 = 0,
        w2 = 0;
      for (const r of all)
        if (r.outcome?.winner_team && rallyEnd(r) <= t) {
          if (r.outcome.winner_team === "T1") w1++;
          else w2++;
        }
      H.w1.textContent = String(w1);
      H.w2.textContent = String(w2);

      // mini court: everybody now, plus the last landing so far
      const mini = el.querySelector(".hud-mini");
      if (mini) {
        for (const g of mini.querySelectorAll<SVGGElement>(".mini-p")) {
          const id = g.dataset.pid!;
          const pos = positionAt(m, id, t, 3);
          if (pos && view) {
            g.setAttribute("transform", `translate(${pos.x},${pos.y})`);
            g.setAttribute("opacity", "1");
          } else g.setAttribute("opacity", "0");
          g.classList.toggle(
            "hitting",
            !!shot && shot.hitter_id === id && strength > 0.5,
          );
        }
        let land: NonNullable<Shot["landing"]> | null = null;
        for (const r of all) {
          const L = r.shots[r.shots.length - 1]?.landing;
          if (L?.position && L.time_s <= t) land = L;
        }
        mini.querySelector(".mini-landing")!.innerHTML = land?.position
          ? `<g class="mini-land ${land.in_court ? "in" : "out"}" transform="translate(${land.position.x},${land.position.y})"><circle r="0.32"/><path d="M-0.2 -0.2 L0.2 0.2 M0.2 -0.2 L-0.2 0.2"/></g>`
          : "";
      }

      // rally list follows the playhead
      const id = inRally && rally ? rally.id : null;
      if (id !== currentId) {
        currentId = id;
        setCurrent(id);
      }
    }
    updateRef.current = update;

    let raf = 0;
    const loop = () => {
      update();
      raf = v.paused ? 0 : requestAnimationFrame(loop);
    };
    const setPlayIcon = () => {
      const playing = !v.paused;
      $("#play-icon")?.setAttribute(
        "d",
        playing ? "M5 4h3.5v12H5zM11.5 4H15v12h-3.5z" : "M6 4 L16 10 L6 16 Z",
      );
      $("#play")?.setAttribute("aria-label", playing ? "Pause" : "Play");
      const big = $<HTMLButtonElement>("#bigplay");
      if (big) big.hidden = playing;
    };
    const onPlay = () => {
      setPlayIcon();
      if (!raf) raf = requestAnimationFrame(loop);
    };
    const seek = (s: number) => {
      const d =
        v.duration && isFinite(v.duration)
          ? v.duration
          : matchRef.current.analysis.video.duration_s;
      v.currentTime = Math.min(Math.max(s, 0), d - 0.1);
      update();
    };
    seekRef.current = seek;
    const startAt = Number(
      new URLSearchParams(location.hash.split("?")[1] ?? "").get("t"),
    );
    const onMeta = () => {
      if (v.currentTime < 1)
        seek(
          startAt ||
            (matchRef.current.analysis.rallies[0]?.start_s ?? 0.5) - 0.5,
        );
    };
    v.addEventListener("play", onPlay);
    v.addEventListener("pause", setPlayIcon);
    v.addEventListener("seeked", update);
    v.addEventListener("loadedmetadata", update);
    v.addEventListener("loadedmetadata", onMeta, { once: true });

    const jumpRally = (dir: number) => {
      const t = v.currentTime;
      const all = matchRef.current.analysis.rallies;
      const list =
        dir > 0
          ? all.filter((r) => r.start_s > t + 0.5)
          : all.filter((r) => r.start_s < t - 1.5).reverse();
      if (list[0]) seek(list[0].start_s - 0.8);
    };
    jumpRef.current = jumpRally;
    const toggle = () => (v.paused ? void v.play().catch(() => {}) : v.pause());
    toggleRef.current = toggle;
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.closest?.("input, textarea, select") &&
        (target as HTMLInputElement).type !== "range"
      )
        return;
      if (e.key === " " && !target.closest?.("button")) {
        e.preventDefault();
        toggle();
      } else if (e.key === "[") jumpRally(-1);
      else if (e.key === "]") jumpRally(1);
      else if (e.key === "ArrowRight" && target === document.body)
        seek(v.currentTime + 5);
      else if (e.key === "ArrowLeft" && target === document.body)
        seek(v.currentTime - 5);
    };
    addEventListener("keydown", onKey);
    update();
    setPlayIcon();
    return () => {
      cancelAnimationFrame(raf);
      removeEventListener("keydown", onKey);
      v.removeEventListener("play", onPlay);
      v.removeEventListener("pause", setPlayIcon);
      v.removeEventListener("seeked", update);
      v.removeEventListener("loadedmetadata", update);
      v.removeEventListener("loadedmetadata", onMeta);
      v.pause();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // A rebuilt document (after a fix) or a moved mini court: redraw now.
  useEffect(() => updateRef.current(), [match, wide]);

  // keep the current rally in view while playing
  useEffect(() => {
    const list = rl.current;
    if (!current || !list || video.current?.paused) return;
    const li = list.querySelector<HTMLElement>(`[data-id="${current}"]`);
    if (li && list.scrollHeight > list.clientHeight)
      list.scrollTo({
        top: li.offsetTop - list.offsetTop - 12,
        behavior: "smooth",
      });
  }, [current]);

  /* ---- timeline: a tap jumps to the start of the rally under the finger; a drag scrubs ---- */
  const press = useRef<{ x: number; moved: boolean } | null>(null);
  const timeAt = (e: PointerEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    return Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1) * DUR;
  };

  async function applySwap(r: Rally) {
    if (chosen.length !== 2) return;
    setBusy(true);
    const [a, b] = chosen as [PersonId, PersonId];
    try {
      await swapRally(match.id, r.id, [a, b]);
      await refresh();
      toast(
        `Swapped ${nameOf(match, a)} and ${nameOf(match, b)} in rally ${rallyNumber(r)}. The match is rebuilt with the fix.`,
      );
      setOpen(null);
      setChosen([]);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function undo(r: Rally) {
    setBusy(true);
    try {
      await undoSwaps(match.id, r.id);
      await refresh();
      toast(`Undid the swap in rally ${rallyNumber(r)}.`);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const mini = <MiniCourt match={match} />;
  return (
    <div className="watch" ref={root}>
      <div className="watch-main">
        <div className="screen">
          <video
            ref={video}
            src={src ?? undefined}
            poster={posterUrl(match.id)}
            preload="metadata"
            playsInline
            onClick={() => toggleRef.current()}
            onError={() => setVideoError(true)}
          ></video>
          <svg className="ov" viewBox={`0 0 ${VW} ${VH}`} aria-hidden="true">
            <defs>
              <linearGradient id="beam" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stopColor="#ffe6b0" stopOpacity="0" />
                <stop offset="1" stopColor="#ffe6b0" stopOpacity="0.32" />
              </linearGradient>
              <radialGradient id="pool">
                <stop offset="0" stopColor="#ffe6b0" stopOpacity="0.45" />
                <stop offset="1" stopColor="#ffe6b0" stopOpacity="0" />
              </radialGradient>
            </defs>
            <g className={`ov-lines${linesOn ? "" : " off"}`}></g>
            <g className="ov-land"></g>
            <g className="ov-hit"></g>
          </svg>
          <button
            className="bigplay"
            id="bigplay"
            aria-label="Play"
            onClick={() => toggleRef.current()}
          >
            <svg viewBox="0 0 40 40" aria-hidden="true">
              <path d="M14 10 L31 20 L14 30 Z" />
            </svg>
          </button>
          {videoError ? (
            <p className="screen-error" role="alert">
              This browser cannot play the video file. The overlay and the
              numbers below still follow the match.
            </p>
          ) : null}
          {wide ? mini : null}
        </div>
        <div className="hud">
          <div className="hud-cell hud-stroke">
            <span className="hud-k">Last stroke</span>
            <span className="hud-v" id="h-stroke"></span>
            <span className="hud-s" id="h-who"></span>
          </div>
          <div className="hud-cell hud-speed" id="h-speed-cell">
            <span className="hud-k">Shot speed, approx.</span>
            <span className="hud-v" id="h-speed"></span>
            <span className="gauge" aria-hidden="true">
              <span className="gauge-fill" id="h-gauge"></span>
            </span>
            <span className="hud-s" id="h-speed-note"></span>
          </div>
          <div className="hud-cell hud-rally">
            <span className="hud-k" id="h-rally-k"></span>
            <span className="hud-v">
              <span id="h-shots"></span>
              <small> shots</small>
            </span>
            <span className="hud-s" id="h-time"></span>
          </div>
          <div className="hud-cell hud-won">
            <span className="hud-k">Rallies won so far</span>
            <span className="hud-v hud-score">
              <b className="t1" id="h-w1"></b>
              <i aria-hidden="true"></i>
              <b className="t2" id="h-w2"></b>
            </span>
            <span className="hud-s">
              {teamName(match, "T1")} v {teamName(match, "T2")}
            </span>
          </div>
          {wide ? null : mini}
        </div>
        <div className="transport">
          <button
            className="tbtn"
            id="play"
            aria-label="Play"
            onClick={() => toggleRef.current()}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path id="play-icon" d="M6 4 L16 10 L6 16 Z" />
            </svg>
          </button>
          <button
            className="tbtn"
            aria-label="Previous rally"
            onClick={() => jumpRef.current(-1)}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M5 4v12M16 4 L7 10 L16 16 Z" />
            </svg>
          </button>
          <button
            className="tbtn"
            aria-label="Next rally"
            onClick={() => jumpRef.current(1)}
          >
            <svg viewBox="0 0 20 20" aria-hidden="true">
              <path d="M15 4v12M4 4 L13 10 L4 16 Z" />
            </svg>
          </button>
          <span className="tclock">
            <span id="cur">0:00</span> / {clock(DUR)}
          </span>
          <label className="ttoggle">
            <input
              type="checkbox"
              checked={linesOn}
              onChange={(e) => setLinesOn(e.target.checked)}
            />{" "}
            Court lines
          </label>
        </div>
        <div
          className="timeline"
          onPointerDown={(e) => {
            press.current = { x: e.clientX, moved: false };
            e.currentTarget.setPointerCapture(e.pointerId);
          }}
          onPointerMove={(e) => {
            const p = press.current;
            if (!p) return;
            if (Math.abs(e.clientX - p.x) > 6) p.moved = true;
            if (p.moved) seekRef.current(timeAt(e));
          }}
          onPointerUp={(e) => {
            const p = press.current;
            if (!p) return;
            const t = timeAt(e);
            if (!p.moved && rallies.length) {
              const slack = DUR * 0.012;
              const hit =
                rallies.find(
                  (r) => t >= r.start_s - slack && t <= rallyEnd(r) + slack,
                ) ??
                rallies.reduce((best, r) =>
                  Math.abs(r.start_s - t) < Math.abs(best.start_s - t)
                    ? r
                    : best,
                );
              seekRef.current(hit.start_s - 0.8);
            }
            press.current = null;
          }}
          onPointerCancel={() => {
            press.current = null;
          }}
        >
          <div className="tl-rallies" aria-hidden="true">
            {rallies.map((r) => {
              const w = r.outcome?.winner_team;
              return (
                <span
                  key={r.id}
                  className={`tl-r ${w ? `w-${w}` : "w-none"}${r.outcome?.reason === "error" ? " err" : ""}`}
                  style={{
                    left: `${(r.start_s / DUR) * 100}%`,
                    width: `${Math.max(((rallyEnd(r) - r.start_s) / DUR) * 100, 0.35)}%`,
                  }}
                ></span>
              );
            })}
          </div>
          <div className="tl-head" id="tl-head"></div>
          <input
            type="range"
            id="scrub"
            ref={scrub}
            min={0}
            max={DUR}
            step={0.04}
            defaultValue={0}
            aria-label="Position in the video"
            onInput={(e) => seekRef.current(Number(e.currentTarget.value))}
          />
        </div>
        <p className="kbd-hint">
          Space plays and pauses. Arrow keys skip 5 seconds. [ and ] jump
          between rallies.
        </p>
      </div>
      <aside className="rallies" aria-labelledby="rl-title">
        <h2 id="rl-title" className="rallies-title">
          Rallies
        </h2>
        <ol className="rl" ref={rl}>
          {rallies.map((r) => {
            const w = r.outcome?.winner_team;
            const swaps = rallySwaps(A, r);
            const isOpen = open === r.id;
            return (
              <li
                key={r.id}
                className={`rl-item ${w ? `w-${w}` : "w-none"}${current === r.id ? " current" : ""}${isOpen ? " open" : ""}`}
                data-id={r.id}
              >
                <button
                  className="rl-jump"
                  onClick={() => {
                    seekRef.current(r.start_s - 0.8);
                    void video.current?.play().catch(() => {});
                  }}
                >
                  <span className="rl-num">{rallyNumber(r)}</span>
                  <span className="rl-meta">
                    <span>{clock(r.start_s)}</span>
                    <span>
                      {r.shots.length} {r.shots.length === 1 ? "shot" : "shots"}
                    </span>
                    <span>
                      {Math.max(0, rallyEnd(r) - r.start_s).toFixed(1)} s
                    </span>
                  </span>
                  <span className="rl-res">{resultSentence(match, r)}</span>
                </button>
                <div className="rl-fix">
                  {swaps.length ? (
                    <>
                      <span className="rl-swapped">
                        {swaps
                          .map(
                            (s) =>
                              `${nameOf(match, s.persons[0])} and ${nameOf(match, s.persons[1])}`,
                          )
                          .join("; ")}{" "}
                        swapped here
                      </span>
                      <button
                        className="link-quiet rl-undo"
                        disabled={busy}
                        onClick={() => undo(r)}
                      >
                        Undo
                      </button>
                    </>
                  ) : (
                    <button
                      className="link-quiet rl-open"
                      aria-expanded={isOpen}
                      onClick={() => {
                        setOpen(isOpen ? null : r.id);
                        setChosen([]);
                      }}
                    >
                      Two players mixed up here?
                    </button>
                  )}
                </div>
                {isOpen ? (
                  <div className="rl-panel">
                    <p>
                      Tap the two people who are the wrong way round in rally{" "}
                      {rallyNumber(r)}.
                    </p>
                    <div className="rl-people">
                      {people.map((p) => (
                        <button
                          key={p.id}
                          className={`chip side-${sideNumber(p.team)}`}
                          aria-pressed={chosen.includes(p.id)}
                          onClick={() =>
                            setChosen((c) =>
                              c.includes(p.id)
                                ? c.filter((x) => x !== p.id)
                                : [...c, p.id].slice(-2),
                            )
                          }
                        >
                          <Face match={match} id={p.id} />
                          {firstName(match, p.id)}
                        </button>
                      ))}
                    </div>
                    <div className="rl-panel-actions">
                      <button
                        className="btn btn-small"
                        disabled={chosen.length !== 2 || busy}
                        onClick={() => applySwap(r)}
                      >
                        {busy ? "Rebuilding…" : "Swap them in this rally"}
                      </button>
                      <button
                        className="link-quiet rl-cancel"
                        onClick={() => {
                          setOpen(null);
                          setChosen([]);
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      </aside>
    </div>
  );
}
