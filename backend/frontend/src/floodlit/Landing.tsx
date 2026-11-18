import { useEffect, useRef, useState } from "react";
import { listMatches, loadAnalysis, matchStatus, posterUrl } from "./api.js";
import type { HeroMatch, HeroShotEvent } from "./hero.js";
import {
  firstName,
  inv3,
  prepareMatch,
  rallyNumber,
  teamName,
  type Matrix,
} from "./model.js";
import sample from "./sample-rally.json";

const PHONE = "(max-width: 760px)";
const reducedMotion = () =>
  matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The bundled sample rally, shaped like a match for the hero. */
function sampleMatch(): HeroMatch {
  const analysis = sample as unknown as HeroMatch["analysis"] & {
    court: {
      views: { start_frame: number; end_frame: number; homography: Matrix }[];
    };
  };
  return {
    analysis,
    trackIndex: new Map(analysis.tracks.persons.map((p) => [p.person_id, p])),
    views: analysis.court.views.map((v) => ({
      ...v,
      inverse: inv3(v.homography),
    })),
  };
}

interface Replay {
  match: HeroMatch;
  /** The user's match, or null for the bundled sample. */
  id: string | null;
}

/** The newest ready match, else the sample rally. */
async function findReplay(
  signal: AbortSignal,
): Promise<{ replay: Replay; any: boolean }> {
  let any = false;
  try {
    const matches = await listMatches(signal);
    any = matches.length > 0;
    for (const m of matches.slice(0, 8)) {
      const status = await matchStatus(m.match_id, signal);
      if (status.state !== "ready") continue;
      const analysis = await loadAnalysis(m.match_id, signal);
      if (!analysis.rallies.some((r) => r.shots.length >= 2)) continue;
      return {
        replay: {
          match: prepareMatch(m.match_id, analysis, null),
          id: m.match_id,
        },
        any,
      };
    }
  } catch (error) {
    if (signal.aborted) throw error;
    console.warn("Showing the sample rally:", error);
  }
  return { replay: { match: sampleMatch(), id: null }, any };
}

export function Landing() {
  const stage = useRef<HTMLDivElement>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [hasMatches, setHasMatches] = useState(false);
  const [what, setWhat] = useState("Loading a rally");
  const [shot, setShot] = useState({ num: "0", of: "", stroke: "" });
  const [live, setLive] = useState(false);

  useEffect(() => {
    const ctl = new AbortController();
    findReplay(ctl.signal).then(
      ({ replay, any }) => {
        setReplay(replay);
        setHasMatches(any);
      },
      () => {},
    );
    return () => ctl.abort();
  }, []);

  useEffect(() => {
    if (!replay) return;
    const el = stage.current;
    if (!el) return;
    const match = replay.match;
    let hero: { destroy(): void } | null = null;
    let disposed = false;
    const phoneMq = matchMedia(PHONE);
    const onShot = ({ index, total, shot, label, speed }: HeroShotEvent) => {
      const who = shot.hitter_id ? firstName(match, shot.hitter_id) : "Someone";
      setShot({
        num: String(index + 1),
        of: ` of ${total} shots`,
        stroke: `${who}, ${label.toLowerCase()}${
          speed?.kmh
            ? `, ${speed.kmh} km/h${speed.settled ? " est. at +0.1 s" : ""}`
            : speed?.bound
              ? ", launch speed uncertain"
              : ""
        }`,
      });
    };
    async function build() {
      hero?.destroy();
      hero = null;
      const { createHero } = await import("./hero.js");
      await Promise.all([
        document.fonts.load('800 100px "Anybody Variable"'),
        document.fonts.load('600 40px "Archivo Variable"'),
      ]).catch(() => {});
      if (disposed || !el) return;
      const created = createHero(el, match, {
        still: reducedMotion(),
        phone: phoneMq.matches,
        onShot,
      });
      hero = created;
      const r = created.rally;
      setWhat(
        replay!.id
          ? `Rally ${rallyNumber(r)} of ${teamName(match, "T1")} v ${teamName(match, "T2")}, rebuilt from the tracking`
          : `Rally ${(sample as { rally_number?: number }).rally_number ?? rallyNumber(r)} of a sample doubles match, rebuilt from the tracking`,
      );
      setLive(true);
    }
    const rebuild = () => build().catch(fail);
    const fail = (error: unknown) => {
      console.warn("The 3D replay could not start:", error);
      setWhat(
        "The 3D replay needs WebGL, so here is a still from the match instead.",
      );
    };
    build().catch(fail);
    phoneMq.addEventListener("change", rebuild);
    return () => {
      disposed = true;
      phoneMq.removeEventListener("change", rebuild);
      hero?.destroy();
    };
  }, [replay]);

  const posterId = replay?.id;
  return (
    <>
      <section className="hero" aria-labelledby="hero-title">
        <div className={`hero-stage${live ? " live" : ""}`} ref={stage}>
          <div
            className="hero-fallback"
            style={
              posterId
                ? { backgroundImage: `url(${posterUrl(posterId)})` }
                : undefined
            }
          ></div>
          <div className="hero-shade" aria-hidden="true"></div>
          <aside className="hero-readout" aria-label="The rally being replayed">
            <p className="readout-what">{what}</p>
            <div className="readout-row">
              <div className="readout-count">
                <span className="readout-num">{shot.num}</span>
                <span className="readout-unit">{shot.of}</span>
              </div>
              <div className="readout-stroke">{shot.stroke}</div>
            </div>
            <p className="readout-hint">
              <span className="hint-mouse">Drag to look around the hall</span>
              <span className="hint-touch">Swipe sideways to look around</span>
            </p>
          </aside>
        </div>
        <div className="hero-copy">
          <h1 id="hero-title" className="hero-title">
            <span>Every rally,</span>
            <span>back under</span>
            <span>the lights</span>
          </h1>
          <p className="hero-lede">
            Upload a video of your singles or doubles match. We find the court,
            follow every player and the shuttle, and give you each rally, stroke
            and speed to watch back.
          </p>
          <div className="hero-actions">
            <a className="btn btn-flood" href="#/upload">
              Analyse a match
            </a>
            {replay?.id ? (
              <a className="link-quiet" href={`#/match/${replay.id}/watch`}>
                Open your latest match
              </a>
            ) : hasMatches ? (
              <a className="link-quiet" href="#/matches">
                See your matches
              </a>
            ) : null}
          </div>
        </div>
      </section>
      <section className="steps" aria-labelledby="steps-title">
        <h2 id="steps-title" className="section-title">
          From video to rally-by-rally in three steps
        </h2>
        <ol className="steps-list">
          <li>
            <h3>Upload the video</h3>
            <p>
              A whole game or a highlight reel, filmed from behind one end like
              a broadcast. Add the players' names.
            </p>
          </li>
          <li>
            <h3>Confirm who is who</h3>
            <p>
              We show a picture of each person we found with the name we think
              fits. Tap two to swap them.
            </p>
          </li>
          <li>
            <h3>Watch and read the match</h3>
            <p>
              Every rally with the hitter lit up, stroke and speed, plus where
              each of you stood, won and lost points.
            </p>
          </li>
        </ol>
      </section>
    </>
  );
}
