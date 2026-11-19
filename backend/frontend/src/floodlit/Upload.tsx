import { useEffect, useRef, useState, type FormEvent } from "react";
import { errorText, startFromLink, uploadMatch } from "./api.js";
import type { Mode } from "./model.js";
import { go } from "./shell.js";
import { isCancellation } from "../api/client.js";

type Names = { T1: string[]; T2: string[] };

const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "youtu.be",
]);
const VIDEO_ID = /^[A-Za-z0-9_-]{11}$/;

/** A pasted YouTube link, tidied, and what is obviously wrong with it ("" if
 * nothing). The server checks it properly before anything starts. */
export function checkLink(raw: string): { url: string; problem: string } {
  let url = raw.trim();
  if (!url) return { url, problem: "" };
  if (/^http:\/\//i.test(url)) url = `https://${url.slice(7)}`;
  else if (!/^[a-z][a-z0-9+.-]*:/i.test(url)) url = `https://${url}`;
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return {
      url,
      problem: "That does not look like a link. Copy it from YouTube.",
    };
  }
  if (parsed.protocol !== "https:" || !YOUTUBE_HOSTS.has(parsed.hostname))
    return {
      url,
      problem: "That is not a YouTube link. Paste a link to one YouTube video.",
    };
  const keys = [...parsed.searchParams.keys()].map((k) => k.toLowerCase());
  if (
    keys.some((k) => ["list", "playlist", "index", "start_radio"].includes(k))
  )
    return {
      url,
      problem: "That link is a playlist. Open the one video and copy its link.",
    };
  const path = parsed.pathname.replace(/\/$/, "");
  const id =
    parsed.hostname === "youtu.be"
      ? path.slice(1)
      : path === "/watch"
        ? (parsed.searchParams.get("v") ?? "")
        : (/^\/(?:shorts|live)\/([^/]+)$/.exec(path)?.[1] ?? "");
  if (!VIDEO_ID.test(id))
    return {
      url,
      problem:
        "That link does not point to one video. Open the video and copy its link.",
    };
  return { url, problem: "" };
}

/** Plain checks before anything is sent; the server checks again. */
export function uploadProblem(
  file: File | null,
  mode: Mode,
  names: Names,
  link = "",
): string {
  if (link.trim()) {
    const { problem } = checkLink(link);
    if (problem) return problem;
  } else if (!file) return "Choose a video or paste a YouTube link first.";
  const per = mode === "doubles" ? 2 : 1;
  const all = [...names.T1.slice(0, per), ...names.T2.slice(0, per)].map((n) =>
    n.trim(),
  );
  if (all.length < per * 2 || all.some((n) => !n))
    return "Fill in every name. Nicknames are fine.";
  if (all.some((n) => n.length > 100))
    return "Keep each name under 100 characters.";
  if (new Set(all.map((n) => n.toLowerCase())).size !== all.length)
    return "Give everyone a different name, so we can tell them apart.";
  return "";
}

