export function createSegmentTools({
  state,
  $,
  api,
  notice,
  seek,
  escape,
  clock,
}) {
  let loaded = null;
  function reset() {
    loaded = null;
    $("segment-status").textContent =
      "Scan camera changes across the full video.";
    $("camera-boundaries").innerHTML = "";
    delete $("camera-boundaries").dataset.runId;
    $("scan-segments").disabled = true;
  }
  $("scan-segments").onclick = async () => {
    try {
      const id = state.video?.id;
      if (!id) return;
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
    if (latest?.status === "failed") {
      $("segment-status").textContent = latest.message;
    }
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
    $("camera-boundaries").dataset.runId = done.id;
    $("segment-status").textContent =
      `${run.boundaries.length} possible boundaries · live/replay status unknown`;
    $("camera-boundaries").innerHTML = run.boundaries.length
      ? run.boundaries
          .map(
            (b) =>
              `<button type="button" class="quiet" data-boundary="${b.frame}">${clock(b.time_s)} · frame ${b.frame} · ${escape(b.reason.replaceAll("_", " "))}</button>`,
          )
          .join("")
      : '<p class="empty">No abrupt boundary found. Continuous camera motion or gradual transitions may still be present.</p>';
    $("camera-boundaries")
      .querySelectorAll("[data-boundary]")
      .forEach((button) => {
        button.onclick = () => {
          seek(Number(button.dataset.boundary));
          notice(
            "Possible camera boundary. Step back and forward to inspect it; this is not a rally boundary.",
          );
        };
      });
  }
  return { refresh, reset };
}
