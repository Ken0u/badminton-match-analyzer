import { useEffect, useRef, useState } from "react";
import { errorText, matchStatus, pauseMatch, resumeMatch } from "./api.js";
import type { MatchStatus } from "./model.js";
import { go, useToast } from "./shell.js";

const LAMPS = 5;
/** What each stage label from the server means, in a sentence. */
export const STAGE_DETAIL: Record<string, string> = {
  "Waiting to start": "It starts as soon as the analyzer is free.",
  "Downloading the video":
    "Fetching the video from YouTube onto the analyzer's computer",
  "Preparing the video": "Reading the file and the time of every frame",
  "Scanning the video":
    "Finding camera cuts and the court lines in every angle",
  "Finding players": "Following each person around the court",
  "Tracking the shuttle": "Spotting the shuttle in every frame",
  "Reading strokes": "Finding each contact and naming the stroke",
  "Recognising players": "Telling the players apart through the whole video",
  "Reading rally outcomes": "Working out where rallies ended and who won them",
  "Building the analysis": "Putting every rally and number together",
  Pausing: "Stopping at the next safe point. Finished work is kept.",
  Paused: "Finished work is kept. Resume to carry on from here.",
};
const POLL_MS = 2000;

export function Processing({ id }: { id: string }) {
  const [status, setStatus] = useState<MatchStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [poll, setPoll] = useState(0);
  const leaving = useRef(0);
  const toast = useToast();

  // Poll politely: one request at a time, every 2 s, and not while hidden.
  useEffect(() => {
    const ctl = new AbortController();
    let timer = 0;
    const next = () => {
      timer = window.setTimeout(tick, POLL_MS);
    };
    const tick = () => {
      if (document.hidden) {
        document.addEventListener("visibilitychange", tick, { once: true });
        return;
      }
      matchStatus(id, ctl.signal).then(
        (s) => {
          // A link match takes its video's id once the video is downloaded.
          if (s.match_id !== id) {
            go(`#/match/${s.match_id}/processing`, true);
            return;
          }
          setStatus(s);
          setError("");
          if (s.state === "running" || s.state === "queued") next();
        },
        (e) => {
          if (ctl.signal.aborted) return;
          setError(errorText(e));
          next();
        },
      );
    };
    tick();
    return () => {
      ctl.abort();
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", tick);
    };
  }, [id, poll]);

  // Finished: name confirmation next, or straight to the match.
  const state = status?.state;
  useEffect(() => {
    if (state !== "needs_names" && state !== "ready") return;
    leaving.current = window.setTimeout(
      () => go(`#/match/${id}/${state === "ready" ? "watch" : "names"}`),
      state === "ready" ? 1200 : 900,
    );
    return () => clearTimeout(leaving.current);
  }, [state, id]);

  async function resume() {
    setBusy(true);
    try {
      await resumeMatch(id);
      setStatus(null);
      setPoll((n) => n + 1);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function pause() {
    setBusy(true);
    try {
      setStatus(await pauseMatch(id).then(() => matchStatus(id)));
      setPoll((n) => n + 1);
    } catch (e) {
      toast(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const done = state === "needs_names" || state === "ready";
  const stopped = state === "failed" || state === "paused";
  const progress = status ? (done ? 1 : status.progress) : 0;
  const pct = Math.round(progress * 100);
  // Lamps light in turn as the whole job advances; the next one warms up.
  const lit = Math.min(
    Math.floor(Math.min(progress, 0.999) * LAMPS),
    LAMPS - 1,
  );
  const stage = !status
    ? "Checking on the analysis"
    : done
      ? "Done"
      : state === "failed"
        ? "Stopped"
        : status.stage;
  const detail = !status
    ? ""
    : done
      ? state === "ready"
        ? "Opening the match."
        : "Next, check who is who."
      : state === "failed"
        ? status.video_id === null
          ? "The video was not downloaded. Resuming tries the download again."
          : "Finished work is kept, so resuming carries on from where it stopped."
        : (STAGE_DETAIL[status.stage] ?? "");

  return (
    <section
      className={`page processing${stopped ? " is-stopped" : ""}`}
      aria-labelledby="pr-title"
    >
      <div className="lamps" aria-hidden="true">
        {Array.from({ length: LAMPS }, (_, i) => (
          <span
            key={i}
            className={`lamp${i < lit || done ? " on" : ""}${
              i === lit && !done && !stopped && status ? " warming" : ""
            }`}
          >
            <i></i>
          </span>
        ))}
      </div>
      <div className="proc-court" aria-hidden="true">
        <div
          className="proc-pool"
          style={{ ["--lit" as string]: progress.toFixed(3) }}
        ></div>
      </div>
      <div className="proc-copy">
        <h1 id="pr-title" className="visually-hidden">
          Analysing your match
        </h1>
        <p className="proc-file">{status?.name ?? ""}</p>
        <div
          className="proc-num"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          aria-labelledby="stage-name"
        >
          <span>{pct}</span>
          <small>%</small>
        </div>
        <p className="proc-stage" id="stage-name">
          {stage}
        </p>
        <p className="proc-detail">{detail}</p>
        {stopped && status?.error ? (
          <p className="proc-error" role="alert">
            {status.error}
          </p>
        ) : null}
        {error ? (
          <p className="proc-error" role="alert">
            {error}
          </p>
        ) : null}
        {stopped ? (
          <div className="proc-actions">
            <button className="btn btn-flood" onClick={resume} disabled={busy}>
              {busy ? "Resuming…" : "Resume the analysis"}
            </button>
            <a className="link-quiet" href="#/matches">
              Back to your matches
            </a>
          </div>
        ) : (
          <>
            <p className="proc-note">
              You can close this page. We will keep going and the match will be
              waiting for you in Your matches.
            </p>
            {state === "running" ? (
              <button
                className="link-quiet proc-pause"
                onClick={pause}
                disabled={busy}
              >
                Pause the analysis
              </button>
            ) : null}
          </>
        )}
        {status?.warnings.length ? (
          <div className="warn proc-warn">
            {status.warnings.map((w) => (
              <p key={w}>{w}</p>
            ))}
          </div>
        ) : null}
      </div>
    </section>
  );
}
