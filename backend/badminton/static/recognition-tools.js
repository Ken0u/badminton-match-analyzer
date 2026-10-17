export function createRecognitionTools({
  state,
  $,
  api,
  notice,
  escape,
  resetEditor,
  editEvent,
  seek,
  kindFields,
}) {
  let run = null,
    jobId = null;
  function reset() {
    run = null;
    jobId = null;
    state.recognitionJob = null;
    $("recognize").disabled = true;
    $("recognition-status").textContent =
      "Track players and the shuttle to suggest shot families.";
    render();
  }
  function render() {
    if (!state.doc) return;
    const candidates = run?.candidates ?? [];
    $("stroke-count").textContent = candidates.length;
    $("stroke-predictions").innerHTML = candidates.length
      ? candidates
          .map((c) => {
            const applied = state.doc.events.some(
              (e) =>
                e.classification_run_id === jobId &&
                e.classification_candidate_id === c.id,
            );
            const sourceEvent =
              c.event_id && state.doc.events.find((e) => e.id === c.event_id);
            const stale =
              c.event_id && (!sourceEvent || sourceEvent.frame !== c.frame);
            const result =
              c.status === "predicted"
                ? c.kind === "serve"
                  ? "Possible serve"
                  : `Possible ${c.family}`
                : "Needs source review";
            const alternatives = (c.top_classes ?? [])
              .map(
                (item) =>
                  `${item.source_type} ${(item.score * 100).toFixed(0)}%`,
              )
              .join(", ");
            return `<button class="candidate-row stroke-row" data-stroke="${escape(c.id)}" ${applied || stale ? "disabled" : ""}><time>F${c.frame}</time><span>${applied ? "Applied" : stale ? "Contact changed; classify again" : escape(result)}<small>${escape(c.reason ?? alternatives)}${c.family_score != null ? ` · family score ${c.family_score.toFixed(2)}` : ""} · stroke side needs review</small></span></button>`;
          })
          .join("")
      : '<p class="empty">Family suggestions appear here. They never replace your saved labels automatically.</p>';
    document.querySelectorAll("[data-stroke]").forEach(
      (button) =>
        (button.onclick = () => {
          const c = candidates.find((c) => c.id === button.dataset.stroke);
          if (!c || (c.status !== "predicted" && !c.top_classes?.length)) {
            if (c) {
              seek(c.frame);
              notice(c.reason ?? "More tracking context is needed.");
            }
            return;
          }
          if (c.event_id) editEvent(c.event_id);
          else {
            resetEditor();
            $("event-frame").value = c.frame;
            $("event-player").value = c.hitter_hint?.player_id ?? "";
            $("contact-start").value = c.contact_start_frame ?? "";
            $("contact-end").value = c.contact_end_frame ?? "";
            $("contact-uncertainty").open = c.contact_start_frame != null;
            if (c.contact_candidate_id && run.contacts_run_id)
              state.pendingCandidate = {
                id: c.contact_candidate_id,
                run_id: run.contacts_run_id,
              };
          }
          if (c.status === "predicted") {
            $("event-kind").value = c.kind;
            $("event-family").value = c.family ?? "unknown";
          }
          state.pendingClassification = {
            run_id: jobId,
            id: c.id,
            family: c.family,
            kind: c.kind,
            score: c.family_score,
            frame: c.frame,
          };
          kindFields();
          seek(c.frame);
          $("editor-hint").textContent =
            `Model suggestion at frame ${c.frame}; verify family, hitter, contact time and stroke side before updating.`;
          notice(
            "Suggestion loaded into the editor. Review it, then add or update and save the event.",
          );
        }),
    );
  }
  async function refresh(jobs, active) {
    $("recognize").disabled =
      !!active ||
      state.video?.mode !== "singles" ||
      !state.lastJob ||
      !state.shuttleJob;
    if (!state.video) return;
    if (state.video.mode !== "singles") {
      $("recognition-status").textContent =
        "The current learned family model supports singles. Doubles recognition remains in development.";
      return;
    }
    const running = jobs.find(
      (j) =>
        j.video_id === state.video.id &&
        j.kind === "recognition" &&
        ["queued", "running"].includes(j.status),
    );
    const latest = jobs.find(
      (j) => j.video_id === state.video.id && j.kind === "recognition",
    );
    if (latest?.status === "failed")
      $("recognition-status").textContent = latest.message;
    if (running)
      $("recognition-status").textContent =
        `Classifying · ${Math.round(running.progress * 100)}%`;
    const completed = jobs.find(
      (j) =>
        j.video_id === state.video.id &&
        j.kind === "recognition" &&
        j.status === "completed" &&
        j.summary?.player_run_id === state.lastJob &&
        j.summary?.shuttle_run_id === state.shuttleJob,
    );
    if (!completed) {
      if (run) {
        run = null;
        jobId = null;
        state.recognitionJob = null;
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
    state.recognitionJob = completed.id;
    $("recognition-status").textContent =
      `${result.predicted_count}/${result.candidate_count} family suggestions · saved revision ${result.annotation_revision} · experimental model scores`;
    render();
  }
  $("recognize").onclick = async () => {
    try {
      if (state.dirty)
        throw Error("Save annotations before classifying shot families.");
      await api(`/api/videos/${state.video.id}/recognize`, {
        method: "POST",
        body: JSON.stringify({
          player_run_id: state.lastJob,
          shuttle_run_id: state.shuttleJob,
          contacts_run_id: state.contactJob,
        }),
      });
      notice(
        "Classifying shot families from the saved contacts and tracks. Stroke side remains for review.",
      );
    } catch (e) {
      notice(e.message, true);
    }
  };
  return { reset, render, refresh };
}
