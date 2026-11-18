import { useEffect, useRef, useState, type FormEvent } from "react";
import { errorText, uploadMatch } from "./api.js";
import type { Mode } from "./model.js";
import { go } from "./shell.js";
import { isCancellation } from "../api/client.js";

type Names = { T1: string[]; T2: string[] };

/** Plain checks before anything is sent; the server checks again. */
export function uploadProblem(
  file: File | null,
  mode: Mode,
  names: Names,
): string {
  if (!file) return "Choose a video first.";
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
  const [error, setError] = useState("");
  const [sent, setSent] = useState<number | null>(null);
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
    const problem = uploadProblem(file, mode, names);
    setError(problem);
    if (problem || !file) return;
    const ctl = new AbortController();
    upload.current = ctl;
    setSent(0);
    try {
      const created = await uploadMatch(
        file,
        mode,
        names.T1.slice(0, per).map((n) => n.trim()),
        names.T2.slice(0, per).map((n) => n.trim()),
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

  const uploading = sent !== null || upload.current !== null;
  return (
    <section className="page upload" aria-labelledby="up-title">
      <h1 id="up-title" className="page-title">
        Analyse a match
      </h1>
      <div className="upload-grid">
        <form onSubmit={submit} noValidate>
          <label
            className={`drop${file ? " has-file" : ""}${over ? " over" : ""}`}
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
              if (f && !uploading) setFile(f);
            }}
          >
            <input
              type="file"
              accept="video/*,.mp4,.mov,.mkv,.avi,.webm,.m4v"
              className="visually-hidden"
              disabled={uploading}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) setFile(f);
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
              {sent === null
                ? uploading
                  ? "Uploading…"
                  : "Start analysis"
                : `Uploading ${Math.round(sent * 100)}%`}
            </button>
            {uploading ? (
              <button
                type="button"
                className="link-quiet"
                onClick={() => upload.current?.abort()}
              >
                Cancel the upload
              </button>
            ) : null}
          </div>
          {uploading ? (
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
