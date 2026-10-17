import { createReviewTools } from "./review-tools.js";
import { createImportTools } from "./import-tools.js";
import { createRecognitionTools } from "./recognition-tools.js";
const $ = (id) => document.getElementById(id);
const state = {
  videos: [],
  video: null,
  doc: null,
  times: [],
  frame: 0,
  selected: null,
  dirty: false,
  corners: null,
  run: null,
  runMap: new Map(),
  jobs: [],
  lastJob: null,
  selectionGeneration: 0,
  editVersion: 0,
  saving: false,
  shuttleRun: null,
  shuttleMap: new Map(),
  shuttleJob: null,
  contactRun: null,
  contactJob: null,
  pendingCandidate: null,
  pendingClassification: null,
  recognitionJob: null,
  shuttleLabeling: false,
};
const escape = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const pretty = (s) => String(s ?? "Unknown").replaceAll("_", " ");
const clock = (t) =>
  `${Math.floor(t / 60)}:${(t % 60).toFixed(2).padStart(5, "0")}`;
function notice(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
async function api(path, options = {}) {
  const r = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  if (!r.ok) {
    const raw = await r.text();
    let b;
    try {
      b = JSON.parse(raw);
    } catch {
      b = { detail: raw };
    }
    const detail =
      typeof b.detail === "string" ? b.detail : JSON.stringify(b.detail);
    throw Error(detail || `Request failed (${r.status})`);
  }
  return r.json();
}
function changed() {
  state.editVersion += 1;
  state.dirty = true;
  $("save-state").textContent = "Unsaved edits";
  $("save").disabled = false;
  reviewTools.render();
  recognitionTools.render();
}
function handleError(e) {
  notice(e.message || String(e), true);
}
async function loadLibrary() {
  state.videos = await api("/api/videos");
  $("library-count").textContent = state.videos.length;
  $("library").innerHTML = state.videos
    .map(
      (v) =>
        `<button class="library-item ${state.video?.id === v.id ? "active" : ""}" data-video="${v.id}"><img src="/api/videos/${v.id}/image/poster.jpg" alt=""><strong>${escape(v.name)}</strong><small>${v.mode} · ${clock(v.duration_s)}</small></button>`,
    )
    .join("");
  document
    .querySelectorAll("[data-video]")
    .forEach(
      (b) =>
        (b.onclick = () => selectVideo(b.dataset.video).catch(handleError)),
    );
}
async function selectVideo(id) {
  if (state.saving) {
    notice("Saving annotations. Switch videos after the save finishes.");
    return;
  }
  if (state.dirty && !confirm("Discard unsaved edits and open another video?"))
    return;
  const generation = ++state.selectionGeneration;
  $("video").pause();
  $("exact-frame").hidden = true;
  const [video, doc, times] = await Promise.all([
    api(`/api/videos/${id}`),
    api(`/api/videos/${id}/annotations`),
    api(`/api/videos/${id}/timestamps`),
  ]);
  if (generation !== state.selectionGeneration) return;
  Object.assign(state, {
    video,
    doc,
    times,
    frame: 0,
    selected: null,
    dirty: false,
    corners: null,
    run: null,
    runMap: new Map(),
    lastJob: null,
    shuttleRun: null,
    shuttleMap: new Map(),
    shuttleJob: null,
    contactRun: null,
    contactJob: null,
    pendingCandidate: null,
    pendingClassification: null,
    recognitionJob: null,
    shuttleLabeling: false,
  });
  $("workspace").hidden = false;
  $("onboarding").hidden = true;
  $("title").textContent = video.name;
  $("video-info").textContent =
    `${pretty(video.mode)} · ${video.width} × ${video.height} · ${video.fps.toFixed(2).replace(".00", "")} fps · ${clock(video.duration_s)} · ${video.frame_count.toLocaleString()} source frames`;
  $("video").src = `/api/videos/${id}/media`;
  $("stage").style.aspectRatio = `${video.width}/${video.height}`;
  $("overlay").width = video.width;
  $("overlay").height = video.height;
  $("scrubber").max = video.frame_count - 1;
  $("frame-number").max = video.frame_count - 1;
  $("event-frame").max = video.frame_count - 1;
  const initialFrame = video.review_start_frame || 0;
  const calibration = doc.calibrations.find(
    (c) => c.start_frame <= initialFrame && initialFrame < c.end_frame,
  );
  $("court-start").value = calibration?.start_frame ?? 0;
  $("court-end").value = calibration?.end_frame ?? video.frame_count;
  $("save-state").textContent = `Saved · revision ${doc.revision}`;
  $("save").disabled = true;
  $("calibration-hint").hidden = true;
  $("stage").classList.remove("calibrating");
  $("track-status").textContent = "No tracking run loaded";
  $("shuttle-status").textContent = "No shuttle run loaded";
  $("export-json").href = `/api/videos/${id}/export?format=json`;
  $("export-csv").href = `/api/videos/${id}/export?format=csv`;
  $("rally-id").value = "R1";
  renderPlayers();
  resetEditor();
  renderEvents();
  renderCandidates();
  reviewTools.reset();
  recognitionTools.reset();
  draw();
  await loadLibrary();
  if (generation !== state.selectionGeneration) return;
  seek(initialFrame);
  resetEditor();
  notice(
    "Mark events at the current frame. Save edits before exporting or running tracking.",
  );
  await pollJobs();
}
function frameAt(time) {
  let lo = 0,
    hi = state.times.length;
  while (lo < hi) {
    const m = (lo + hi) >> 1;
    if (state.times[m] <= time + 0.00001) lo = m + 1;
    else hi = m;
  }
  return Math.max(0, lo - 1);
}
function updateFrame(frame) {
  state.frame = Math.max(0, Math.min(state.times.length - 1, frame));
  $("scrubber").value = state.frame;
  $("frame-number").value = state.frame;
  $("clock").textContent = clock(state.times[state.frame] || 0);
  reviewTools.frameStatus();
  draw();
}
function showExact() {
  if (!state.video || !$("video").paused) return;
  const index = state.frame;
  const videoId = state.video.id;
  const img = $("exact-frame");
  img.hidden = true;
  img.onload = () => {
    if (
      state.video?.id === videoId &&
      state.frame === index &&
      $("video").paused
    )
      img.hidden = false;
  };
  img.onerror = () => {
    if (state.video?.id === videoId && state.frame === index)
      notice(
        "Could not load the source frame. Check whether the video changed or is unavailable.",
        true,
      );
  };
  img.src = `/api/videos/${state.video.id}/frame?index=${index}`;
}
function seek(frame) {
  if (!state.video) return;
  $("video").pause();
  updateFrame(Math.round(Number(frame) || 0));
  $("video").currentTime = state.times[state.frame];
  showExact();
}
function draw() {
  if (!state.video) return;
  const ctx = $("overlay").getContext("2d"),
    w = ctx.canvas.width,
    h = ctx.canvas.height;
  ctx.clearRect(0, 0, w, h);
  const calibration = state.doc.calibrations.find(
    (c) => c.start_frame <= state.frame && state.frame < c.end_frame,
  );
  const corners = state.corners ?? calibration?.corners;
  if (corners?.length) {
    ctx.strokeStyle = "#b5ef91";
    ctx.fillStyle = "#b5ef9112";
    ctx.lineWidth = 3;
    ctx.beginPath();
    corners.forEach((p, i) =>
      i ? ctx.lineTo(p.x * w, p.y * h) : ctx.moveTo(p.x * w, p.y * h),
    );
    if (corners.length === 4) ctx.closePath();
    ctx.stroke();
    if (corners.length === 4) ctx.fill();
    corners.forEach((p, i) => {
      ctx.beginPath();
      ctx.arc(p.x * w, p.y * h, 6, 0, Math.PI * 2);
      ctx.fillStyle = "#b5ef91";
      ctx.fill();
      ctx.font = "17px Segoe UI";
      ctx.fillText(String(i + 1), p.x * w + 10, p.y * h - 8);
    });
  }
  $("court-status").textContent = calibration
    ? `Calibrated · frames ${calibration.start_frame}–${calibration.end_frame - 1}`
    : "No calibration for this frame";
  drawShuttle(ctx);
  reviewTools.drawPoint(ctx);
  if (!$("show-tracks").checked) return;
  const row = state.runMap.get(state.frame);
  if (!row) return;
  const skeleton = [
    [5, 7],
    [7, 9],
    [6, 8],
    [8, 10],
    [5, 6],
    [5, 11],
    [6, 12],
    [11, 12],
    [11, 13],
    [13, 15],
    [12, 14],
    [14, 16],
  ];
  for (const p of row.players) {
    const [x1, y1, x2, y2] = p.box;
    ctx.strokeStyle = "#d6f9be";
    ctx.lineWidth = 2;
    ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
    ctx.font = "16px Segoe UI";
    const player = reviewTools.playerForTrack(
      state.lastJob,
      p.track_id,
      state.frame,
    );
    const label = `${player ? `Player ${player} · ` : ""}Track ${p.track_id ?? "?"} · ${Math.round(p.confidence * 100)}%`;
    ctx.fillStyle = "#14231cdd";
    ctx.fillRect(
      x1,
      Math.max(0, y1 - 24),
      ctx.measureText(label).width + 10,
      24,
    );
    ctx.fillStyle = "#d6f9be";
    ctx.fillText(label, x1 + 5, Math.max(18, y1 - 6));
    for (const [a, b] of skeleton) {
      const pa = p.keypoints[a],
        pb = p.keypoints[b];
      if (pa?.[2] > 0.35 && pb?.[2] > 0.35) {
        ctx.beginPath();
        ctx.moveTo(pa[0], pa[1]);
        ctx.lineTo(pb[0], pb[1]);
        ctx.stroke();
      }
    }
  }
}
function drawShuttle(ctx) {
  if (!$("show-shuttle").checked) return;
  ctx.strokeStyle = "#ffd379";
  ctx.fillStyle = "#ffd379";
  ctx.lineWidth = 2;
  ctx.beginPath();
  let connected = false;
  for (let frame = state.frame - 12; frame <= state.frame; frame++) {
    const point = state.shuttleMap.get(frame)?.shuttle;
    if (!point?.visible) {
      connected = false;
      continue;
    }
    if (connected) ctx.lineTo(point.x, point.y);
    else ctx.moveTo(point.x, point.y);
    connected = true;
  }
  ctx.stroke();
  const point = state.shuttleMap.get(state.frame)?.shuttle;
  if (point?.visible) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#182227";
    ctx.stroke();
  }
}
function renderCandidates() {
  const candidates = state.contactRun?.candidates || [];
  $("candidate-count").textContent = candidates.length;
  $("candidates").innerHTML = candidates.length
    ? candidates
        .map((c) => {
          const added = state.doc.events.some(
            (e) =>
              e.source_run_id === state.contactJob && e.candidate_id === c.id,
          );
          const player = reviewTools.playerForTrack(
            state.contactRun.player_run_id,
            c.track_id,
            c.frame,
          );
          const uncertain = c.timing === "uncertain_interval";
          return `<button class="candidate-row" data-candidate="${escape(c.id)}" ${added ? "disabled" : ""}><time>${clock(c.time_s)}</time><span>${added ? "Added" : uncertain ? "Review possible contact" : "Review contact"}<small>${uncertain ? `Frames ${c.start_frame}–${c.end_frame} · ` : ""}${player ? `Player ${escape(player)} · ` : ""}${c.track_id === null ? "Hitter unconfirmed" : `Track ${escape(c.track_id)}${player ? "" : " · identity unconfirmed"}`} · score ${c.score.toFixed(2)}</small></span></button>`;
        })
        .join("")
    : '<p class="empty">Track the shuttle, then suggest contacts.</p>';
  document.querySelectorAll("[data-candidate]").forEach(
    (button) =>
      (button.onclick = () => {
        const candidate = candidates.find(
          (c) => c.id === button.dataset.candidate,
        );
        resetEditor("shot");
        state.pendingCandidate = { id: candidate.id, run_id: state.contactJob };
        $("event-frame").value = candidate.frame;
        if (candidate.timing === "uncertain_interval") {
          $("contact-start").value = candidate.start_frame;
          $("contact-end").value = candidate.end_frame;
          $("contact-uncertainty").open = true;
        }
        $("event-player").value =
          reviewTools.playerForTrack(
            state.contactRun.player_run_id,
            candidate.track_id,
            candidate.frame,
          ) || "";
        $("event-notes").value =
          `Contact suggestion: ${candidate.reason}. Verify contact, hitter, and stroke.`;
        $("editor-hint").textContent =
          candidate.timing === "uncertain_interval"
            ? `Possible contact · frames ${candidate.start_frame}–${candidate.end_frame}. Navigation frame ${candidate.frame} is an estimate.`
            : `Suggested contact · frame ${candidate.frame} · verify before adding`;
        seek(candidate.frame);
        notice(
          "Review the source frames, choose the hitter and stroke labels, then add the event.",
        );
      }),
  );
}
function renderPlayers() {
  const options =
    '<option value="">Unknown hitter</option>' +
    state.doc.players
      .map(
        (p) =>
          `<option value="${escape(p.id)}">${escape(p.name)} (${escape(p.id)})</option>`,
      )
      .join("");
  const previous = $("event-player").value;
  $("event-player").innerHTML = options;
  $("event-player").value = previous;
  $("players").innerHTML = state.doc.players
    .map(
      (p) =>
        `<div class="player-row"><strong>${escape(p.id)}</strong><input data-player="${escape(p.id)}" data-field="name" value="${escape(p.name)}" aria-label="Player ${escape(p.id)} name" maxlength="100"><select data-player="${escape(p.id)}" data-field="team" aria-label="Player ${escape(p.id)} team"><option ${p.team === "T1" ? "selected" : ""}>T1</option><option ${p.team === "T2" ? "selected" : ""}>T2</option></select><select data-player="${escape(p.id)}" data-field="handedness" aria-label="Player ${escape(p.id)} handedness">${["unknown", "right", "left"].map((v) => `<option value="${v}" ${p.handedness === v ? "selected" : ""}>${pretty(v)}</option>`).join("")}</select></div>`,
    )
    .join("");
  document.querySelectorAll("[data-player]").forEach(
    (el) =>
      (el.onchange = () => {
        state.doc.players.find((p) => p.id === el.dataset.player)[
          el.dataset.field
        ] = el.value;
        changed();
        const hitter = $("event-player").value;
        renderPlayers();
        $("event-player").value = hitter;
        renderEvents();
      }),
  );
}
function renderEvents() {
  const filter = $("filter-rally").value;
  const rallies = [...new Set(state.doc.events.map((e) => e.rally_id))];
  $("filter-rally").innerHTML =
    '<option value="">All rallies</option>' +
    rallies
      .map((r) => `<option value="${escape(r)}">${escape(r)}</option>`)
      .join("");
  $("filter-rally").value = rallies.includes(filter) ? filter : "";
  const events = [...state.doc.events]
    .sort((a, b) => a.frame - b.frame)
    .filter(
      (e) => !$("filter-rally").value || e.rally_id === $("filter-rally").value,
    );
  $("event-count").textContent = `${state.doc.events.length} events`;
  $("events").innerHTML = events.length
    ? events
        .map((e) => {
          const player = state.doc.players.find((p) => p.id === e.player_id);
          return `<button class="event-row ${state.selected === e.id ? "active" : ""}" data-event="${escape(e.id)}"><span class="event-dot ${e.kind}"></span><time>${clock(state.times[e.frame] || 0)}</time><span class="event-text">${escape(e.kind === "shot" ? pretty(e.family) : pretty(e.kind))}<small>${escape(e.rally_id)} · ${escape(player?.name || "—")}${e.side ? " · " + escape(pretty(e.side)) : ""}${e.contact_start_frame != null && e.contact_start_frame < e.contact_end_frame ? ` · timing ${e.contact_start_frame}–${e.contact_end_frame}` : ""}</small></span></button>`;
        })
        .join("")
    : '<p class="empty">No events yet. Mark the serve to begin a rally.</p>';
  $("event-markers").innerHTML = state.doc.events
    .map(
      (e) =>
        `<button class="${e.kind}" style="left:${Math.min(99.5, (e.frame / (state.video.frame_count - 1)) * 100)}%" title="${escape(pretty(e.kind))} · ${clock(state.times[e.frame])}" data-jump="${escape(e.id)}"></button>`,
    )
    .join("");
  document
    .querySelectorAll("[data-event],[data-jump]")
    .forEach(
      (b) => (b.onclick = () => editEvent(b.dataset.event || b.dataset.jump)),
    );
}
function kindFields() {
  const kind = $("event-kind").value;
  $("family-label").hidden = kind !== "shot";
  $("side-label").hidden = kind === "rally_end";
  $("player-label").hidden = kind === "rally_end";
  $("contact-uncertainty").hidden = kind === "rally_end";
}
function resetEditor(kind = "shot") {
  state.pendingClassification = null;
  state.pendingCandidate = null;
  state.selected = null;
  $("event-kind").value = kind;
  $("event-frame").value = state.frame;
  $("event-family").value = "unknown";
  $("event-side").value = "unknown";
  $("event-notes").value = "";
  $("contact-start").value = "";
  $("contact-end").value = "";
  $("contact-uncertainty").open = false;
  $("apply-event").textContent = "Add event";
  $("delete-event").hidden = true;
  $("editor-hint").textContent =
    `New ${pretty(kind)} at the current source frame.`;
  kindFields();
}
function mark(kind) {
  if (!state.video) return;
  seek(state.frame);
  resetEditor(kind);
  renderEvents();
  $("event-family").focus();
  notice(
    `Choose the ${kind === "shot" ? "shot family and stroke side" : "event details"}, then add the event.`,
  );
}
function editEvent(id) {
  state.pendingClassification = null;
  state.pendingCandidate = null;
  const e = state.doc.events.find((e) => e.id === id);
  if (!e) return;
  state.selected = id;
  $("rally-id").value = e.rally_id;
  $("event-kind").value = e.kind;
  $("event-frame").value = e.frame;
  $("event-player").value = e.player_id || "";
  $("event-family").value = e.family || "unknown";
  $("event-side").value = e.side || "unknown";
  $("event-notes").value = e.notes;
  $("contact-start").value = e.contact_start_frame ?? "";
  $("contact-end").value = e.contact_end_frame ?? "";
  $("contact-uncertainty").open = e.contact_start_frame != null;
  $("apply-event").textContent = "Update event";
  $("delete-event").hidden = false;
  $("editor-hint").textContent = `Editing ${pretty(e.kind)} · frame ${e.frame}`;
  kindFields();
  seek(e.frame);
  renderEvents();
}
async function save() {
  if (!state.dirty || state.saving) return;
  const videoId = state.video.id;
  const editVersion = state.editVersion;
  state.saving = true;
  try {
    const saved = await api(`/api/videos/${videoId}/annotations`, {
      method: "PUT",
      body: JSON.stringify(state.doc),
    });
    if (state.video?.id !== videoId) return;
    if (state.editVersion !== editVersion) {
      state.doc.revision = saved.revision;
      notice("Earlier edits saved. Save again to keep your newest changes.");
      return;
    }
    state.doc = saved;
    state.dirty = false;
    $("save").disabled = true;
    $("save-state").textContent = `Saved · revision ${saved.revision}`;
    notice("Annotations saved. JSON and CSV exports include this revision.");
    renderEvents();
  } finally {
    state.saving = false;
  }
}
async function pollJobs() {
  const jobs = await api("/api/jobs");
  state.jobs = jobs;
  const active = jobs.find((j) => ["queued", "running"].includes(j.status));
  $("track").disabled = !!active;
  $("track-shuttle").disabled = !!active;
  $("detect-contacts").disabled = !!active || !state.shuttleRun;
  importTools.updateJobs(jobs);
  if (active) {
    if (active.kind === "players" && active.video_id === state.video?.id)
      $("track-status").textContent =
        `Tracking · ${Math.round(active.progress * 100)}%`;
    else if (active.kind === "shuttle" && active.video_id === state.video?.id)
      $("shuttle-status").textContent =
        `Tracking shuttle · ${Math.round(active.progress * 100)}%`;
    else if (active.kind === "contacts" && active.video_id === state.video?.id)
      $("shuttle-status").textContent = "Finding contact suggestions";
    else if (active.kind === "import")
      notice(`Inspecting video · ${Math.round(active.progress * 100)}%`);
  }
  const imports = jobs.filter(
    (j) => j.kind === "import" && j.status === "completed",
  );
  if (imports.length && imports[0].id !== state.importJob) {
    state.importJob = imports[0].id;
    await loadLibrary();
  }
  if (!state.video) return;
  const latest = jobs.find((j) => j.video_id === state.video.id);
  if (latest?.status === "failed") {
    $(
      latest.kind === "players" ? "track-status" : "shuttle-status",
    ).textContent = latest.message;
  }
  const done = jobs.find(
    (j) =>
      j.video_id === state.video.id &&
      j.kind === "players" &&
      j.status === "completed",
  );
  if (done && done.id !== state.lastJob) {
    const videoId = state.video.id;
    const generation = state.selectionGeneration;
    const run = await api(`/api/videos/${videoId}/runs/${done.id}`);
    if (state.video?.id !== videoId || generation !== state.selectionGeneration)
      return;
    state.lastJob = done.id;
    state.run = run;
    state.runMap = new Map(state.run.frames.map((f) => [f.frame, f]));
    reviewTools.render();
    $("track-status").textContent =
      `${state.run.processed_frames} frames · ${state.run.inference_fps} fps · ${state.run.device}${state.run.calibrated ? " · court filter" : " · no court filter"}`;
    draw();
  }
  const shuttle = jobs.find(
    (j) =>
      j.video_id === state.video.id &&
      j.kind === "shuttle" &&
      j.status === "completed",
  );
  if (shuttle && shuttle.id !== state.shuttleJob) {
    const generation = state.selectionGeneration,
      videoId = state.video.id;
    const run = await api(`/api/videos/${videoId}/runs/${shuttle.id}`);
    if (generation !== state.selectionGeneration) return;
    state.shuttleRun = run;
    state.shuttleJob = shuttle.id;
    state.shuttleMap = new Map(run.frames.map((f) => [f.frame, f]));
    state.contactRun = null;
    state.contactJob = null;
    renderCandidates();
    $("shuttle-status").textContent =
      `${run.visible_frames}/${run.processed_frames} frames visible · ${run.inference_fps} fps · raw detections`;
    draw();
  }
  const contacts = jobs.find(
    (j) =>
      j.video_id === state.video.id &&
      j.kind === "contacts" &&
      j.status === "completed" &&
      j.summary?.shuttle_run_id === state.shuttleJob,
  );
  if (contacts && contacts.id !== state.contactJob) {
    const generation = state.selectionGeneration,
      videoId = state.video.id;
    const run = await api(`/api/videos/${videoId}/runs/${contacts.id}`);
    if (generation !== state.selectionGeneration) return;
    state.contactRun = run;
    state.contactJob = contacts.id;
    renderCandidates();
  }
  $("detect-contacts").disabled = !!active || !state.shuttleRun;
  await recognitionTools.refresh(jobs, active);
}
$("event-form").onsubmit = (e) => {
  e.preventDefault();
  const kind = $("event-kind").value,
    frame = Number($("event-frame").value),
    rally = $("rally-id").value.trim();
  if (
    !rally ||
    !Number.isInteger(frame) ||
    frame < 0 ||
    frame >= state.times.length
  ) {
    notice("Enter a rally and a source frame inside the video.", true);
    return;
  }
  const existing = state.doc.events.find((e) => e.id === state.selected);
  const contactStart =
    $("contact-start").value === "" || kind === "rally_end"
      ? null
      : Number($("contact-start").value);
  const contactEnd =
    $("contact-end").value === "" || kind === "rally_end"
      ? null
      : Number($("contact-end").value);
  if (
    (contactStart === null) !== (contactEnd === null) ||
    (contactStart !== null &&
      (!Number.isInteger(contactStart) ||
        !Number.isInteger(contactEnd) ||
        contactStart < 0 ||
        contactEnd >= state.times.length ||
        contactStart > frame ||
        contactEnd < frame))
  ) {
    notice(
      "Enter both contact bounds, including the event frame, or clear the interval for exact timing.",
      true,
    );
    return;
  }
  const event = {
    id: state.selected || crypto.randomUUID(),
    rally_id: rally,
    kind,
    frame,
    time_s: state.times[frame],
    player_id: kind === "rally_end" ? null : $("event-player").value || null,
    family: kind === "shot" ? $("event-family").value : null,
    side: kind === "rally_end" ? null : $("event-side").value,
    status: ["predicted", "corrected"].includes(existing?.status)
      ? "corrected"
      : "reviewed",
    confidence: existing?.confidence ?? null,
    notes: $("event-notes").value,
    source_run_id:
      existing?.source_run_id ?? state.pendingCandidate?.run_id ?? null,
    candidate_id: existing?.candidate_id ?? state.pendingCandidate?.id ?? null,
    classification_run_id:
      kind === "rally_end"
        ? null
        : (state.pendingClassification?.run_id ??
          existing?.classification_run_id ??
          null),
    classification_candidate_id:
      kind === "rally_end"
        ? null
        : (state.pendingClassification?.id ??
          existing?.classification_candidate_id ??
          null),
    family_score:
      kind === "rally_end"
        ? null
        : state.pendingClassification
          ? frame === state.pendingClassification.frame &&
            kind === state.pendingClassification.kind &&
            (kind !== "shot" ||
              $("event-family").value === state.pendingClassification.family)
            ? (state.pendingClassification.score ?? null)
            : null
          : existing?.frame === frame &&
              existing?.kind === kind &&
              existing?.family ===
                (kind === "shot" ? $("event-family").value : null)
            ? (existing?.family_score ?? null)
            : null,
    contact_start_frame: contactStart,
    contact_end_frame: contactEnd,
  };
  state.doc.events = state.doc.events.filter((e) => e.id !== event.id);
  state.doc.events.push(event);
  changed();
  editEvent(event.id);
  renderCandidates();
  notice("Event updated locally. Save annotations to keep your edits.");
};
$("delete-event").onclick = () => {
  state.doc.events = state.doc.events.filter((e) => e.id !== state.selected);
  changed();
  resetEditor();
  renderEvents();
  renderCandidates();
};
$("new-event").onclick = () => {
  resetEditor();
  renderEvents();
};
$("event-kind").onchange = kindFields;
$("clear-contact-interval").onclick = () => {
  $("contact-start").value = "";
  $("contact-end").value = "";
  notice(
    "Contact timing set to the event frame. Update the event to keep this change.",
  );
};
$("filter-rally").onchange = renderEvents;
$("save").onclick = () => save().catch(handleError);
$("play").onclick = () => {
  const v = $("video");
  if (v.paused) {
    $("exact-frame").hidden = true;
    v.play().catch(handleError);
  } else {
    v.pause();
    showExact();
  }
};
$("video").onplay = () => {
  $("play").textContent = "Ⅱ Pause";
  $("exact-frame").hidden = true;
};
$("video").onpause = () => {
  $("play").textContent = "▶ Play";
  updateFrame(frameAt($("video").currentTime));
  showExact();
};
$("video").ontimeupdate = () => {
  if (!$("video").paused) updateFrame(frameAt($("video").currentTime));
};
$("video").onerror = () => {
  if (state.video)
    notice(
      "Video playback could not load. Check the source file or try exact-frame review.",
      true,
    );
};
$("video").onseeked = () => {
  if ($("video").paused) showExact();
};
$("speed").onchange = () =>
  ($("video").playbackRate = Number($("speed").value));
