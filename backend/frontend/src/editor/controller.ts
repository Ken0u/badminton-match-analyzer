import { createApiClient, isCancellation } from "../api/client.js";
import { parsePlayback, parseAnalysis } from "../library/model.js";
import { createDraftStore } from "../state/draft.js";
import { createSelectionScope, createLatestTask } from "../state/selection.js";
import { createStore } from "../state/store.js";
import { createPlaybackStore } from "../state/playback.js";
import {
  parseDocument,
  parseVideo,
  parseTimes,
  parseJobs,
  parseRun,
  object,
  objects,
  num,
  str,
  contextSignature,
} from "./model.js";
import type { Document, Video, Job, Run, ObjectData, Schema } from "./model.js";
export type Stage =
  "players" | "shuttle" | "contacts" | "recognition" | "rallies" | "segments";
export interface LoadedRun {
  id: string;
  run: Run;
}
export interface EditorSnapshot {
  videos: Video[];
  video: Video | null;
  times: number[];
  jobs: Job[];
  runs: Partial<Record<Stage, LoadedRun>>;
  plan: ObjectData | null;
  actors: ObjectData[];
  analysisEnabled: boolean;
  partIndex: number | null;
  playbackUrl: string | null;
  playbackBusy: boolean;
  loading: boolean;
  notice: string;
  error: boolean;
  report: ObjectData | null;
}
const initial: EditorSnapshot = {
  videos: [],
  video: null,
  times: [],
  jobs: [],
  runs: {},
  plan: null,
  actors: [],
  analysisEnabled: false,
  partIndex: null,
  playbackUrl: null,
  playbackBusy: false,
  loading: false,
  notice: "Choose a video from the library.",
  error: false,
  report: null,
};
export function createEditorController() {
  const api = createApiClient(),
    scope = createSelectionScope(),
    drafts = createDraftStore<Document>(scope),
    store = createStore(initial),
    playback = createPlaybackStore();
  const load = createLatestTask(scope),
    resource = createLatestTask(scope),
    evaluation = createLatestTask(scope);
  let disposed = false,
    polling = false,
    pollAgain = false,
    pollingView = 0,
    activePoll = 0,
    selectionBusy = false;
  let edits = 0,
    librarySequence = 0,
    viewVersion = 0,
    evaluationVersion = 0;
  let automaticAnalysis = true;
  const evaluatedStages = [
    "contacts",
    "shuttle",
    "recognition",
    "rallies",
  ] as const;
  function evaluationInputs(state: EditorSnapshot) {
    return JSON.stringify([
      state.video?.id ?? null,
      state.analysisEnabled,
      state.partIndex,
      ...evaluatedStages.map((stage) => state.runs[stage]?.id ?? null),
    ]);
  }
  function cancelEvaluation() {
    ++evaluationVersion;
    evaluation.cancel();
  }
  function invalidateEvaluation() {
    cancelEvaluation();
    publish({ report: null });
  }
  // A review view owns its async reads independently of the selected video.
  // Ordinary frame ticks do not invalidate reads; only window/mode changes do.
  function invalidateView() {
    ++viewVersion;
    resource.cancel();
    invalidateEvaluation();
  }
  const snapshot = store.getSnapshot;
  function publish(patch: Partial<EditorSnapshot>) {
    if (disposed) return;
    const previous = snapshot();
    const next = { ...previous, ...patch };
    if (evaluationInputs(previous) !== evaluationInputs(next)) {
      // Every accepted transition fences even A -> B -> A input replacement.
      // Polling with identical evaluated inputs keeps a completed report valid.
      cancelEvaluation();
      next.report = null;
    }
    if (JSON.stringify(previous) !== JSON.stringify(next)) store.publish(next);
  }
  let previousDraft = drafts.getSnapshot();
  drafts.subscribe(() => {
    const next = drafts.getSnapshot();
    const changed =
      previousDraft?.owner !== next?.owner ||
      previousDraft?.revision !== next?.revision ||
      previousDraft?.value !== next?.value;
    previousDraft = next;
    if (changed) invalidateEvaluation();
  });
  function notice(message: string, error = false) {
    publish({ notice: message, error });
  }
  function handle(error: unknown) {
    if (!isCancellation(error) && !disposed)
      notice(error instanceof Error ? error.message : String(error), true);
  }
  function edit(update: (d: Document) => Document) {
    if (drafts.edit(update)) {
      edits++;
      publish({ report: null });
    }
  }
  async function library() {
    const sequence = ++librarySequence;
    const raw = await api.request("get", "/api/videos", {});
    if (!Array.isArray(raw)) throw Error("Invalid video library");
    const videos = raw.map(parseVideo);
    if (!disposed && sequence === librarySequence) publish({ videos });
  }
  async function select(id: string) {
    if (selectionBusy) return;
    if (drafts.getSnapshot()?.saving) {
      notice("Saving annotations. Switch videos after the save finishes.");
      return;
    }
    if (drafts.getSnapshot()?.dirty) {
      if (!window.confirm("Discard unsaved edits and open another video?"))
        return;
      drafts.discard();
    }
    invalidateView();
    automaticAnalysis = true;
    const owner = scope.select(id);
    publish({
      loading: true,
      video: null,
      runs: {},
      plan: null,
      actors: [],
      report: null,
      analysisEnabled: false,
      partIndex: null,
      playbackUrl: null,
      playbackBusy: false,
    });
    playback.update({
      mediaTime: 0,
      playing: false,
      sourceFrame: null,
      sourceTime: null,
    });
    try {
      await load.run(
        owner,
        async (signal) => {
          const [v, d, t] = await Promise.all([
            api.request("get", "/api/videos/{video_id}", {
              path: { video_id: id },
              signal,
            }),
            api.request("get", "/api/videos/{video_id}/annotations", {
              path: { video_id: id },
              signal,
            }),
            api.request("get", "/api/videos/{video_id}/timestamps", {
              path: { video_id: id },
              signal,
            }),
          ]);
          const video = parseVideo(v);
          const doc = parseDocument(d);
          if (video.id !== id || doc.mode !== video.mode)
            throw Error(
              "Selected source identity does not match the annotation response.",
            );
          return {
            video,
            doc,
            times: parseTimes(t, video.frame_count),
          };
        },
        (result) => {
          drafts.open(owner, result.doc, result.doc.revision);
          publish({
            video: result.video,
            times: result.times,
            loading: false,
            notice:
              "Mark events at the current frame. Save edits before exporting or running tracking.",
            error: false,
          });
        },
      );
      if (scope.isCurrent(owner)) {
        await library();
        await refresh();
      }
    } catch (e) {
      if (scope.isCurrent(owner)) {
        publish({ loading: false });
        handle(e);
      }
    }
  }
  function planStale(plan = snapshot().plan) {
    const d = drafts.getSnapshot()?.value,
      v = snapshot().video;
    if (!d || !v || !plan?.recipe) return false;
    const recipe = object(plan.recipe);
    return (
      Boolean(plan.requires_processing_rerun) ||
      JSON.stringify(contextSignature(d, 0, v.frame_count)) !==
        JSON.stringify(recipe.context_signature)
    );
  }
  function currentPart() {
    const s = snapshot();
    if (!s.analysisEnabled || !s.plan) return null;
    return (
      objects(s.plan.parts).find(
        (p) => num(object(p.window).index) === s.partIndex,
      ) ?? null
    );
  }
  function stageMatches(j: Job) {
    const s = snapshot();
    if (s.analysisEnabled) {
      const part = currentPart();
      const stages = part ? object(part.stages) : {};
      return j.id === object(stages[j.kind] ?? {}).run_id;
    }
    return !j.analysis_key;
  }
  function latestCore(plan: ObjectData) {
    const frame =
      playback.getSnapshot().sourceFrame ??
      snapshot().video?.review_start_frame ??
      0;
    const part = objects(plan.parts).find((p) => {
      const window = object(p.window);
      return (
        num(window.core_start_frame) <= frame &&
        frame < num(window.core_end_frame)
      );
    });
    return part ? num(object(part.window).index) : null;
  }
  // The first plan is not yet available to setFrame while its runs load.
  // Reconcile that pending view before exposing any frame-scoped results.
  function reconcileInitialCore(
    plan: ObjectData | null,
    enabled: boolean,
    index: number | null,
  ) {
    if (!plan || !enabled || planStale(plan)) return false;
    const current = latestCore(plan);
    if (current === index) return false;
    invalidateView();
    publish({
      plan,
      analysisEnabled: true,
      partIndex: current,
      runs: {},
      actors: [],
    });
    void refresh();
    return true;
  }
  function setFrame(frame: number) {
    const s = snapshot();
    if (!s.video) return;
    const f = Math.max(0, Math.min(s.times.length - 1, Math.round(frame)));
    playback.update({
      mediaTime: s.times[f] ?? 0,
      sourceTime: s.times[f] ?? 0,
      sourceFrame: f,
      playing: false,
    });
    if (s.analysisEnabled && s.plan && !planStale()) {
      const part = objects(s.plan.parts).find((p) => {
        const w = object(p.window);
        return num(w.core_start_frame) <= f && f < num(w.core_end_frame);
      });
      const index = part ? num(object(part.window).index) : null;
      if (index !== s.partIndex) {
        invalidateView();
        publish({ partIndex: index, runs: {} });
        void refresh();
      }
    }
  }
  async function refresh() {
    if (disposed) return;
    if (polling && pollingView === viewVersion) {
      pollAgain = true;
      return;
    }
    const owner = scope.current();
    if (!owner) return;
    const version = viewVersion,
      poll = ++activePoll;
    polling = true;
    pollingView = version;
    pollAgain = false;
    const pendingView: {
      value: {
        plan: ObjectData | null;
        enabled: boolean;
        index: number | null;
      } | null;
    } = { value: null };
    try {
      await resource.run(
        owner,
        async (signal) => {
          const jobs = parseJobs(
            await api.request("get", "/api/jobs", { signal }),
          );
          const s = snapshot();
          const v = s.video;
          if (!v || v.id !== owner.id) return null;
          let plan = s.plan,
            analysisEnabled = s.analysisEnabled,
            partIndex = s.partIndex;
          // Actor hints belong to this manifest's identity result. A new plan
          // may reuse player runs before it has produced any identity links.
          let actors: ObjectData[] = [];
          const analysis = jobs.find(
            (j) => j.video_id === v.id && j.kind === "analysis",
          );
          if (analysis) {
            plan = object(
              await api.request(
                "get",
                "/api/videos/{video_id}/analysis/{job_id}",
                { path: { video_id: v.id, job_id: analysis.id }, signal },
              ),
            );
            parseAnalysis(plan, v.id, analysis.id);
            if (
              automaticAnalysis &&
              (!s.plan || object(s.plan.job).id !== analysis.id)
            ) {
              analysisEnabled = true;
              const frame =
                playback.getSnapshot().sourceFrame ?? v.review_start_frame;
              const part = objects(plan.parts).find((p) => {
                const w = object(p.window);
                return (
                  num(w.core_start_frame) <= frame &&
                  frame < num(w.core_end_frame)
                );
              });
              partIndex = part ? num(object(part.window).index) : null;
            }
            if (plan.identities) {
              const identity = object(plan.identities),
                runId = str(identity.run_id);
              if (runId) {
                const run = parseRun(
                  await api.request(
                    "get",
                    "/api/videos/{video_id}/runs/{job_id}",
                    { path: { video_id: v.id, job_id: runId }, signal },
                  ),
                );
                actors = run.requires_context_rerun ? [] : objects(run.tracks);
              }
            }
          }
          if (plan && planStale(plan)) analysisEnabled = false;
          pendingView.value = {
            plan,
            enabled: analysisEnabled,
            index: partIndex,
          };
          const part =
            analysisEnabled && plan
              ? objects(plan.parts).find(
                  (p) => num(object(p.window).index) === partIndex,
                )
              : null;
          const stages = part ? object(part.stages) : {};
          const matches = (j: Job) =>
            analysisEnabled
              ? j.id === object(stages[j.kind] ?? {}).run_id
              : !j.analysis_key;
          const runs: Partial<Record<Stage, LoadedRun>> = {};
          for (const stage of [
            "segments",
            "players",
            "shuttle",
            "contacts",
            "recognition",
            "rallies",
          ] as const) {
            const job = jobs.find(
              (j) =>
                j.video_id === v.id &&
                j.kind === stage &&
                j.status === "completed" &&
                (stage === "segments" || matches(j)) &&
                (stage !== "contacts" ||
                  j.summary.shuttle_run_id === runs.shuttle?.id) &&
                (!["recognition", "rallies"].includes(stage) ||
                  (j.summary.player_run_id === runs.players?.id &&
                    j.summary.shuttle_run_id === runs.shuttle?.id)),
            );
            if (job) {
              const prior = s.runs[stage];
              runs[stage] =
                prior?.id === job.id
                  ? prior
                  : {
                      id: job.id,
                      run: parseRun(
                        await api.request(
                          "get",
                          "/api/videos/{video_id}/runs/{job_id}",
                          { path: { video_id: v.id, job_id: job.id }, signal },
                        ),
                      ),
                    };
            }
          }
          const pb = parsePlayback(
            await api.request("get", "/api/videos/{video_id}/playback", {
              path: { video_id: v.id },
              signal,
            }),
            v.id,
          );
          const busy = jobs.some(
            (j) =>
              j.video_id === v.id &&
              j.kind === "playback" &&
              ["queued", "running"].includes(j.status),
          );
          return {
            jobs,
            plan,
            analysisEnabled,
            partIndex,
            actors,
            runs,
            playbackUrl: pb.url,
            playbackBusy: busy,
          };
        },
        (result) => {
          if (
            version === viewVersion &&
            result &&
            !reconcileInitialCore(
              result.plan,
              result.analysisEnabled,
              result.partIndex,
            )
          )
            publish(result);
        },
      );
    } catch (e) {
      if (
        scope.isCurrent(owner) &&
        version === viewVersion &&
        !(
          pendingView.value &&
          reconcileInitialCore(
            pendingView.value.plan,
            pendingView.value.enabled,
            pendingView.value.index,
          )
        )
      )
        handle(e);
    } finally {
      // An ignored abort may outlive a replacement poll. Only the active
      // poll may release its busy flag or consume its queued refresh.
      if (poll === activePoll) {
        polling = false;
        if (pollAgain) {
          pollAgain = false;
          void refresh();
        }
      }
    }
  }
  async function save() {
    const ticket = drafts.beginSave();
    if (!ticket) return;
    try {
      const result = await api.request(
        "put",
        "/api/videos/{video_id}/annotations",
        {
          path: { video_id: ticket.owner.id },
          json: { ...ticket.value, revision: ticket.revision },
          signal: ticket.owner.signal,
        },
      );
      const doc = parseDocument(result);
      if (drafts.completeSave(ticket, doc.revision, doc)) {
        notice(
          drafts.getSnapshot()?.dirty
            ? "Earlier edits saved. Save again to keep your newest changes."
            : "Annotations saved. JSON and CSV exports include this revision.",
        );
      }
    } catch (e) {
      if (drafts.failSave(ticket, e)) handle(e);
    }
  }
  function requireSaved() {
    const v = snapshot().video;
    if (!v) throw Error("Choose a video first.");
    if (drafts.getSnapshot()?.dirty || drafts.getSnapshot()?.saving)
      throw Error("Save annotations before running analysis or exporting.");
    return v;
  }
  async function command(action: () => Promise<unknown>, message: string) {
    const owner = scope.current(),
      version = viewVersion;
    try {
      await action();
      if (owner && scope.isCurrent(owner) && version === viewVersion) {
        notice(message);
        await refresh();
      }
    } catch (e) {
      if (owner && scope.isCurrent(owner) && version === viewVersion) handle(e);
    }
  }
  function track(
    stage: "players" | "shuttle",
    settings: { duration: number; model: "small" | "nano"; auto: boolean },
  ) {
    let v: Video;
    try {
      v = requireSaved();
    } catch (e) {
      handle(e);
      return;
    }
    const s = snapshot(),
      start = playback.getSnapshot().sourceFrame ?? 0;
    let end = start + 1;
    while (
      end < s.times.length &&
      (s.times[end] ?? Infinity) <
        (s.times[start] ?? 0) + settings.duration - 0.00001
    )
      end++;
    invalidateView();
    automaticAnalysis = false;
    publish({ analysisEnabled: false, partIndex: null, runs: {} });
    void refresh();
    void command(
      () =>
        api.request("post", "/api/videos/{video_id}/track", {
          path: { video_id: v.id },
          json: {
            start_frame: start,
            end_frame: end,
            stride: 1,
            stage,
            ...(stage === "players"
              ? { player_model: settings.model, auto_calibrate: settings.auto }
              : {}),
          },
        }),
      "Tracking queued",
    );
  }
  function suggest(
    stage: "contacts" | "recognition" | "rallies" | "segments",
    audio = false,
  ) {
    let v: Video;
    try {
      v = requireSaved();
    } catch (e) {
      handle(e);
      return;
    }
    const r = snapshot().runs;
    void command(async () => {
      if (stage === "segments")
        return api.request("post", "/api/videos/{video_id}/segments", {
          path: { video_id: v.id },
        });
      if (!r.shuttle) throw Error("Track the shuttle first.");
      if (stage === "contacts")
        return api.request("post", "/api/videos/{video_id}/contacts", {
          path: { video_id: v.id },
          json: {
            shuttle_run_id: r.shuttle.id,
            player_run_id: r.players?.id ?? null,
            include_audio: audio,
          },
        });
      if (!r.players) throw Error("Track players first.");
      if (stage === "rallies")
        return api.request("post", "/api/videos/{video_id}/rallies", {
          path: { video_id: v.id },
          json: { player_run_id: r.players.id, shuttle_run_id: r.shuttle.id },
        });
      return api.request("post", "/api/videos/{video_id}/recognize", {
        path: { video_id: v.id },
        json: {
          player_run_id: r.players.id,
          shuttle_run_id: r.shuttle.id,
          contacts_run_id: r.contacts?.id ?? null,
        },
      });
    }, "Suggestions queued. Review every proposed event before adding it.");
  }
  function preparePlayback() {
    const v = snapshot().video;
    if (v)
      void command(
        () =>
          api.request("post", "/api/videos/{video_id}/playback", {
            path: { video_id: v.id },
          }),
        "Preparing playback. Exact-frame review remains available.",
      );
  }
  function process(settings: Schema["AnalysisRequest"]) {
    let v: Video;
    try {
      v = requireSaved();
    } catch (e) {
      handle(e);
      return;
    }
    invalidateView();
    automaticAnalysis = true;
    void command(
      () =>
        api.request("post", "/api/videos/{video_id}/analysis", {
          path: { video_id: v.id },
          json: settings,
        }),
      "Full-match processing queued. Completed stages will be reused when their inputs match.",
    );
  }
  function pause() {
    const v = snapshot().video,
      job = snapshot().jobs.find(
        (j) => j.video_id === v?.id && j.kind === "analysis",
      );
    if (v && job)
      void command(
        () =>
          api.request(
            "post",
            "/api/videos/{video_id}/analysis/{job_id}/pause",
            { path: { video_id: v.id, job_id: job.id } },
          ),
        "Pausing processing; completed stages remain available to resume.",
      );
  }
  async function evaluate() {
    const owner = scope.current();
    if (!owner || disposed) return;
    let requestVersion = evaluationVersion;
    try {
      const v = requireSaved(),
        r = snapshot().runs,
        version = edits,
        revision = drafts.getSnapshot()!.revision,
        inputs = evaluationInputs(snapshot());
      if (!r.contacts && !r.shuttle && !r.recognition && !r.rallies)
        throw Error("Run tracking or event proposals first.");
      const runIds = {
        contacts: r.contacts?.id ?? null,
        shuttle: r.shuttle?.id ?? null,
        recognition: r.recognition?.id ?? null,
        rallies: r.rallies?.id ?? null,
      };
      invalidateEvaluation();
      requestVersion = evaluationVersion;
      await evaluation.run(
        owner,
        async (signal) => {
          const report = object(
            await api.request("post", "/api/videos/{video_id}/evaluate", {
              path: { video_id: v.id },
              signal,
              json: {
                contacts_run_id: runIds.contacts,
                shuttle_run_id: runIds.shuttle,
                recognition_run_id: runIds.recognition,
                rallies_run_id: runIds.rallies,
              },
            }),
          );
          if (
            report.video_id !== v.id ||
            report.annotation_revision !== revision ||
            evaluatedStages.some((stage) => {
              const result = report[stage];
              return runIds[stage] === null
                ? result != null
                : !result ||
                    typeof result !== "object" ||
                    Array.isArray(result) ||
                    (result as ObjectData).run_id !== runIds[stage];
            })
          )
            throw Error(
              "Evaluation response does not match the selected source, saved revision or input runs. Reload the saved revision and measure again.",
            );
          return report;
        },
        (report) => {
          const draft = drafts.getSnapshot();
          if (
            requestVersion === evaluationVersion &&
            version === edits &&
            draft?.revision === revision &&
            !draft.dirty &&
            !draft.saving &&
            inputs === evaluationInputs(snapshot())
          )
            publish({ report });
        },
      );
    } catch (e) {
      if (scope.isCurrent(owner) && requestVersion === evaluationVersion)
        handle(e);
    }
  }
  function reviewPart(index: number) {
    const s = snapshot();
    if (planStale()) {
      notice(
        "Camera, scene or court context changed. Save, then process again.",
        true,
      );
      return;
    }
    const part = objects(s.plan?.parts).find(
      (p) => num(object(p.window).index) === index,
    );
    if (part) {
      invalidateView();
      publish({ analysisEnabled: true, partIndex: index, runs: {} });
      const frame = num(object(part.window).core_start_frame);
      setFrame(frame);
      void refresh();
      return frame;
    }
  }
  function leave() {
    invalidateView();
    automaticAnalysis = false;
    publish({ analysisEnabled: false, partIndex: null, runs: {} });
    void refresh();
  }
  async function reload() {
    if (drafts.getSnapshot()?.saving) return;
    const id = snapshot().video?.id;
    if (!id) return;
    if (
      drafts.getSnapshot()?.dirty &&
      !window.confirm("Discard unsaved edits and reload the saved revision?")
    )
      return;
    drafts.discard();
    await select(id);
  }
  function start() {
    disposed = false;
    void library().catch(handle);
    const timer = window.setInterval(() => {
      void refresh();
    }, 2000);
    return () => {
      invalidateEvaluation();
      disposed = true;
      selectionBusy = true;
      window.clearInterval(timer);
      scope.clear();
      load.cancel();
      resource.cancel();
    };
  }
  return {
    snapshot,
    subscribe: store.subscribe,
    drafts,
    playback,
    select,
    library,
    edit,
    save,
    notice,
    handle,
    refresh,
    setFrame,
    track,
    suggest,
    preparePlayback,
    process,
    pause,
    evaluate,
    reviewPart,
    leave,
    planStale,
    currentPart,
    stageMatches,
    reload,
    start,
  };
}
export type EditorController = ReturnType<typeof createEditorController>;
