import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { createExportController } from "./controller.js";
import { exportModes } from "./model.js";
import type { ExportMode } from "./model.js";

export function ExportPanel({
  videoId,
  revision,
  dirty,
  saving,
}: {
  videoId: string;
  revision: number;
  dirty: boolean;
  saving: boolean;
}) {
  const [controller] = useState(createExportController);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot);
  const [mode, setMode] = useState<ExportMode>("plain-rallies");
  const latest = useRef({ videoId, revision, dirty, saving });
  latest.current = { videoId, revision, dirty, saving };
  useEffect(() => {
    controller.select(videoId);
  }, [controller, videoId]);
  useEffect(() => () => controller.dispose(), [controller]);
  const disabled = dirty || saving;
  return (
    <section className="media-export-panel" aria-labelledby="media-export-heading">
      <h2 id="media-export-heading">EXPORT REVIEWED MEDIA</h2>
      <p>
        Source <code>{videoId}</code> · saved revision <strong>{revision}</strong> · mode{" "}
        <strong>{mode}</strong>
      </p>
      <label htmlFor="media-export-mode">
        Native media export mode
        <select
          id="media-export-mode"
          value={mode}
          onChange={(event) => setMode(event.target.value as ExportMode)}
        >
          {exportModes.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <div className="row">
        <button
          id="media-export-start"
          type="button"
          disabled={disabled}
          onClick={() => void controller.start(
            { videoId, revision, mode },
            () => latest.current,
          )}
        >
          Start media export
        </button>
        <button id="media-export-refresh" type="button" onClick={() => void controller.refresh()} disabled={state.loading}>
          Refresh jobs
        </button>
      </div>
      {disabled && <small>Save annotations before starting an export. The editor will not save or export automatically.</small>}
      <p id="media-export-status" role={state.error ? "alert" : "status"} aria-live="polite">
        {state.message}
      </p>
      {state.jobs.map((job) => (
        <article key={job.id} data-export-job={job.id} className="media-export-job">
          <strong>{job.mode}</strong> · revision {job.revision} · {job.status}
          {job.message && <span> · {job.message}</span>}
          {job.status === "queued" || job.status === "running" ? <span> · {Math.round(job.progress * 100)}%</span> : null}
          {job.available ? (
            <>
              <p>
                {job.counts.eligible} eligible / {job.counts.ineligible} ineligible / {job.counts.total} total rallies.
                {job.mode === "annotated-full" ? " The full source video remains one export even when rallies are ineligible." : ""}
              </p>
              {job.reasons.length > 0 && <p>Ineligible reasons: {job.reasons.join(", ")}.</p>}
              <p>Saved reviewed overlays preserve reviewed and predicted annotation provenance; they do not establish annotation accuracy.</p>
              <ul>
                {job.files.map((file) => (
                  <li key={file.filename}>
                    <a data-export-file={file.filename} href={file.href} download>{file.filename}</a>
                    {" "}({file.mediaType}, {file.sizeBytes} bytes, SHA-256 {file.sha256})
                  </li>
                ))}
              </ul>
            </>
          ) : job.status === "failed" || job.status === "interrupted" ? (
            <p>Export did not complete. Review the message, then explicitly start a new export when ready.</p>
          ) : job.status === "completed" ? (
            <p>Completed export artifacts are unavailable or changed. Refresh or explicitly start a new export.</p>
          ) : job.status === "queued" || job.status === "running" ? (
            <p>Media export is admitted through the shared worker. Refresh its status; it will not retry mutations automatically.</p>
          ) : <p>This export has an unknown status and cannot be acted on. Refresh after the server is updated.</p>}
        </article>
      ))}
    </section>
  );
}