$("back-frame").onclick = () => seek(state.frame - 1);
$("next-frame").onclick = () => seek(state.frame + 1);
$("scrubber").oninput = () => seek($("scrubber").value);
$("frame-number").onchange = () => seek($("frame-number").value);
$("show-tracks").onchange = draw;
$("show-shuttle").onchange = draw;
document
  .querySelectorAll("[data-mark]")
  .forEach((b) => (b.onclick = () => mark(b.dataset.mark)));
$("audit").onclick = () =>
  window.open(
    `/api/videos/${state.video.id}/image/contact-sheet.jpg`,
    "_blank",
    "noopener",
  );
$("calibrate").onclick = () => {
  state.shuttleLabeling = false;
  reviewTools.frameStatus();
  if (state.corners) {
    state.corners = null;
    $("calibrate").textContent = "Select 4 corners";
    $("stage").classList.remove("calibrating");
    $("calibration-hint").hidden = true;
    draw();
    return;
  }
  seek(state.frame);
  state.corners = [];
  $("calibrate").textContent = "Cancel selection";
  $("stage").classList.add("calibrating");
  $("calibration-hint").hidden = false;
  $("calibration-hint").textContent = "1 / 4 · Far left corner";
  draw();
};
$("overlay").onclick = (e) => {
  if (reviewTools.capturePoint(e)) return;
  if (!state.corners) return;
  const rect = $("overlay").getBoundingClientRect();
  state.corners.push({
    x: (e.clientX - rect.left) / rect.width,
    y: (e.clientY - rect.top) / rect.height,
  });
  draw();
  if (state.corners.length === 4) {
    const start = Number($("court-start").value),
      end = Number($("court-end").value);
    if (
      !Number.isInteger(start) ||
      !Number.isInteger(end) ||
      start < 0 ||
      end > state.times.length ||
      end <= start
    ) {
      state.corners = [];
      notice(
        "Enter a valid calibration frame range and select the corners again.",
        true,
      );
      return;
    }
    state.doc.calibrations = state.doc.calibrations.filter(
      (c) => c.start_frame !== start || c.end_frame !== end,
    );
    state.doc.calibrations.push({
      start_frame: start,
      end_frame: end,
      corners: state.corners,
    });
    state.corners = null;
    $("stage").classList.remove("calibrating");
    $("calibration-hint").hidden = true;
    $("calibrate").textContent = "Select 4 corners";
    changed();
    notice(
      "Court corners added. Save annotations to validate the calibration.",
    );
    draw();
  } else
    $("calibration-hint").textContent =
      `${state.corners.length + 1} / 4 · ${["Far left", "Far right", "Near right", "Near left"][state.corners.length]} corner`;
};
$("clear-court").onclick = () => {
  const start = Number($("court-start").value),
    end = Number($("court-end").value);
  state.doc.calibrations = state.doc.calibrations.filter(
    (c) => c.start_frame !== start || c.end_frame !== end,
  );
  changed();
  draw();
};
async function startTracking(stage) {
  try {
    if (state.dirty) {
      notice("Save your annotations before running tracking.", true);
      return;
    }
    await api(`/api/videos/${state.video.id}/track`, {
      method: "POST",
      body: JSON.stringify({
        start_frame: state.frame,
        end_frame: Math.min(
          state.times.length,
          frameAt(
            state.times[state.frame] +
              Number($("track-duration").value) -
              0.00001,
          ) + 1,
        ),
        stride: 1,
        stage,
      }),
    });
    $(stage === "players" ? "track-status" : "shuttle-status").textContent =
      "Tracking queued";
    await pollJobs();
  } catch (e) {
    handleError(e);
  }
}
$("track").onclick = () => startTracking("players");
$("track-shuttle").onclick = () => startTracking("shuttle");
$("detect-contacts").onclick = async () => {
  try {
    if (state.dirty) {
      notice("Save annotations before requesting contact suggestions.", true);
      return;
    }
    const s = state.shuttleRun;
    const playerJob = state.jobs.find(
      (j) =>
        j.video_id === state.video.id &&
        j.kind === "players" &&
        j.status === "completed" &&
        j.summary?.start_frame <= s.start_frame &&
        j.summary?.end_frame >= s.end_frame,
    );
    await api(`/api/videos/${state.video.id}/contacts`, {
      method: "POST",
      body: JSON.stringify({
        shuttle_run_id: state.shuttleJob,
        player_run_id: playerJob?.id ?? null,
      }),
    });
    notice(
      "Finding contact suggestions. Review them before adding shot events.",
    );
    await pollJobs();
  } catch (e) {
    handleError(e);
  }
};
for (const id of ["export-json", "export-csv"])
  $(id).onclick = (e) => {
    if (state.dirty) {
      e.preventDefault();
      notice("Save annotations before exporting.", true);
    }
  };
