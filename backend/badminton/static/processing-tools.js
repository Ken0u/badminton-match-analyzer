import { courtSignature } from "./court-context.js";

export function stageMatches(state, job) {
  if (state.analysisEnabled)
    return job.id === state.analysisPart?.stages?.[job.kind]?.run_id;
  return !job.analysis_key;
}

export function ownedCandidates(run) {
  return (run?.candidates ?? []).filter(
    (c) =>
      run.analysis_core_start_frame == null ||
      (run.analysis_core_start_frame <= c.frame &&
        c.frame < run.analysis_core_end_frame),
  );
}

export function createProcessingTools({
  state,
  $,
  api,
  notice,
  seek,
  clock,
  pollJobs,
  clearLoaded,
}) {
  let plan = null,
    jobId = null;
  function scope() {
    return state.analysisEnabled
      ? `${plan?.analysis_key}:${state.analysisPart?.window.index}`
      : "window";
  }
  function setPart(part) {
    const before = scope();
    state.analysisPart = part;
    if (before !== scope()) clearLoaded();
  }
  function stale() {
    if (!plan?.recipe) return false;
    const doc = state.doc,
      end = state.times.length;
    const current = {
      camera: (doc.camera_corrections ?? [])
        .filter((c) => c.frame < end)
        .sort((a, b) => a.frame - b.frame)
        .map((c) => [c.frame, c.is_cut]),
      scenes: (doc.scene_ranges ?? [])
        .filter((r) => r.start_frame < end && r.end_frame > 0)
        .sort((a, b) => a.start_frame - b.start_frame)
        .map((r) => [r.start_frame, r.end_frame, r.scene]),
      court: courtSignature(doc, null, 0, end),
    };
    return (
      plan.requires_processing_rerun ||
      JSON.stringify(current) !== JSON.stringify(plan.recipe.context_signature)
    );
  }
  function reset() {
    plan = null;
    jobId = null;
    state.analysisEnabled = false;
    state.analysisPart = null;
    $("analysis-windows").innerHTML = "";
    $("analysis-status").textContent =
      "Process all source frames; completed stages are reused after a pause or restart.";
    $("pause-analysis").disabled = true;
    $("review-analysis").disabled = true;
    $("leave-analysis").disabled = true;
  }
  function frameChanged() {
    if (!state.analysisEnabled || !plan) return;
    setPart(
      plan.parts.find(
        (p) =>
          p.window.core_start_frame <= state.frame &&
          state.frame < p.window.core_end_frame,
      ) ?? null,
    );
    if (state.analysisPart)
      $("analysis-windows").value = state.analysisPart.window.index;
  }
  function leave() {
    if (!state.analysisEnabled) return;
    state.analysisEnabled = false;
    state.analysisPart = null;
    clearLoaded();
  }
  function render() {
    if (!plan) return;
    if (stale()) {
      $("analysis-status").textContent =
        "Camera, scene or court context changed. Save, then process again with the current context.";
      if (state.analysisEnabled) leave();
      $("review-analysis").disabled = true;
      return;
    }
    const active = plan.active;
    const stateText =
      plan.state === "completed"
        ? "Processing complete; review proposals and unresolved labels"
        : plan.job.cancel_requested &&
            ["queued", "running"].includes(plan.job.status)
          ? "Pausing…"
          : plan.state === "interrupted"
            ? "Paused; resume to reuse completed stages"
            : plan.state === "failed"
              ? `Stopped: ${plan.error || plan.job.message}`
              : `Processing ${active?.stage ?? "source"}${active?.part_index >= 0 ? ` · window ${active.part_index + 1}` : ""}`;
    $("analysis-status").textContent =
      `${stateText} · ${Math.round((plan.job.progress ?? 0) * 100)}%`;
    $("review-analysis").disabled = !plan.parts.length;
    $("leave-analysis").disabled = !state.analysisEnabled;
  }
  async function refresh(jobs, active) {
    $("process-analysis").disabled = !!active || !state.video;
    $("pause-analysis").disabled =
      !active ||
      active.kind !== "analysis" ||
      active.video_id !== state.video?.id ||
      active.cancel_requested;
    if (!state.video) return;
    const job = jobs.find(
      (j) => j.kind === "analysis" && j.video_id === state.video.id,
    );
    if (!job) return;
    const generation = state.selectionGeneration;
    const result = await api(
      `/api/videos/${state.video.id}/analysis/${job.id}`,
    );
    if (generation !== state.selectionGeneration) return;
    const isNew = job.id !== jobId;
    const oldKey = plan?.analysis_key;
    plan = result;
    jobId = job.id;
    if (isNew) {
      state.analysisEnabled = true;
      clearLoaded();
    }
    if (oldKey && oldKey !== plan.analysis_key) clearLoaded();
    const selected = $("analysis-windows").value;
    $("analysis-windows").replaceChildren(
      ...plan.parts.map((part) => {
        const option = document.createElement("option"),
          w = part.window;
        option.value = w.index;
        option.textContent = `${clock(state.times[w.core_start_frame])}–${clock(state.times[w.core_end_frame] ?? state.video.duration_s)} · ${Object.keys(part.stages).length}/5 stages`;
        return option;
      }),
    );
    if ([...$("analysis-windows").options].some((o) => o.value === selected))
      $("analysis-windows").value = selected;
    frameChanged();
    render();
  }
  $("process-analysis").onclick = async () => {
    try {
      if (state.dirty)
        throw Error("Save annotations before processing the match.");
      await api(`/api/videos/${state.video.id}/analysis`, {
        method: "POST",
        body: JSON.stringify({
          player_model: $("player-model").value,
          auto_calibrate: $("auto-court").checked,
          recognize: $("analysis-recognize").checked,
        }),
      });
      $("analysis-status").textContent = "Processing queued…";
      notice(
        "Full-match processing queued. Completed stages will be reused when their inputs match.",
      );
      await pollJobs();
    } catch (error) {
      notice(error.message, true);
    }
  };
  $("pause-analysis").onclick = async () => {
    try {
      await api(`/api/videos/${state.video.id}/analysis/${jobId}/pause`, {
        method: "POST",
      });
      notice(
        "Pausing processing; completed stages remain available to resume.",
      );
      await pollJobs();
    } catch (error) {
      notice(error.message, true);
    }
  };
  $("review-analysis").onclick = () => {
    const part = plan?.parts.find(
      (p) => p.window.index === Number($("analysis-windows").value),
    );
    if (!part || stale()) return;
    state.analysisEnabled = true;
    setPart(part);
    seek(part.window.core_start_frame);
    pollJobs().catch((e) => notice(e.message, true));
  };
  $("leave-analysis").onclick = () => {
    leave();
    pollJobs().catch((e) => notice(e.message, true));
  };
  return { reset, refresh, render, scope, frameChanged, leave };
}
