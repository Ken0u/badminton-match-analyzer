import { ApiError, createApiClient, isCancellation } from "../../api/client.js";
import { createStore } from "../../state/store.js";
import {
  ExportPayloadError,
  parseExportJob,
  parseExportStatus,
  parseRecoveredExports,
} from "./model.js";
import type { ExportJob, ExportRequest, ExportStatus } from "./model.js";

export interface ExportSnapshot {
  readonly videoId: string | null;
  readonly jobs: readonly ExportStatus[];
  readonly loading: boolean;
  readonly starting: boolean;
  readonly message: string;
  readonly error: boolean;
}
const initial: ExportSnapshot = {
  videoId: null,
  jobs: [],
  loading: false,
  starting: false,
  message: "Choose a saved annotation revision to export native media.",
  error: false,
};
const active = (job: ExportJob) =>
  job.status === "queued" || job.status === "running";
const retryableListFailure = (error: unknown) =>
  error instanceof ApiError
    ? error.status >= 500 && error.status < 600
    : error instanceof TypeError ||
      (error instanceof DOMException && error.name === "NetworkError");
export const exportError = (error: unknown) => {
  if (error instanceof ApiError) {
    if (error.status === 401 || error.status === 403)
      return "Authentication is required to start or inspect media exports. Sign in, then refresh.";
    if (error.status === 409)
      return "The export is unavailable, its saved inputs changed, or shared admission is busy. Refresh or start a new export.";
    return error.message;
  }
  return error instanceof Error ? error.message : String(error);
};
export function createExportController({
  api = createApiClient(),
  pollMs = 3000,
}: { api?: ReturnType<typeof createApiClient>; pollMs?: number } = {}) {
  const store = createStore(initial);
  let generation = 0,
    intent = 0,
    readSequence = 0,
    starting = false,
    selection: string | null = null,
    timer: ReturnType<typeof setTimeout> | null = null,
    disposed = false;
  let recoveryReads = 0;
  let operationError: string | null = null;
  let listError: string | null = null;
  const clearTimer = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  const publish = (patch: Partial<ExportSnapshot>) => {
    if (!disposed) store.publish({ ...store.getSnapshot(), ...patch });
  };
  const owns = (videoId: string, ticket: number) =>
    !disposed && selection === videoId && generation === ticket;
  const errors = () => ({
    error: Boolean(operationError || listError),
    message: [operationError, listError].filter(Boolean).join(" "),
  });
  const schedule = (videoId: string, ticket: number) => {
    clearTimer();
    if (store.getSnapshot().jobs.some(active))
      timer = setTimeout(() => {
        if (owns(videoId, ticket)) void readJobs(false);
      }, pollMs);
  };
  const unavailable = (job: ExportJob, error: unknown): ExportStatus => ({
    ...job,
    available: false,
    unavailableReason: exportError(error),
  });
  const status = async (job: ExportJob) => {
    const request: ExportRequest = {
      videoId: job.videoId,
      revision: job.revision,
      mode: job.mode,
    };
    const raw = await api.request(
      "get",
      "/api/videos/{video_id}/media-exports/{job_id}",
      { path: { video_id: job.videoId, job_id: job.id } },
    );
    return parseExportStatus(raw, request, job.id);
  };
  async function readJobs(manual: boolean) {
    const videoId = selection;
    // A list captured before the POST settles can omit its durable new job.
    // A new selection still refreshes while the old selection's POST finishes.
    if (!videoId || disposed || store.getSnapshot().starting) return;
    if (manual) recoveryReads = 0;
    clearTimer();
    const ticket = generation;
    const readIntent = intent;
    const read = ++readSequence;
    publish({ loading: true });
    try {
      const raw = await api.request("get", "/api/jobs", {
        query: { video_id: videoId },
      });
      const jobs = parseRecoveredExports(raw, videoId);
      const results = await Promise.all(
        jobs.map(async (job) => {
          try {
            return await status(job);
          } catch (error) {
            return unavailable(job, error);
          }
        }),
      );
      if (
        !owns(videoId, ticket) ||
        readIntent !== intent ||
        read !== readSequence
      )
        return;
      recoveryReads = 0;
      listError = null;
      publish({
        jobs: results,
        message: operationError
          ? operationError
          : jobs.length
            ? "Media export jobs are bound to their saved source and revision."
            : "No media export jobs for this source.",
        error: Boolean(operationError),
      });
      schedule(videoId, ticket);
    } catch (error) {
      if (
        !owns(videoId, ticket) ||
        readIntent !== intent ||
        read !== readSequence
      )
        return;
      if (isCancellation(error)) {
        listError =
          "Export status refresh was cancelled. Refresh jobs to try again.";
        publish(errors());
      } else {
        const recoverable =
          retryableListFailure(error) && store.getSnapshot().jobs.some(active);
        const retry = recoverable && recoveryReads < 3;
        listError =
          exportError(error) +
          (recoverable
            ? retry
              ? " Export status will refresh automatically."
              : " Automatic status refresh stopped. Refresh jobs to try again."
            : " Refresh jobs to try again.");
        publish(errors());
        if (retry) {
          ++recoveryReads;
          schedule(videoId, ticket);
        }
      }
    } finally {
      if (
        owns(videoId, ticket) &&
        readIntent === intent &&
        read === readSequence
      )
        publish({ loading: false });
    }
  }
  async function start(
    request: ExportRequest,
    current: () => {
      videoId: string | null;
      revision: number | null;
      dirty: boolean;
      saving: boolean;
    },
  ) {
    if (starting) return;
    try {
      const now = current();
      if (now.videoId !== request.videoId || now.revision !== request.revision)
        throw new Error(
          "The selected source or saved revision changed. Review the export details and start again.",
        );
      if (now.dirty || now.saving)
        throw new Error("Save annotations before starting a media export.");
    } catch (error) {
      operationError = exportError(error);
      publish(errors());
      return;
    }
    starting = true;
    clearTimer();
    ++intent;
    recoveryReads = 0;
    operationError = null;
    listError = null;
    const ticket = generation;
    const read = ++readSequence;
    // This start now owns the view; the superseded read cannot release loading.
    publish({ starting: true, loading: false, error: false });
    try {
      const raw = await api.request(
        "post",
        "/api/videos/{video_id}/media-exports",
        {
          path: { video_id: request.videoId },
          json: { revision: request.revision, mode: request.mode },
        },
      );
      const job = parseExportJob(raw, request);
      if (!owns(request.videoId, ticket)) return;
      let result: ExportStatus;
      try {
        result = await status(job);
      } catch (error) {
        result = unavailable(job, error);
      }
      if (!owns(request.videoId, ticket) || read !== readSequence) return;
      const old = store
        .getSnapshot()
        .jobs.filter((known) => known.id !== job.id);
      publish({
        jobs: [result, ...old],
        message: `Started ${request.mode} from saved revision ${request.revision}.`,
        error: false,
      });
    } catch (error) {
      if (
        owns(request.videoId, ticket) &&
        (error instanceof ExportPayloadError || !isCancellation(error))
      ) {
        operationError = exportError(error);
        publish(errors());
      }
    } finally {
      starting = false;
      if (owns(request.videoId, ticket)) {
        publish({ starting: false });
        schedule(request.videoId, ticket);
      }
    }
  }
  return {
    subscribe: store.subscribe,
    getSnapshot: store.getSnapshot,
    select(videoId: string | null) {
      clearTimer();
      selection = videoId;
      ++generation;
      ++readSequence;
      recoveryReads = 0;
      operationError = null;
      listError = null;
      publish({
        videoId,
        jobs: [],
        loading: false,
        starting: false,
        message: videoId ? "Loading media export jobs…" : initial.message,
        error: false,
      });
      if (videoId) void readJobs(true);
    },
    refresh: () => readJobs(true),
    start,
    dispose() {
      disposed = true;
      clearTimer();
      ++generation;
    },
  };
}
