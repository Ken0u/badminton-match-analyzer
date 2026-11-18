import { useEffect, useState } from "react";
import {
  errorText,
  listMatches,
  matchPlayers,
  matchStatus,
  resumeMatch,
} from "./api.js";
import {
  STATE_TEXT,
  matchHome,
  type MatchStatus,
  type MatchSummary,
} from "./model.js";
import { go, useToast } from "./shell.js";

interface Row {
  summary: MatchSummary;
  status: MatchStatus | null;
  /** Names by side, when the server has them. */
  teams: string[][] | null;
}

const dateText = (seconds: number) =>
  new Date(seconds * 1000).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

async function loadRows(signal: AbortSignal): Promise<Row[]> {
  const summaries = await listMatches(signal);
  return Promise.all(
    summaries.map(async (summary) => {
      const status = await matchStatus(summary.match_id, signal).catch(
        () => null,
      );
      let teams: string[][] | null = null;
      if (
        status &&
        (status.state === "ready" || status.state === "needs_names")
      ) {
        const players = await matchPlayers(summary.match_id, signal).catch(
          () => null,
        );
        if (players) teams = ["T1", "T2"].map((t) => players.teams[t] ?? []);
      }
      return { summary, status, teams };
    }),
  );
}

export function Matches() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const toast = useToast();

  useEffect(() => {
    const ctl = new AbortController();
    loadRows(ctl.signal).then(
      (r) => {
        setRows(r);
        setError("");
      },
      (e) => {
        if (!ctl.signal.aborted) setError(errorText(e));
      },
    );
    // Refresh while something is processing, politely.
    return () => ctl.abort();
  }, [reload]);
  const processing = rows?.some(
    (r) => r.status?.state === "running" || r.status?.state === "queued",
  );
  useEffect(() => {
    if (!processing) return;
    const timer = window.setTimeout(() => setReload((n) => n + 1), 5000);
    return () => clearTimeout(timer);
  }, [processing, rows]);

  async function resume(id: string) {
    setBusy(id);
    try {
      await resumeMatch(id);
      go(`#/match/${id}/processing`);
    } catch (e) {
      toast(errorText(e));
      setBusy(null);
    }
  }

  return (
    <section className="page matches" aria-labelledby="ml-title">
      <div className="ml-head">
        <h1 id="ml-title" className="page-title">
          Your matches
        </h1>
        <a className="btn btn-flood" href="#/upload">
          Analyse a match
        </a>
      </div>
      {error ? (
        <p className="form-error ml-error" role="alert">
          {error}{" "}
          <button
            className="link-quiet"
            onClick={() => setReload((n) => n + 1)}
          >
            Try again
          </button>
        </p>
      ) : !rows ? (
        <p className="lede ml-empty">Fetching your matches…</p>
      ) : !rows.length ? (
        <div className="ml-empty">
          <p className="lede">
            No matches yet. Upload a video and it will wait for you here.
          </p>
        </div>
      ) : (
        <ol className="ml">
          {rows.map(({ summary, status, teams }) => {
            const state = status?.state;
            const sides =
              teams && teams.every((t) => t.length)
                ? teams.map((t) => t.join(" & "))
                : null;
            const href = state ? matchHome(summary.match_id, state) : null;
            return (
              <li
                key={summary.match_id}
                className={`ml-item state-${state ?? "unknown"}`}
              >
                <span className="ml-lamp" aria-hidden="true">
                  <i></i>
                </span>
                <div className="ml-main">
                  <p className="ml-names">
                    {sides ? (
                      <>
                        <span className="t1">{sides[0]}</span>
                        <span className="ml-v"> v </span>
                        <span className="t2">{sides[1]}</span>
                      </>
                    ) : (
                      summary.name || "Untitled video"
                    )}
                  </p>
                  <p className="ml-meta">
                    <span>
                      {summary.mode === "doubles" ? "Doubles" : "Singles"}
                    </span>
                    <span>{dateText(summary.created_at)}</span>
                    {sides && summary.name ? <span>{summary.name}</span> : null}
                  </p>
                </div>
                <div className="ml-state">
                  <span className="ml-state-text">
                    {state ? STATE_TEXT[state] : "Status unavailable"}
                    {state === "running" && status
                      ? ` · ${Math.round(status.progress * 100)}%`
                      : ""}
                  </span>
                  {state === "failed" || state === "paused" ? (
                    <button
                      className="btn btn-small"
                      disabled={busy === summary.match_id}
                      onClick={() => resume(summary.match_id)}
                    >
                      {busy === summary.match_id ? "Resuming…" : "Resume"}
                    </button>
                  ) : href ? (
                    <a
                      className={`btn btn-small${state === "ready" ? " btn-flood" : ""}`}
                      href={href}
                    >
                      {state === "ready"
                        ? "Open"
                        : state === "needs_names"
                          ? "Check names"
                          : "Follow progress"}
                    </a>
                  ) : null}
                </div>
                {(state === "failed" || state === "paused") && status?.error ? (
                  <p className="ml-why">{status.error}</p>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
