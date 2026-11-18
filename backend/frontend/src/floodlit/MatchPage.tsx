import { useCallback, useEffect, useState } from "react";
import { ApiError } from "../api/client.js";
import { Analysis } from "./Analysis.js";
import {
  errorText,
  loadAnalysis,
  loadStats,
  matchStatus,
  thumbnailUrl,
} from "./api.js";
import {
  matchHome,
  nameOf,
  prepareMatch,
  ralliesWon,
  teamName,
  teamPlayers,
  type Match,
  type Team,
} from "./model.js";
import { go } from "./shell.js";
import { Watch } from "./Watch.js";

async function fetchMatch(id: string, signal?: AbortSignal): Promise<Match> {
  const [analysis, stats] = await Promise.all([
    loadAnalysis(id, signal),
    loadStats(id, signal).catch((e: unknown) => {
      if (signal?.aborted) throw e;
      console.warn("Statistics unavailable:", e);
      return null;
    }),
  ]);
  const photos = Object.fromEntries(
    analysis.players.map((p) => [
      p.id,
      p.thumbnail ? thumbnailUrl(id, p.id) : null,
    ]),
  );
  return prepareMatch(id, analysis, stats, photos);
}

export function Face({ match, id }: { match: Match; id: string }) {
  const src = match.photos[id];
  return src ? (
    <img src={src} alt="" />
  ) : (
    <span className="face-none" aria-hidden="true">
      {nameOf(match, id).slice(0, 1)}
    </span>
  );
}

export function MatchPage({
  id,
  tab,
}: {
  id: string;
  tab: "watch" | "analysis";
}) {
  const [match, setMatch] = useState<Match | null>(null);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    const ctl = new AbortController();
    fetchMatch(id, ctl.signal).then(
      (m) => {
        if (m.analysis.names_confirmed === false) go(`#/match/${id}/names`);
        else setMatch(m);
      },
      async (e: unknown) => {
        if (ctl.signal.aborted) return;
        if (e instanceof ApiError && e.status === 404) {
          // Not built yet: send the user where the match stands.
          const status = await matchStatus(id, ctl.signal).catch(() => null);
          if (status && status.state !== "ready")
            return go(matchHome(id, status.state));
        }
        setProblem(errorText(e));
      },
    );
    return () => ctl.abort();
  }, [id]);

  /** After a fix: the rebuilt document and its statistics. */
  const refresh = useCallback(async () => {
    setMatch(await fetchMatch(id));
  }, [id]);

  if (problem || !match)
    return (
      <section className="matchpage">
        <p
          className={problem ? "form-error" : "lede"}
          role={problem ? "alert" : undefined}
        >
          {problem || "Fetching the match…"}
        </p>
        {problem ? (
          <p className="page-actions">
            <a className="btn" href="#/matches">
              Your matches
            </a>
          </p>
        ) : null}
      </section>
    );

  const A = match.analysis;
  const rallies = A.rallies;
  const won = ralliesWon(rallies);
  const unknown = rallies.filter((r) => !r.outcome?.winner_team).length;
  const side = (team: Team, k: number) => (
    <div className={`sb-side sb-${k}`}>
      <div className="sb-faces">
        {teamPlayers(match, team).map((p) => (
          <Face key={p.id} match={match} id={p.id} />
        ))}
      </div>
      <div className="sb-names">
        {teamPlayers(match, team).map((p) => (
          <span key={p.id}>{nameOf(match, p.id)}</span>
        ))}
      </div>
      <div className="sb-won">
        <span className="sb-num">{won[team]}</span>
        <small>rallies won</small>
      </div>
    </div>
  );
  return (
    <section className="matchpage" aria-labelledby="mp-title">
      <header className="scoreboard">
        <h1 id="mp-title" className="visually-hidden">
          {teamName(match, "T1")} v {teamName(match, "T2")}
        </h1>
        {side("T1", 1)}
        <div className="sb-mid">
          <span>{rallies.length} rallies</span>
          {unknown ? <span>{unknown} with no result</span> : null}
          <span>{Math.round(A.video.duration_s / 60)} min of video</span>
        </div>
        {side("T2", 2)}
      </header>
      <nav className="tabs" aria-label="Match views">
        <a
          href={`#/match/${id}/watch`}
          className="tab"
          aria-current={tab === "watch" ? "page" : undefined}
        >
          Watch
        </a>
        <a
          href={`#/match/${id}/analysis`}
          className="tab"
          aria-current={tab === "analysis" ? "page" : undefined}
        >
          Analysis
        </a>
      </nav>
      <div id="tab-body">
        {tab === "analysis" ? (
          <Analysis match={match} />
        ) : (
          <Watch match={match} refresh={refresh} />
        )}
      </div>
    </section>
  );
}
