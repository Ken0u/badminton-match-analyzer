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
  const clearTimer = () => {
    if (timer) clearTimeout(timer);
    timer = null;
  };
  const publish = (patch: Partial<ExportSnapshot>) => {
    if (!disposed) store.publish({ ...store.getSnapshot(), ...patch });
  };
  const owns = (videoId: string, ticket: number) =>
    !disposed && selection === videoId && generation === ticket;
  const schedule = (videoId: string, ticket: number) => {
    clearTimer();
    if (store.getSnapshot().jobs.some(active))
      timer = setTimeout(() => {
        if (owns(videoId, ticket)) void refresh();
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
  async function refresh() {
    const videoId = selection;
    if (!videoId || disposed) return;
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
      const previous = store.getSnapshot();
      publish({
        jobs: results,
        loading: false,
        message: previous.error
          ? previous.message
          : jobs.length
            ? "Media export jobs are bound to their saved source and revision."
            : "No media export jobs for this source.",
        error: previous.error,
      });
      schedule(videoId, ticket);
    } catch (error) {
      if (
        !owns(videoId, ticket) ||
        readIntent !== intent ||
        read !== readSequence ||
        isCancellation(error)
      )
        return;
      publish({ loading: false, error: true, message: exportError(error) });
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
      publish({ error: true, message: exportError(error) });
      return;
    }
    starting = true;
    ++intent;
    const ticket = generation;
    const read = ++readSequence;
    publish({ starting: true, error: false });
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
      schedule(request.videoId, ticket);
    } catch (error) {
      if (
        owns(request.videoId, ticket) &&
        (error instanceof ExportPayloadError || !isCancellation(error))
      )
        publish({ error: true, message: exportError(error) });
    } finally {
      starting = false;
      if (owns(request.videoId, ticket)) publish({ starting: false });
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
      publish({
        videoId,
        jobs: [],
        loading: false,
        starting: false,
        message: videoId ? "Loading media export jobs…" : initial.message,
        error: false,
      });
      if (videoId) void refresh();
    },
    refresh,
    start,
    dispose() {
      disposed = true;
      clearTimer();
      ++generation;
    },
  };
}