window.addEventListener("beforeunload", (e) => {
  if (state.dirty) {
    e.preventDefault();
    e.returnValue = "";
  }
});
window.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    save().catch(handleError);
    return;
  }
  if (
    !state.video ||
    ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)
  )
    return;
  if (e.key === "ArrowLeft") {
    e.preventDefault();
    seek(state.frame - 1);
  }
  if (e.key === "ArrowRight") {
    e.preventDefault();
    seek(state.frame + 1);
  }
  if (e.code === "Space") {
    e.preventDefault();
    $("play").click();
  }
  if (["1", "2", "3"].includes(e.key))
    mark({ 1: "serve", 2: "shot", 3: "rally_end" }[e.key]);
});
const reviewTools = createReviewTools({
  state,
  $,
  changed,
  draw,
  seek,
  api,
  notice,
  escape,
  renderCandidates,
});
const importTools = createImportTools({
  $,
  api,
  notice,
  pollJobs,
  loadLibrary,
});
const recognitionTools = createRecognitionTools({
  state,
  $,
  api,
  notice,
  escape,
  resetEditor,
  editEvent,
  seek,
  kindFields,
});
await loadLibrary().catch(handleError);
if (state.videos.length)
  await selectVideo(state.videos[0].id).catch(handleError);
setInterval(() => pollJobs().catch(handleError), 2000);
