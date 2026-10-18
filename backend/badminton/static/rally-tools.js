import { courtSignature } from "./court-context.js";

export function createRallyTools({
  state,
  $,
  api,
  notice,
  escape,
  clock,
  resetEditor,
  seek,
}) {
  let run = null,
    jobId = null;
  function signature() {
    if (!run) return null;
    const start = run.context_start_frame,
      end = run.context_end_frame;
    return {
      camera: (state.doc.camera_corrections ?? [])
        .filter((c) => c.frame < end && (c.frame >= start || c.is_cut))
        .sort((a, b) => a.frame - b.frame)
        .map((c) => [c.frame, c.is_cut]),
      scenes: (state.doc.scene_ranges ?? [])
        .filter((r) => r.start_frame < end && start < r.end_frame)
        .sort((a, b) => a.start_frame - b.start_frame)
        .map((r) => [r.start_frame, r.end_frame, r.scene]),
      court: courtSignature(state.doc, run.court_context, start, end),
    };
  }
  function reset() {
    run = null;
    jobId = null;
    $("suggest-rallies").disabled = true;
    $("rally-status").textContent =
      "Track players and the shuttle at every frame first.";
    render();
  }
  function render() {
    const candidates = run?.candidates ?? [];
    const stale =
      run &&
      JSON.stringify(signature()) !== JSON.stringify(run.context_signature);
    $("rally-count").textContent = candidates.length;
    $("rally-candidates").innerHTML = candidates.length
      ? candidates
          .map((c) => {
            const added = state.doc.events.some(
              (e) => e.source_run_id === jobId && e.candidate_id === c.id,
            );
            const surround =
              c.evidence?.settled_region === "near_court_surround";
            return `<button class="candidate-row" data-rally-candidate="${escape(c.id)}" ${stale || added ? "disabled" : ""}><time>${clock(c.time_s)}</time><span>${stale ? "Review context changed; request new boundaries" : added ? "Added" : c.kind === "serve" ? "Review possible serve" : "Review possible rally end"}<small>Frames ${c.start_frame}–${c.end_frame} · timing uncertain${c.kind === "serve" ? " · hitter unconfirmed" : surround ? " · near court edge; verify landing" : ""}</small></span></button>`;
          })
          .join("")
      : '<p class="empty">Boundary suggestions appear here. Missing proposals do not mean there was no rally.</p>';
    document.querySelectorAll("[data-rally-candidate]").forEach((button) => {
      button.onclick = () => {
        const c = candidates.find(
          (c) => c.id === button.dataset.rallyCandidate,
        );
        resetEditor(c.kind);
        $("event-frame").value = c.frame;
        $("event-player").value = "";
        $("contact-start").value = c.start_frame;
        $("contact-end").value = c.end_frame;
        $("contact-uncertainty").open = true;
        $("event-notes").value =
          `Experimental ${c.kind === "serve" ? "serve" : "rally-end"} suggestion; verify the source and uncertain timing.` +
          (c.evidence?.settled_region === "near_court_surround"
            ? " Shuttle settled near a court edge; landing, fault and line call are unverified."
            : "");
        state.pendingCandidate = { id: c.id, run_id: jobId };
        seek(c.frame);
        $("editor-hint").textContent =
          `Possible ${c.kind === "serve" ? "serve" : "rally end"} within frames ${c.start_frame}–${c.end_frame}. The navigation frame is an estimate. Verify before adding.`;
        notice(
          "Suggestion loaded into the editor. Review the interval, then add and save the event.",
        );
      };
    });
  }
  async function refresh(jobs, active) {
    $("suggest-rallies").disabled =
      !!active || !state.lastJob || !state.shuttleJob;
    if (!state.video) return;
    const latest = jobs.find(
      (j) => j.video_id === state.video.id && j.kind === "rallies",
    );
    if (latest?.status === "failed")
      $("rally-status").textContent = latest.message;
    if (["queued", "running"].includes(latest?.status))
      $("rally-status").textContent = "Looking for boundary evidence…";
    const completed = jobs.find(
      (j) =>
        j.video_id === state.video.id &&
        j.kind === "rallies" &&
        j.status === "completed" &&
        j.summary?.player_run_id === state.lastJob &&
        j.summary?.shuttle_run_id === state.shuttleJob,
    );
    if (!completed) {
      if (run) {
        run = null;
        jobId = null;
        render();
      }
      return;
    }
    if (completed.id === jobId) return;
    const generation = state.selectionGeneration;
    const result = await api(
      `/api/videos/${state.video.id}/runs/${completed.id}`,
    );
    if (generation !== state.selectionGeneration) return;
    run = result;
    jobId = completed.id;
    $("rally-status").textContent =
      `${result.candidate_count} experimental boundaries · saved revision ${result.annotation_revision} · ${result.diagnostics.eligible_frames} frames with usable camera/court context`;
    render();
  }
  $("suggest-rallies").onclick = async () => {
    try {
      if (state.dirty)
        throw Error("Save annotations before requesting rally boundaries.");
      await api(`/api/videos/${state.video.id}/rallies`, {
        method: "POST",
        body: JSON.stringify({
          player_run_id: state.lastJob,
          shuttle_run_id: state.shuttleJob,
        }),
      });
      notice(
        "Finding possible serves and rally endings. Review every interval before adding events.",
      );
    } catch (e) {
      notice(e.message, true);
    }
  };
  return { reset, render, refresh };
}
