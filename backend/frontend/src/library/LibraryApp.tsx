import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Button, ErrorFeedback, Feedback, Field } from "../ui/controls.js";
import { createLibraryController } from "./controller.js";
import { activeJob } from "./model.js";
import type { Job } from "./model.js";

function Jobs({ jobs, label }: { jobs: Job[]; label: string }) {
  return (
    <div
      data-testid={label === "Import jobs" ? "import-jobs" : "selected-jobs"}
    >
      <h3>{label}</h3>
      {!jobs.length ? (
        <p>No jobs yet.</p>
      ) : (
        <ul className="job-list">
          {jobs.map((job) => (
            <li key={job.id}>
              <strong>
                {job.kind} · {job.status}
              </strong>
              {job.cancel_requested && activeJob(job)
                ? " · Pause requested"
                : ""}
              <progress
                aria-label={`${job.kind} ${job.id} progress`}
                value={job.progress}
                max={1}
              />
              <span>
                {Math.round(job.progress * 100)}% ·{" "}
                {job.message || "No server message"}
              </span>
              <small>Job {job.id}</small>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
export function LibraryApp() {
  const [controller] = useState(() => createLibraryController());
  const state = useSyncExternalStore(
    controller.subscribe,
    controller.getSnapshot,
  );
  const [mode, setMode] = useState<"singles" | "doubles">("singles");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [model, setModel] = useState<"small" | "nano">("small");
  const [calibrate, setCalibrate] = useState(true),
    [recognize, setRecognize] = useState(true);
  const [mediaAttempt, setMediaAttempt] = useState(0);
  const importSource = useRef<"file" | "youtube">("file");
  const selectedHeading = useRef<HTMLHeadingElement>(null);
  const youtubeInput = useRef<HTMLInputElement>(null),
    uploadInput = useRef<HTMLInputElement>(null),
    libraryButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    controller.start();
    return () => controller.dispose();
  }, [controller]);
  const selectedJobs = state.jobs.filter(
    (j) => j.video_id === state.selectedId,
  );
  const processing = selectedJobs.find((j) => j.kind === "analysis");
  const running = selectedJobs.some(
    (j) => j.kind === "analysis" && activeJob(j),
  );
  const proxyRunning = selectedJobs.some(
    (j) => j.kind === "playback" && activeJob(j),
  );
  const imports = state.jobs.filter((j) => j.kind === "import");
  const mediaUrl = state.video
    ? (state.playback?.url ??
      `/api/videos/${encodeURIComponent(state.video.id)}/media`)
    : null;
  const transfer = state.transfer;
  const settings = {
    player_model: model,
    auto_calibrate: calibrate,
    recognize,
  };
  return (
    <main>
      <header>
        <p className="eyebrow">Badminton match analyzer</p>
        <h1>Match library</h1>
        <p>Import videos and monitor full-match processing.</p>
        <p className="boundary">
          Automatic annotation accuracy is not established. Processing coverage
          and completed jobs do not prove correct labels. Review every
          annotation in the editor.
        </p>
        <nav aria-label="Application">
          <a
            href={`/editor${state.selectedId ? `?video=${encodeURIComponent(state.selectedId)}` : ""}`}
          >
            Open review editor
          </a>{" "}
          · <a href="/library">Match library</a>
        </nav>
      </header>
      <section aria-labelledby="import-heading">
        <h2 id="import-heading">Import a match</h2>
        <p>
          Choose a local video or a public HTTPS YouTube video. Imports finish
          in the background and do not change your selected video.
        </p>
        <div className="field">
          <label htmlFor="match-mode">Match mode</label>
          <select
            id="match-mode"
            value={mode}
            disabled={state.importing}
            onChange={(e) =>
              setMode(e.target.value === "doubles" ? "doubles" : "singles")
            }
          >
            <option value="singles">Singles</option>
            <option value="doubles">Doubles</option>
          </select>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (file) {
              importSource.current = "file";
              void controller.upload(file, mode);
            }
          }}
        >
          <Field
            ref={uploadInput}
            type="file"
            label="Video file"
            accept=".mp4,.mov,.mkv,.avi,.webm"
            disabled={state.importing}
            help="MP4, MOV, MKV, AVI or WebM. Server size and media validation still apply."
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <Button type="submit" disabled={!file || state.importing}>
            Upload video
          </Button>
        </form>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            importSource.current = "youtube";
            void controller.youtube(url, mode);
          }}
        >
          <Field
            ref={youtubeInput}
            label="Public YouTube URL"
            type="url"
            value={url}
            disabled={state.importing}
            help="Single public video only; playlists and radio links are rejected."
            onChange={(e) => setUrl(e.target.value)}
          />
          <Button type="submit" disabled={!url || state.importing}>
            Import YouTube
          </Button>
        </form>
        {state.importing && (
          <div role="status">
            <p>Submitting import…</p>
            <>
              <progress
                aria-label="Upload transfer progress"
                {...(transfer?.total
                  ? { value: transfer.loaded, max: transfer.total }
                  : {})}
              />
              <p>
                {transfer ? (
                  <>
                    {transfer.loaded.toLocaleString()} bytes transferred
                    {transfer.total
                      ? ` of ${transfer.total.toLocaleString()}`
                      : " (total unavailable)"}
                    . Transfer completion is followed by server import
                    processing.
                  </>
                ) : (
                  "Waiting for transfer byte counts…"
                )}
              </p>
            </>
            <Button onClick={() => controller.cancelUpload()}>
              Cancel transfer
            </Button>
          </div>
        )}
        {state.errors.import && (
          <ErrorFeedback
            retry={() => {
              (importSource.current === "file"
                ? uploadInput
                : youtubeInput
              ).current?.focus();
            }}
          >
            {state.errors.import}
          </ErrorFeedback>
        )}
        <Jobs label="Import jobs" jobs={imports} />
      </section>
      <section aria-labelledby="library-heading" data-testid="library">
        <h2 id="library-heading">Videos</h2>
        <Button
          ref={libraryButton}
          onClick={() => {
            void controller
              .refreshLibrary()
              .then(() => libraryButton.current?.focus());
          }}
          busy={state.libraryLoading}
        >
          Refresh library
        </Button>
        {state.errors.library && (
          <ErrorFeedback
            retry={() => {
              void controller
                .refreshLibrary()
                .then(() => libraryButton.current?.focus());
            }}
          >
            {state.errors.library}
          </ErrorFeedback>
        )}
        {!state.libraryLoading &&
          !state.errors.library &&
          !state.videos.length && (
            <p>
              No videos yet. Upload a video or import a public YouTube match to
              begin.
            </p>
          )}
        <ul className="video-list">
          {state.videos.map((v) => (
            <li key={v.id}>
              <Button
                aria-label={`Select ${v.name}`}
                aria-pressed={state.selectedId === v.id}
                onClick={() => {
                  void controller.select(v.id);
                }}
              >
                <strong>{v.name}</strong>
                <small>
                  {v.mode} · {v.duration_s.toFixed(1)} seconds
                </small>
              </Button>
            </li>
          ))}
        </ul>
      </section>
      <Feedback>{state.notice}</Feedback>
      <section aria-labelledby="selected-heading" data-testid="selected-video">
        <h2 id="selected-heading" ref={selectedHeading} tabIndex={-1}>
          {state.video?.name ??
            (state.selectedLoading
              ? "Loading selected video…"
              : "Selected video")}
        </h2>
        <p>
          Selected video:{" "}
          <strong data-testid="selected-video-id">
            {state.selectedId ?? "none"}
          </strong>
        </p>
        {!state.selectedId && <p>Select a video from the library.</p>}
        {state.errors.video && (
          <ErrorFeedback
            retry={() => {
              if (state.selectedId)
                void controller
                  .select(state.selectedId)
                  .then(() => selectedHeading.current?.focus());
            }}
          >
            {state.errors.video}
          </ErrorFeedback>
        )}
        {state.video && (
          <>
            <p>
              {state.video.mode} · {state.video.frame_count.toLocaleString()}{" "}
              native source frames. Preview playback does not supply exact
              source-frame mapping.
            </p>
            <video
              key={`${state.video.id}:${mediaUrl}:${mediaAttempt}`}
              controls
              preload="metadata"
              aria-label={`Playback for ${state.video.name}`}
              src={mediaUrl ?? undefined}
              onError={() => controller.mediaFailed(state.video!.id)}
              onCanPlay={() => controller.mediaReady(state.video!.id)}
            />
            <p data-testid="playback-status">
              {proxyRunning
                ? "Preparing compatible playback…"
                : state.playback?.status === "ready"
                  ? "Compatible playback ready"
                  : "Compatible playback not prepared"}
            </p>
            {state.errors.media && (
              <ErrorFeedback>{state.errors.media}</ErrorFeedback>
            )}
            {state.errors.playback && (
              <ErrorFeedback
                retry={() => {
                  void controller.refreshPlayback();
                }}
              >
                {state.errors.playback}
              </ErrorFeedback>
            )}
            <div className="actions">
              <Button
                disabled={proxyRunning || Boolean(state.action)}
                onClick={() => {
                  void controller.preparePlayback();
                }}
              >
                Prepare playback
              </Button>
              <Button
                onClick={() => {
                  setMediaAttempt((n) => n + 1);
                  void controller.refreshPlayback();
                }}
              >
                Retry playback
              </Button>
            </div>
            <h3>Full-match processing</h3>
            <p>
              Pause requests stop cooperatively at a safe checkpoint. Resume
              starts a new job using cached completed work when it is still
              valid; previous jobs remain in history.
            </p>
            <div className="field">
              <label htmlFor="player-model">Player model</label>
              <select
                id="player-model"
                value={model}
                onChange={(e) =>
                  setModel(e.target.value === "nano" ? "nano" : "small")
                }
                disabled={running || Boolean(state.action)}
              >
                <option value="small">Small</option>
                <option value="nano">Nano</option>
              </select>
            </div>
            <label className="check">
              <input
                type="checkbox"
                checked={calibrate}
                disabled={running || Boolean(state.action)}
                onChange={(e) => setCalibrate(e.target.checked)}
              />{" "}
              Automatically calibrate court
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={recognize}
                disabled={running || Boolean(state.action)}
                onChange={(e) => setRecognize(e.target.checked)}
              />{" "}
              Recognize stroke proposals
            </label>
            <div className="actions">
              <Button
                disabled={running || Boolean(state.action)}
                onClick={() => {
                  void controller.process(settings);
                }}
              >
                Start processing
              </Button>
              <Button
                disabled={
                  !running ||
                  Boolean(state.action) ||
                  processing?.cancel_requested
                }
                onClick={() => {
                  void controller.pause();
                }}
              >
                Pause processing
              </Button>
              <Button
                disabled={
                  running ||
                  Boolean(state.action) ||
                  !processing?.settings ||
                  !["cancelled", "failed", "interrupted"].includes(
                    processing.status,
                  )
                }
                onClick={() => {
                  if (processing?.settings)
                    void controller.process(processing.settings);
                }}
              >
                Resume processing
              </Button>
            </div>
            {processing && !processing.settings && !activeJob(processing) && (
              <p>
                Previous settings are unavailable; choose settings and start
                processing.
              </p>
            )}
            {state.analysis && (
              <p data-testid="analysis-state">
                Processing state: {state.analysis.state}
                {state.analysis.requiresProcessingRerun
                  ? ". Source context changed; processing must run again."
                  : ""}
              </p>
            )}
            <Jobs label="Jobs for selected video" jobs={selectedJobs} />
          </>
        )}
        {state.errors.action && (
          <ErrorFeedback>{state.errors.action}</ErrorFeedback>
        )}
        {state.errors.analysis && (
          <ErrorFeedback
            retry={() => {
              void controller.refreshJobs();
            }}
          >
            {state.errors.analysis}
          </ErrorFeedback>
        )}
      </section>
      {state.errors.jobs && (
        <ErrorFeedback
          retry={() => {
            void controller.refreshJobs();
          }}
        >
          {state.errors.jobs}
        </ErrorFeedback>
      )}
    </main>
  );
}
