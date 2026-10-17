export function createSegmentTools({
  state,
  $,
  api,
  notice,
  seek,
  escape,
  clock,
  changed,
}) {
  let loaded = null,
    scan = null,
    editingScene = null;
  function reset() {
    loaded = null;
    scan = null;
    editingScene = null;
    $("segment-status").textContent =
      "Scan camera changes across the full video.";
    $("camera-boundaries").innerHTML = "";
    $("scene-ranges").innerHTML = "";
    delete $("camera-boundaries").dataset.runId;
    $("scan-segments").disabled = true;
    for (const id of [
      "camera-frame",
      "camera-notes",
      "scene-start",
      "scene-end",
      "scene-notes",
    ])
      $(id).value = "";
    $("add-scene").textContent = "Add scene range";
  }
  function attempt(action) {
    return () => {
      try {
        action();
      } catch (error) {
        notice(error.message, true);
      }
    };
  }
  function render() {
    if (!state.doc) return;
    state.doc.camera_corrections ??= [];
    state.doc.scene_ranges ??= [];
    const corrections = new Map(
      state.doc.camera_corrections.map((c) => [c.frame, c]),
    );
    const frames = [
      ...new Set([
        ...(scan?.boundaries ?? []).map((b) => b.frame),
        ...corrections.keys(),
      ]),
    ].sort((a, b) => a - b);
    $("camera-boundaries").innerHTML = frames.length
      ? frames
          .map((frame) => {
            const raw = scan?.boundaries.find((b) => b.frame === frame);
            const correction = corrections.get(frame);
            const decision = correction
              ? correction.is_cut
                ? "Confirmed cut"
                : "Rejected cut"
              : raw.reason.replaceAll("_", " ");
            return `<div class="boundary-row"><button type="button" class="quiet" data-boundary="${frame}">${clock(state.times[frame])} · frame ${frame} · ${escape(decision)}</button>${correction ? `<button type="button" class="quiet" data-reset-cut="${frame}">Remove correction</button>` : ""}</div>`;
          })
          .join("")
      : '<p class="empty">No boundaries loaded. Scan the video or add a missed cut at a reviewed source frame.</p>';
    $("camera-boundaries")
      .querySelectorAll("[data-boundary]")
      .forEach((button) => {
        button.onclick = () => {
          const frame = Number(button.dataset.boundary),
            correction = corrections.get(frame);
          $("camera-frame").value = frame;
          $("camera-decision").value =
            correction?.is_cut === false ? "not_cut" : "cut";
          $("camera-notes").value = correction?.notes ?? "";
          seek(frame);
          notice(
            "Possible camera boundary. Step back and forward to inspect it; this is not a rally boundary.",
          );
        };
      });
    $("camera-boundaries")
      .querySelectorAll("[data-reset-cut]")
      .forEach((button) => {
        button.onclick = () => {
          state.doc.camera_corrections = state.doc.camera_corrections.filter(
            (c) => c.frame !== Number(button.dataset.resetCut),
          );
          changed();
          notice(
            "Camera correction removed from the draft. Save before running analysis.",
          );
        };
      });
    $("scene-ranges").innerHTML = state.doc.scene_ranges
      .map(
        (r) =>
          `<div class="boundary-row"><button type="button" class="quiet" data-edit-scene="${escape(r.id)}">Frames ${r.start_frame}–${r.end_frame - 1} · ${escape(r.scene.replaceAll("_", " "))}</button><button type="button" class="quiet" data-remove-scene="${escape(r.id)}">Remove</button></div>`,
      )
      .join("");
    $("scene-ranges")
      .querySelectorAll("[data-edit-scene]")
      .forEach((button) => {
        button.onclick = () => {
          const r = state.doc.scene_ranges.find(
            (r) => r.id === button.dataset.editScene,
          );
          editingScene = r.id;
          $("scene-start").value = r.start_frame;
          $("scene-end").value = r.end_frame;
          $("scene-kind").value = r.scene;
          $("scene-notes").value = r.notes;
          $("add-scene").textContent = "Update scene range";
          seek(r.start_frame);
        };
      });
    $("scene-ranges")
      .querySelectorAll("[data-remove-scene]")
      .forEach((button) => {
        button.onclick = () => {
          state.doc.scene_ranges = state.doc.scene_ranges.filter(
            (r) => r.id !== button.dataset.removeScene,
          );
          if (editingScene === button.dataset.removeScene) {
            editingScene = null;
            $("add-scene").textContent = "Add scene range";
          }
          changed();
          notice(
            "Scene range removed from the draft. Save, then request new contacts and shot labels to restore omitted suggestions.",
          );
        };
      });
  }
  $("camera-use-frame").onclick = () => {
    $("camera-frame").value = state.frame;
  };
  $("camera-apply").onclick = attempt(() => {
    const frame = Number($("camera-frame").value);
    if (
      !$("camera-frame").value ||
      !Number.isInteger(frame) ||
      frame <= 0 ||
      frame >= state.times.length
    )
      throw Error(
        "Choose a boundary frame after frame 0 and inside the video.",
      );
    const is_cut = $("camera-decision").value === "cut";
    if (
      !is_cut &&
      state.times[frame] - state.times[frame - 1] >
        Math.max(0.1, 2.5 / state.video.fps) + 1e-8
    )
      throw Error("Cannot join a source timestamp discontinuity.");
    state.doc.camera_corrections = state.doc.camera_corrections.filter(
      (c) => c.frame !== frame,
    );
    state.doc.camera_corrections.push({
      frame,
      is_cut,
      notes: $("camera-notes").value,
    });
    changed();
    notice(
      "Camera correction added to the draft. Save, then rerun affected tracking windows.",
    );
  });
  $("add-scene").onclick = attempt(() => {
    const start_frame = Number($("scene-start").value),
      end_frame = Number($("scene-end").value);
    if (
      !$("scene-start").value ||
      !$("scene-end").value ||
      !Number.isInteger(start_frame) ||
      !Number.isInteger(end_frame) ||
      start_frame < 0 ||
      start_frame >= end_frame ||
      end_frame > state.times.length
    )
      throw Error("Choose a nonempty scene range within the source video.");
    const others = state.doc.scene_ranges.filter((r) => r.id !== editingScene);
    if (
      others.some((r) => r.start_frame < end_frame && start_frame < r.end_frame)
    )
      throw Error(
        "Reviewed scene ranges must not overlap. Edit or remove the existing range first.",
      );
    state.doc.scene_ranges = [
      ...others,
      {
        id: editingScene ?? crypto.randomUUID(),
        start_frame,
        end_frame,
        scene: $("scene-kind").value,
        notes: $("scene-notes").value,
      },
    ].sort((a, b) => a.start_frame - b.start_frame);
    editingScene = null;
    $("add-scene").textContent = "Add scene range";
    changed();
    notice("Scene range added to the draft. Save to apply event exclusions.");
  });
  $("scan-segments").onclick = async () => {
    try {
      const id = state.video?.id;
      if (!id) return;
      if (state.dirty) {
        notice("Save scene and camera corrections before scanning.", true);
        return;
      }
      $("scan-segments").disabled = true;
      await api(`/api/videos/${id}/segments`, { method: "POST" });
      notice(
        "Scanning camera changes. Rally and replay status still need review.",
      );
    } catch (error) {
      notice(error.message, true);
      $("scan-segments").disabled = false;
    }
  };
  async function refresh(jobs, active) {
    const id = state.video?.id;
    $("scan-segments").disabled = !!active || !id;
    if (!id) return;
    if (active?.kind === "segments" && active.video_id === id) {
      $("segment-status").textContent =
        `Scanning · ${Math.round(active.progress * 100)}%`;
      return;
    }
    const latest = jobs.find((j) => j.video_id === id && j.kind === "segments");
    if (latest?.status === "failed")
      $("segment-status").textContent = latest.message;
    const done = jobs.find(
      (j) =>
        j.video_id === id && j.kind === "segments" && j.status === "completed",
    );
    if (!done || done.id === loaded) return;
    const generation = state.selectionGeneration;
    const run = await api(`/api/videos/${id}/runs/${done.id}`);
    if (state.video?.id !== id || state.selectionGeneration !== generation)
      return;
    loaded = done.id;
    scan = run;
    $("camera-boundaries").dataset.runId = done.id;
    $("segment-status").textContent =
      `${run.boundaries.length} possible ${run.boundaries.length === 1 ? "boundary" : "boundaries"} · review scenes separately`;
    render();
  }
  return { refresh, reset, render };
}