export function Upload() {
  const [mode, setMode] = useState<Mode>("doubles");
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const [names, setNames] = useState<Names>({ T1: ["", ""], T2: ["", ""] });
  const [link, setLink] = useState("");
  const [linkChecked, setLinkChecked] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState<number | null>(null);
  const [sending, setSending] = useState(false);
  const upload = useRef<AbortController | null>(null);
  useEffect(() => () => upload.current?.abort(), []);
  const per = mode === "doubles" ? 2 : 1;

  function setName(team: "T1" | "T2", i: number, value: string) {
    setNames((n) => {
      const next = { ...n, [team]: [...n[team]] };
      next[team][i] = value;
      return next;
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (upload.current) return;
    const problem = uploadProblem(file, mode, names, link);
    setLinkChecked(true);
    setError(problem);
    if (problem || (!file && !link.trim())) return;
    const ctl = new AbortController();
    upload.current = ctl;
    const team1 = names.T1.slice(0, per).map((n) => n.trim());
    const team2 = names.T2.slice(0, per).map((n) => n.trim());
    if (link.trim()) {
      setSending(true);
      try {
        const created = await startFromLink(
          checkLink(link).url,
          mode,
          team1,
          team2,
          ctl.signal,
        );
        go(`#/match/${created.match_id}/processing`);
      } catch (err) {
        if (!isCancellation(err)) setError(errorText(err));
      } finally {
        upload.current = null;
        setSending(false);
      }
      return;
    }
    if (!file) return;
    setSent(0);
    try {
      const created = await uploadMatch(
        file,
        mode,
        team1,
        team2,
        ctl.signal,
        ({ loaded, total }) => setSent(total ? loaded / total : null),
      );
      go(`#/match/${created.match_id}/processing`);
    } catch (err) {
      if (!isCancellation(err)) setError(errorText(err));
      setSent(null);
    } finally {
      upload.current = null;
    }
  }

  const uploading = sent !== null || sending || upload.current !== null;
  const linkProblem = linkChecked ? checkLink(link).problem : "";
  const choose = (f: File) => {
    setFile(f);
    setLink("");
    setLinkChecked(false);
  };
  return (
    <section className="page upload" aria-labelledby="up-title">
      <h1 id="up-title" className="page-title">
        Analyse a match
      </h1>
      <div className="upload-grid">
        <form onSubmit={submit} noValidate>
          <div className="source">
            <label
              className={`drop${file ? " has-file" : ""}${over ? " over" : ""}${
                link.trim() ? " is-quiet" : ""
              }`}
              onDragEnter={(e) => {
                e.preventDefault();
                setOver(true);
              }}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(true);
              }}
              onDragLeave={(e) => {
                e.preventDefault();
                setOver(false);
              }}
              onDrop={(e) => {
                e.preventDefault();
                setOver(false);
                const f = e.dataTransfer.files[0];
                if (f && !uploading) choose(f);
              }}
            >
              <input
                type="file"
                accept="video/*,.mp4,.mov,.mkv,.avi,.webm,.m4v"
                className="visually-hidden"
                disabled={uploading}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) choose(f);
                  e.target.value = "";
                }}
              />
              <svg
                className="drop-lines"
                viewBox="0 0 610 300"
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <rect x="1" y="1" width="608" height="298" />
                <line x1="46" y1="1" x2="46" y2="299" />
                <line x1="564" y1="1" x2="564" y2="299" />
                <line x1="1" y1="40" x2="609" y2="40" />
                <line x1="305" y1="236" x2="305" y2="299" />
                <line x1="1" y1="236" x2="609" y2="236" />
              </svg>
              <span className="drop-main">
                {file ? file.name : "Drop your match video here"}
              </span>
              <span className="drop-sub">
                {file
                  ? "Ready. Choose another file to replace it."
                  : "or choose a file. MP4 or MOV, a whole game or a highlight reel."}
              </span>
            </label>
            <div className="src-or" aria-hidden="true">
              <span>or</span>
            </div>
            <div className={`link-in${linkProblem ? " is-bad" : ""}`}>
              <label htmlFor="up-link">Paste a YouTube link</label>
              <div className="link-row">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="2.5" y="5" width="19" height="14" rx="4" />
                  <path d="M10 9.2v5.6l4.8-2.8z" />
                </svg>
                <input
                  id="up-link"
                  type="url"
                  inputMode="url"
                  autoComplete="off"
                  spellCheck={false}
                  placeholder="https://www.youtube.com/watch?v=…"
                  value={link}
                  disabled={uploading}
                  aria-invalid={linkProblem ? true : undefined}
                  aria-describedby="up-link-note"
                  onChange={(e) => {
                    setLink(e.target.value);
                    if (e.target.value.trim()) setFile(null);
                    else setLinkChecked(false);
                  }}
                  onBlur={() => setLinkChecked(Boolean(link.trim()))}
                />
                {link && !uploading ? (
                  <button
                    type="button"
                    className="link-clear"
                    aria-label="Clear the link"
                    onClick={() => {
                      setLink("");
                      setLinkChecked(false);
                    }}
                  >
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M4 4l8 8M12 4l-8 8" />
                    </svg>
                  </button>
                ) : null}
              </div>
              <p id="up-link-note" className="link-note">
                {linkProblem ||
                  "One public video. The analyzer downloads it first, then starts."}
              </p>
            </div>
          </div>

          <fieldset className="mode" disabled={uploading}>
            <legend>What was played</legend>
            <label className="mode-opt">
              <input
                type="radio"
                name="mode"
                value="singles"
                checked={mode === "singles"}
                onChange={() => setMode("singles")}
              />
              <svg viewBox="0 0 40 70" aria-hidden="true">
                <rect x="2" y="2" width="36" height="66" />
                <line x1="2" y1="35" x2="38" y2="35" />
                <circle cx="20" cy="18" r="3.5" />
                <circle cx="20" cy="52" r="3.5" />
              </svg>
              <span>
                Singles<small>One player each side</small>
              </span>
            </label>
            <label className="mode-opt">
              <input
                type="radio"
                name="mode"
                value="doubles"
                checked={mode === "doubles"}
                onChange={() => setMode("doubles")}
              />
              <svg viewBox="0 0 40 70" aria-hidden="true">
                <rect x="2" y="2" width="36" height="66" />
                <line x1="2" y1="35" x2="38" y2="35" />
                <circle cx="12" cy="18" r="3.5" />
                <circle cx="28" cy="22" r="3.5" />
                <circle cx="13" cy="50" r="3.5" />
                <circle cx="27" cy="54" r="3.5" />
              </svg>
              <span>
                Doubles<small>Two partners each side</small>
              </span>
            </label>
          </fieldset>

          <fieldset className="names-in" disabled={uploading}>
            <legend>Who played</legend>
            <p className="hint">
              {mode === "doubles"
                ? "Put partners on the same side so we know who plays together. The order within a side does not matter."
                : "Any order. You will match names to people after the analysis."}
            </p>
            <div className="sides">
              {(["T1", "T2"] as const).map((team, k) => (
                <div key={team} style={{ display: "contents" }}>
                  {k === 1 ? (
                    <div className="side-net" aria-hidden="true"></div>
                  ) : null}
                  <div className={`side side-${k + 1}`}>
                    <h3>
                      {mode === "doubles" ? `Pair ${k + 1}` : `Player ${k + 1}`}
                    </h3>
                    {Array.from({ length: per }, (_, i) => (
                      <label className="field" key={i}>
                        <span>
                          {mode === "doubles" ? `Partner ${i + 1}` : "Name"}
                        </span>
                        <input
                          name={`${team}-${i}`}
                          autoComplete="off"
                          maxLength={100}
                          value={names[team][i] ?? ""}
                          onChange={(e) => setName(team, i, e.target.value)}
                          required
                        />
                      </label>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </fieldset>
          <p className="form-error" role="alert">
            {error}
          </p>
          <div className="up-actions">
            <button
              className="btn btn-flood"
              type="submit"
              disabled={uploading}
            >
              {sending
                ? "Checking the link…"
                : sent === null
                  ? uploading
                    ? "Uploading…"
                    : "Start analysis"
                  : `Uploading ${Math.round(sent * 100)}%`}
            </button>
            {sent !== null ? (
              <button
                type="button"
                className="link-quiet"
                onClick={() => upload.current?.abort()}
              >
                Cancel the upload
              </button>
            ) : null}
          </div>
          {sent !== null ? (
            <div
              className="up-bar"
              role="progressbar"
              aria-label="Upload"
              aria-valuemin={0}
              aria-valuemax={100}
              {...(sent !== null
                ? { "aria-valuenow": Math.round(sent * 100) }
                : {})}
            >
              <span style={{ width: `${(sent ?? 0) * 100}%` }}></span>
            </div>
          ) : null}
        </form>
        <aside className="tips" aria-labelledby="tips-title">
          <svg viewBox="0 0 220 170" aria-hidden="true">
            <path className="tips-court" d="M62 20 H158 L196 132 H24 Z" />
            <path className="tips-court-l" d="M110 20 V132 M43 76 H177" />
            <path className="tips-cone" d="M110 164 L40 24 H180 Z" />
            <circle className="tips-cam" cx="110" cy="160" r="6" />
          </svg>
          <h2 id="tips-title">What works best</h2>
          <ul>
            <li>
              Filmed from behind one end, high enough to see all four corners of
              the court.
            </li>
            <li>
              A camera that stays still. Cuts between camera angles are fine.
            </li>
            <li>
              Anything from one rally to a whole match. Longer videos give
              fuller numbers.
            </li>
          </ul>
          <p>
            Analysis runs on the analyzer's computer, so you can close the page
            while it works.
          </p>
        </aside>
      </div>
    </section>
  );
}
