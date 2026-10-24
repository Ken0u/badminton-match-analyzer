import { createApiClient, isCancellation } from "../api/client.js";
import { createDraftStore } from "../state/draft.js";
import { createLatestTask, createSelectionScope } from "../state/selection.js";
import type { SelectionToken } from "../state/selection.js";
import { createStore } from "../state/store.js";
import {
  activeJob,
  errorMessage,
  parseAnalysis,
  parseJob,
  parseJobs,
  parsePlayback,
  parseVideo,
  parseVideos,
  validateYoutube,
} from "./model.js";
import type {
  Analysis,
  AnalysisSettings,
  Job,
  Playback,
  Video,
} from "./model.js";
import { uploadVideo } from "./upload.js";
import type { Upload, UploadProgress } from "./upload.js";

/** Shared with the future editor: navigation checks the live draft before selecting. */
export function createLibrarySession<T>() {
  const selection = createSelectionScope();
  const drafts = createDraftStore<T>(selection);
  return { selection, drafts, canLeave: drafts.canLeave };
}
export interface LibraryState {
  videos: Video[];
  jobs: Job[];
  selectedId: string | null;
  video: Video | null;
  playback: Playback | null;
  analysis: Analysis | null;
  libraryLoading: boolean;
  selectedLoading: boolean;
  importing: boolean;
  transfer: UploadProgress | null;
  action: string | null;
  notice: string;
  errors: Readonly<Record<string, string>>;
}
export function createLibraryController({
  api = createApiClient(),
  upload = uploadVideo,
  session = createLibrarySession<unknown>(),
  pollMs = 1500,
}: {
  api?: ReturnType<typeof createApiClient>;
  upload?: Upload;
  session?: Pick<
    ReturnType<typeof createLibrarySession<unknown>>,
    "selection" | "canLeave"
  >;
  pollMs?: number;
} = {}) {
  const store = createStore<LibraryState>({
    videos: [],
    jobs: [],
    selectedId: null,
    video: null,
    playback: null,
    analysis: null,
    libraryLoading: true,
    selectedLoading: false,
    importing: false,
    transfer: null,
    action: null,
    notice: "",
    errors: {},
  });
  const patch = (update: Partial<LibraryState>) => {
    if (!disposed) store.publish({ ...store.getSnapshot(), ...update });
  };
  const error = (key: string, value: unknown | null) => {
    const errors = { ...store.getSnapshot().errors };
    if (value === null) delete errors[key];
    else errors[key] = errorMessage(value);
    patch({ errors });
  };
  const globalScope = createSelectionScope(),
    globalOwner = globalScope.select("library");
  const libraryLane = createLatestTask(globalScope),
    jobsLane = createLatestTask(globalScope);
  const metadataLane = createLatestTask(session.selection),
    proxyLane = createLatestTask(session.selection),
    analysisLane = createLatestTask(session.selection);
  let disposed = false,
    started = false,
    timer: ReturnType<typeof setTimeout> | null = null;
  let importAbort: AbortController | null = null,
    importEpoch = 0;
  let importFingerprint = "";
  const importJobsFingerprint = () =>
    store
      .getSnapshot()
      .jobs.filter((j) => j.kind === "import")
      .map((j) => `${j.id}:${j.status}`)
      .join("|");
  const current = (owner: SelectionToken) =>
    !disposed && session.selection.isCurrent(owner);
  async function refreshLibrary() {
    const fingerprint = importJobsFingerprint();
    patch({ libraryLoading: true });
    try {
      await libraryLane.run(
        globalOwner,
        async (signal) =>
          parseVideos(await api.request("get", "/api/videos", { signal })),
        (videos) => {
          // Only this current read can acknowledge the imports it started after.
          importFingerprint = fingerprint;
          patch({ videos, libraryLoading: false });
          error("library", null);
        },
      );
    } catch (e) {
      error("library", e);
      patch({ libraryLoading: false });
    }
  }
  async function refreshPlayback(owner = session.selection.current()) {
    if (!owner) return;
    try {
      await proxyLane.run(
        owner,
        async (signal) =>
          parsePlayback(
            await api.request("get", "/api/videos/{video_id}/playback", {
              path: { video_id: owner.id },
              signal,
            }),
            owner.id,
          ),
        (playback) => {
          patch({ playback });
          error("playback", null);
        },
      );
    } catch (e) {
      if (current(owner)) error("playback", e);
    }
  }
  async function refreshAnalysis(owner: SelectionToken, job: Job) {
    try {
      await analysisLane.run(
        owner,
        async (signal) =>
          parseAnalysis(
            await api.request(
              "get",
              "/api/videos/{video_id}/analysis/{job_id}",
              { path: { video_id: owner.id, job_id: job.id }, signal },
            ),
            owner.id,
            job.id,
          ),
        (analysis) => {
          patch({ analysis });
          error("analysis", null);
        },
      );
    } catch (e) {
      if (current(owner)) error("analysis", e);
    }
  }
  async function refreshJobs() {
    try {
      await jobsLane.run(
        globalOwner,
        async (signal) =>
          parseJobs(await api.request("get", "/api/jobs", { signal })),
        (jobs) => {
          patch({ jobs });
          error("jobs", null);
        },
      );
      if (disposed) return;
      const owner = session.selection.current(),
        jobs = store.getSnapshot().jobs;
      if (owner) {
        const analysis = jobs.find(
          (j) => j.video_id === owner.id && j.kind === "analysis",
        );
        if (analysis) await refreshAnalysis(owner, analysis);
        await refreshPlayback(owner);
      }
      // Refresh after imports without selecting a new video or touching any draft.
      if (importJobsFingerprint() !== importFingerprint) {
        await refreshLibrary();
      }
    } catch (e) {
      error("jobs", e);
    }
  }
  async function select(id: string) {
    if (!session.canLeave()) {
      patch({
        notice:
          "Save or explicitly discard your unsaved draft before selecting another video. Saving must finish first.",
      });
      return false;
    }
    const owner = session.selection.select(id);
    metadataLane.cancel();
    proxyLane.cancel();
    analysisLane.cancel();
    patch({
      selectedId: id,
      video: null,
      playback: null,
      analysis: null,
      selectedLoading: true,
      action: null,
      notice: "",
      errors: Object.fromEntries(
        Object.entries(store.getSnapshot().errors).filter(([key]) =>
          ["library", "jobs", "import"].includes(key),
        ),
      ),
    });
    void refreshPlayback(owner);
    const job = store
      .getSnapshot()
      .jobs.find((j) => j.video_id === id && j.kind === "analysis");
    if (job) void refreshAnalysis(owner, job);
    try {
      await metadataLane.run(
        owner,
        async (signal) => {
          const video = parseVideo(
            await api.request("get", "/api/videos/{video_id}", {
              path: { video_id: id },
              signal,
            }),
          );
          if (video.id !== id)
            throw new Error("Video response belongs to another selection.");
          return video;
        },
        (video) => {
          patch({ video, selectedLoading: false });
          error("video", null);
        },
      );
    } catch (e) {
      if (current(owner)) {
        error("video", e);
        patch({ selectedLoading: false });
      }
    }
    return true;
  }
  async function importMedia(
    task: (
      signal: AbortSignal,
      progress: (p: UploadProgress) => void,
    ) => Promise<unknown>,
  ) {
    if (store.getSnapshot().importing || disposed) return;
    const controller = new AbortController(),
      epoch = ++importEpoch;
    importAbort = controller;
    patch({ importing: true, transfer: null, notice: "Submitting import…" });
    error("import", null);
    try {
      const job = parseJob(
        await task(controller.signal, (p) => {
          if (epoch === importEpoch && !controller.signal.aborted)
            patch({ transfer: p });
        }),
      );
      if (controller.signal.aborted || disposed || epoch !== importEpoch)
        return;
      if (job.kind !== "import")
        throw new Error("Unexpected import job response.");
      patch({
        notice:
          "Import queued. Follow its status in Import jobs; choose the video when it is ready.",
      });
      await refreshJobs();
      await refreshLibrary();
    } catch (e) {
      if (!disposed && epoch === importEpoch) {
        if (isCancellation(e))
          patch({
            notice:
              "Transfer cancelled locally. The server may already have received it; reload jobs before retrying.",
          });
        else error("import", e);
      }
    } finally {
      if (epoch === importEpoch) {
        importAbort = null;
        patch({ importing: false });
      }
    }
  }
  async function action(
    kind: "processing" | "pause" | "playback",
    settings?: AnalysisSettings,
  ) {
    const owner = session.selection.current();
    if (
      !owner ||
      !store.getSnapshot().video ||
      store.getSnapshot().action ||
      disposed
    )
      return;
    patch({ action: kind });
    error("action", null);
    try {
      let result: unknown;
      if (kind === "processing")
        result = await api.request("post", "/api/videos/{video_id}/analysis", {
          path: { video_id: owner.id },
          json: settings ?? {
            player_model: "small",
            auto_calibrate: true,
            recognize: true,
          },
        });
      else if (kind === "playback")
        result = await api.request("post", "/api/videos/{video_id}/playback", {
          path: { video_id: owner.id },
        });
      else {
        const job = store
          .getSnapshot()
          .jobs.find(
            (j) =>
              j.video_id === owner.id && j.kind === "analysis" && activeJob(j),
          );
        if (!job) throw new Error("No active processing job for this video.");
        result = await api.request(
          "post",
          "/api/videos/{video_id}/analysis/{job_id}/pause",
          { path: { video_id: owner.id, job_id: job.id } },
        );
      }
      const job = parseJob(result);
      if (
        job.video_id !== owner.id ||
        job.kind !== (kind === "playback" ? "playback" : "analysis")
      )
        throw new Error("Job response belongs to another video or operation.");
      if (current(owner))
        patch({
          notice:
            kind === "pause"
              ? "Pause requested. Processing stops at a safe checkpoint; wait for the final job status."
              : `${kind === "playback" ? "Playback preparation" : "Processing"} queued.`,
        });
      await refreshJobs();
    } catch (e) {
      if (current(owner)) error("action", e);
    } finally {
      if (current(owner)) patch({ action: null });
    }
  }
  return {
    getSnapshot: store.getSnapshot,
    subscribe: store.subscribe,
    select,
    refreshLibrary,
    refreshJobs,
    refreshPlayback,
    start() {
      if (started || disposed) return;
      started = true;
      void refreshLibrary();
      const poll = async () => {
        await refreshJobs();
        if (!disposed)
          timer = setTimeout(() => {
            void poll();
          }, pollMs);
      };
      void poll();
    },
    upload(file: File, mode: "singles" | "doubles") {
      return importMedia((signal, progress) => {
        if (!file.size || !/\.(mp4|mov|mkv|avi|webm)$/i.test(file.name))
          throw new Error(
            "Choose a nonempty MP4, MOV, MKV, AVI or WebM video.",
          );
        return upload(file, mode, signal, progress);
      });
    },
    youtube(url: string, mode: "singles" | "doubles") {
      return importMedia((signal) =>
        api.request("post", "/api/import/youtube", {
          json: { url: validateYoutube(url), mode },
          signal,
        }),
      );
    },
    cancelUpload() {
      if (importAbort) {
        importAbort.abort();
        patch({
          notice:
            "Transfer cancelled locally. The server may already have received it; reload jobs before retrying.",
        });
      }
    },
    process: (settings: AnalysisSettings) => action("processing", settings),
    pause: () => action("pause"),
    preparePlayback: () => action("playback"),
    mediaFailed(id: string) {
      if (id !== store.getSnapshot().selectedId) return;
      error(
        "media",
        new Error(
          "Video playback could not load. Prepare playback or retry the compatible copy. Exact-frame review remains available in the review editor.",
        ),
      );
    },
    mediaReady(id: string) {
      if (id === store.getSnapshot().selectedId) error("media", null);
    },
    dispose() {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
      importAbort?.abort();
      globalScope.clear();
      session.selection.clear();
      for (const lane of [
        libraryLane,
        jobsLane,
        metadataLane,
        proxyLane,
        analysisLane,
      ])
        lane.cancel();
    },
  };
}
