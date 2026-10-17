export function createReviewTools({
  state,
  $,
  changed,
  draw,
  seek,
  api,
  notice,
  escape,
  renderCandidates,
}) {
  let optionsRun = null;
  let reportUrl = null;
  function playerForTrack(runId, trackId, frame) {
    if (!runId || trackId == null) return null;
    return (
      state.doc?.track_assignments.find(
        (a) =>
          a.run_id === runId &&
          a.track_id === trackId &&
          a.start_frame <= frame &&
          frame < a.end_frame,
      )?.player_id ?? null
    );
  }
  function range(prefix) {
    const start_frame = Number($(`${prefix}-start`).value);
    const end_frame = Number($(`${prefix}-end`).value);
    if (
      !Number.isInteger(start_frame) ||
      !Number.isInteger(end_frame) ||
      start_frame < 0 ||
      end_frame <= start_frame ||
      end_frame > state.times.length
    )
      throw Error(
        "Enter a valid source-frame range. The end frame is excluded.",
      );
    return { start_frame, end_frame };
  }
  function attempt(action) {
    return () => {
      try {
        action();
      } catch (e) {
        notice(e.message, true);
      }
    };
  }
  function frameStatus() {
    if (!state.doc) return;
    const point = state.doc.shuttle_points.find((p) => p.frame === state.frame);
    $("shuttle-label-status").textContent =
      `${state.doc.shuttle_points.length} labeled frames · frame ${state.frame}: ${point ? (point.visible ? "visible, position marked" : "not visible") : "unlabeled"}${state.shuttleLabeling ? " · click the shuttle in the image" : ""}`;
    $("label-shuttle").textContent = state.shuttleLabeling
      ? "Cancel shuttle mark"
      : "Mark visible shuttle";
  }
  function render() {
    if (!state.doc) return;
    // New fields are optional in existing saved revisions.
    state.doc.review_windows ??= [];
    state.doc.shuttle_points ??= [];
    state.doc.track_assignments ??= [];
    const player = $("identity-player").value;
    $("identity-player").innerHTML = state.doc.players
      .map(
        (p) =>
          `<option value="${escape(p.id)}">${escape(p.name)} (${escape(p.id)})</option>`,
      )
      .join("");
    if (state.doc.players.some((p) => p.id === player))
      $("identity-player").value = player;
    if (optionsRun !== state.lastJob) {
      optionsRun = state.lastJob;
      const tracks = [
        ...new Set(
          state.run?.frames
            .flatMap((r) => r.players.map((p) => p.track_id))
            .filter((t) => t != null) ?? [],
        ),
      ].sort((a, b) => a - b);
      $("identity-track").innerHTML = tracks
        .map((t) => `<option value="${t}">Track ${t}</option>`)
        .join("");
      $("identity-start").value = state.run?.start_frame ?? state.frame;
      $("identity-end").value = state.run?.end_frame ?? state.frame + 1;
    }
    $("assign-identity").disabled =
      !state.lastJob || !$("identity-track").options.length;
    $("identity-list").innerHTML = state.doc.track_assignments
      .map(
        (a, i) =>
          `<div class="review-row"><span>Player ${escape(a.player_id)} ← Track ${a.track_id}<small>Frames ${a.start_frame}–${a.end_frame - 1}${a.run_id === state.lastJob ? " · loaded run" : " · another run"}</small></span><button class="quiet" data-remove-assignment="${i}" aria-label="Remove assignment ${i + 1}">Remove</button></div>`,
      )
      .join("");
    document.querySelectorAll("[data-remove-assignment]").forEach(
      (b) =>
        (b.onclick = () => {
          state.doc.track_assignments.splice(
            Number(b.dataset.removeAssignment),
            1,
          );
          changed();
          draw();
          renderCandidates();
        }),
    );
    $("review-list").innerHTML = state.doc.review_windows
      .map(
        (w) =>
          `<div class="review-row"><button class="quiet" data-load-review="${escape(w.id)}">Frames ${w.start_frame}–${w.end_frame - 1}<small>${escape(w.scene)} · ${w.contacts_complete ? "all contacts labeled" : "incomplete"}</small></button><button class="quiet" data-remove-review="${escape(w.id)}" aria-label="Remove reviewed clip">Remove</button></div>`,
      )
      .join("");
    document.querySelectorAll("[data-load-review]").forEach(
      (b) =>
        (b.onclick = () => {
          const w = state.doc.review_windows.find(
            (w) => w.id === b.dataset.loadReview,
          );
          $("review-start").value = w.start_frame;
          $("review-end").value = w.end_frame;
          $("review-scene").value = w.scene;
          $("review-complete").checked = w.contacts_complete;
          $("review-notes").value = w.notes;
          seek(w.start_frame);
        }),
    );
    document.querySelectorAll("[data-remove-review]").forEach(
      (b) =>
        (b.onclick = () => {
          state.doc.review_windows = state.doc.review_windows.filter(
            (w) => w.id !== b.dataset.removeReview,
          );
          changed();
        }),
    );
    frameStatus();
    if (state.dirty) {
      $("evaluation-results").textContent =
        "Save your edits, then measure this revision.";
      $("download-evaluation").hidden = true;
    }
  }
  function reset() {
    optionsRun = undefined;
    const start = state.video.review_start_frame ?? state.frame;
    $("review-start").value = start;
    $("review-end").value = Math.min(state.times.length, start + 250);
    $("review-scene").value = "unknown";
    $("review-complete").checked = false;
    $("review-notes").value = "";
    $("evaluation-results").textContent =
      "Label a complete live clip to measure contact accuracy.";
    $("download-evaluation").hidden = true;
    if (reportUrl) URL.revokeObjectURL(reportUrl);
    reportUrl = null;
    render();
  }
  $("assign-identity").onclick = attempt(() => {
    const bounds = range("identity"),
      track_id = Number($("identity-track").value),
      player_id = $("identity-player").value;
    if (!state.lastJob || !state.run) throw Error("Run player tracking first.");
    if (
      bounds.start_frame < state.run.start_frame ||
      bounds.end_frame > state.run.end_frame
    )
      throw Error("Keep the assignment inside the loaded tracking run.");
    const others = state.doc.track_assignments.filter(
      (a) =>
        !(
          a.run_id === state.lastJob &&
          a.track_id === track_id &&
          a.start_frame === bounds.start_frame &&
          a.end_frame === bounds.end_frame
        ),
    );
    if (
      others.some(
        (a) =>
          a.run_id === state.lastJob &&
          Math.max(a.start_frame, bounds.start_frame) <
            Math.min(a.end_frame, bounds.end_frame) &&
          (a.track_id === track_id || a.player_id === player_id),
      )
    )
      throw Error(
        "This overlaps an existing tracker or player assignment. Remove or shorten that assignment first.",
      );
    state.doc.track_assignments = [
      ...others,
      { run_id: state.lastJob, track_id, player_id, ...bounds },
    ];
    changed();
    draw();
    renderCandidates();
    notice("Player assignment added. Save annotations to keep it.");
  });
  $("add-review").onclick = attempt(() => {
    const bounds = range("review");
    const existing = state.doc.review_windows.find(
      (w) =>
        w.start_frame === bounds.start_frame &&
        w.end_frame === bounds.end_frame,
    );
    const others = state.doc.review_windows.filter((w) => w !== existing);
    if (
      others.some(
        (w) =>
          Math.max(w.start_frame, bounds.start_frame) <
          Math.min(w.end_frame, bounds.end_frame),
      )
    )
      throw Error(
        "Reviewed clips cannot overlap. Remove the old clip before changing its range.",
      );
    state.doc.review_windows = [
      ...others,
      {
        id: existing?.id ?? crypto.randomUUID(),
        ...bounds,
        contacts_complete: $("review-complete").checked,
        scene: $("review-scene").value,
        notes: $("review-notes").value,
      },
    ];
    changed();
    notice("Reviewed clip added. Save annotations before measuring accuracy.");
  });
  $("label-shuttle").onclick = () => {
    state.corners = null;
    $("calibrate").textContent = "Select 4 corners";
    $("calibration-hint").hidden = true;
    state.shuttleLabeling = !state.shuttleLabeling;
    $("stage").classList.toggle("calibrating", state.shuttleLabeling);
    if (state.shuttleLabeling) {
      $("show-shuttle").checked = false;
      seek(state.frame);
    }
    frameStatus();
    draw();
  };
  function setPoint(point) {
    state.doc.shuttle_points = state.doc.shuttle_points.filter(
      (p) => p.frame !== state.frame,
    );
    state.doc.shuttle_points.push(point);
    state.shuttleLabeling = false;
    $("stage").classList.remove("calibrating");
    changed();
    draw();
  }
  $("label-invisible").onclick = () => {
    seek(state.frame);
    setPoint({ frame: state.frame, visible: false, x: null, y: null });
    notice(
      "Shuttle labeled not visible at this frame. Save annotations to keep it.",
    );
  };
  $("clear-shuttle-label").onclick = () => {
    state.doc.shuttle_points = state.doc.shuttle_points.filter(
      (p) => p.frame !== state.frame,
    );
    state.shuttleLabeling = false;
    $("stage").classList.remove("calibrating");
    changed();
    draw();
  };
  function capturePoint(e) {
    if (!state.shuttleLabeling) return false;
    const image = $("exact-frame");
    if (image.hidden || !image.complete || !image.naturalWidth) {
      notice(
        "Wait for the exact source frame to load before marking the shuttle.",
        true,
      );
      return true;
    }
    const r = $("overlay").getBoundingClientRect();
    setPoint({
      frame: state.frame,
      visible: true,
      x: Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)),
      y: Math.max(0, Math.min(1, (e.clientY - r.top) / r.height)),
    });
    notice("Shuttle position labeled. Save annotations to keep it.");
    return true;
  }
  function drawPoint(ctx) {
    const point = state.doc.shuttle_points.find((p) => p.frame === state.frame);
    if (!point?.visible) return;
    const x = point.x * ctx.canvas.width,
      y = point.y * ctx.canvas.height;
    ctx.strokeStyle = "#75e0f5";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 10, 0, Math.PI * 2);
    ctx.moveTo(x - 14, y);
    ctx.lineTo(x + 14, y);
    ctx.moveTo(x, y - 14);
    ctx.lineTo(x, y + 14);
    ctx.stroke();
  }
  $("evaluate").onclick = async () => {
    try {
      if (state.dirty)
        throw Error("Save annotations before measuring accuracy.");
      if (!state.contactJob && !state.shuttleJob)
        throw Error("Run shuttle tracking and contact proposals first.");
      const videoId = state.video.id,
        generation = state.selectionGeneration,
        version = state.editVersion;
      $("evaluation-results").textContent = "Measuring saved labels…";
      const report = await api(`/api/videos/${videoId}/evaluate`, {
        method: "POST",
        body: JSON.stringify({
          contacts_run_id: state.contactJob,
          shuttle_run_id: state.shuttleJob,
        }),
      });
      if (
        generation !== state.selectionGeneration ||
        version !== state.editVersion
      )
        return;
      showReport(report);
      if (reportUrl) URL.revokeObjectURL(reportUrl);
      reportUrl = URL.createObjectURL(
        new Blob([JSON.stringify(report, null, 2)], {
          type: "application/json",
        }),
      );
      $("download-evaluation").href = reportUrl;
      $("download-evaluation").download = `${videoId}-evaluation.json`;
      $("download-evaluation").hidden = false;
    } catch (e) {
      notice(e.message, true);
      $("evaluation-results").textContent = "Measurement unavailable.";
    }
  };
  function showReport(report) {
    // The downloadable report retains sample counts, matching errors, and provenance.
    const percent = (n) => (n == null ? "—" : `${(n * 100).toFixed(1)}%`);
    const parts = [`<p>Saved revision ${report.annotation_revision}</p>`];
    for (const [key, title] of [
      ["contacts", "Contacts"],
      ["shuttle", "Shuttle"],
    ]) {
      const result = report[key];
      if (!result) continue;
      const metric = result.metrics;
      if (!metric)
        parts.push(
          `<p>${title}: ${key === "contacts" ? "No complete live clip is fully covered by this run." : "No manually labeled shuttle frames in this run."}</p>`,
        );
      else
        parts.push(
          `<p><strong>${title} F1 ${percent(metric.f1)}</strong><br>Precision ${percent(metric.precision)} · recall ${percent(metric.recall)}<br>${metric.tp} matched · ${metric.fp} false · ${metric.fn} missed</p>`,
        );
      if (metric && key === "contacts")
        parts.push(
          `<small>${result.coverage.reviewed_contacts} reviewed contacts · ±${Math.round(result.tolerance_s * 1000)} ms tolerance</small>`,
        );
      if (metric && key === "shuttle")
        parts.push(
          `<small>${result.coverage.labeled_frames} labeled frames · ${result.tolerance_px.toFixed(1)} px tolerance</small>`,
        );
    }
    $("evaluation-results").innerHTML = parts.join("");
  }
  return {
    render,
    reset,
    frameStatus,
    playerForTrack,
    capturePoint,
    drawPoint,
  };
}
