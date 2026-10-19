export function createPlaybackTools({ $, state, api, seek, onReady }) {
  let generation = 0,
    preparedUrl = null,
    finishedJob = null,
    busy = false,
    metadataListener = null,
    readyListener = null;
  const button = $("prepare-playback"),
    status = $("playback-status"),
    video = $("video");

  function reset() {
    generation += 1;
    preparedUrl = null;
    finishedJob = null;
    busy = false;
    if (metadataListener)
      video.removeEventListener("loadedmetadata", metadataListener);
    metadataListener = null;
    if (readyListener) video.removeEventListener("canplay", readyListener);
    readyListener = null;
    delete video.dataset.switching;
    button.disabled = true;
    button.textContent = "Prepare playback";
    status.textContent = "";
  }
  function usePrepared() {
    if (!preparedUrl) return;
    if (video.currentSrc.endsWith(preparedUrl) && !video.dataset.switching) {
      status.textContent = "Prepared playback · source frame timing preserved";
      button.textContent = "Playback ready";
      button.disabled = true;
      if (video.readyState >= 2 && !video.error) onReady();
      return;
    }
    if (metadataListener)
      video.removeEventListener("loadedmetadata", metadataListener);
    if (readyListener) video.removeEventListener("canplay", readyListener);
    const current = generation,
      url = preparedUrl;
    video.dataset.switching = "true";
    video.pause();
    button.disabled = true;
    status.textContent = "Loading prepared playback…";
    metadataListener = () => {
      if (current !== generation || !video.currentSrc.endsWith(url)) return;
      video.removeEventListener("loadedmetadata", metadataListener);
      metadataListener = null;
      delete video.dataset.switching;
      seek(state.frame);
      status.textContent = "Prepared playback · source frame timing preserved";
      button.textContent = "Playback ready";
    };
    video.addEventListener("loadedmetadata", metadataListener);
    readyListener = () => {
      if (
        current !== generation ||
        !video.currentSrc.endsWith(url) ||
        video.readyState < 2 ||
        video.error
      )
        return;
      video.removeEventListener("canplay", readyListener);
      readyListener = null;
      onReady();
    };
    video.addEventListener("canplay", readyListener);
    video.src = url;
  }
  async function refresh(current) {
    const result = await api(`/api/videos/${state.video.id}/playback`);
    if (current !== generation) return;
    preparedUrl = result.url;
    button.disabled = busy;
    if (preparedUrl) {
      button.textContent = "Use prepared playback";
      status.textContent = "Prepared playback is ready";
      if (video.paused) usePrepared();
    } else {
      button.textContent = "Prepare playback";
      status.textContent =
        "Video not playing smoothly? Prepare a compatible copy.";
    }
  }
  async function load() {
    const current = generation;
    try {
      await refresh(current);
    } catch (error) {
      if (current === generation) {
        button.disabled = false;
        status.textContent = error.message;
      }
    }
  }
  button.onclick = async () => {
    if (preparedUrl) {
      usePrepared();
      return;
    }
    const current = generation;
    busy = true;
    button.disabled = true;
    status.textContent =
      "Preparing playback… Exact-frame review remains available.";
    try {
      await api(`/api/videos/${state.video.id}/playback`, { method: "POST" });
    } catch (error) {
      if (current === generation) {
        busy = false;
        button.disabled = false;
        status.textContent = error.message;
      }
    }
  };
  async function updateJobs(jobs) {
    if (!state.video) return;
    const current = generation,
      job = jobs.find(
        (j) => j.kind === "playback" && j.video_id === state.video.id,
      );
    if (!job) return;
    if (["queued", "running"].includes(job.status)) {
      busy = true;
      button.disabled = true;
      status.textContent = `Preparing playback · ${Math.round(job.progress * 100)}%`;
    } else if (job.id !== finishedJob) {
      finishedJob = job.id;
      busy = false;
      if (job.status === "completed") await load();
      else if (current === generation) {
        button.disabled = false;
        status.textContent = `Playback preparation stopped: ${job.message}. You can retry.`;
      }
    }
  }
  function mediaError() {
    if (metadataListener)
      video.removeEventListener("loadedmetadata", metadataListener);
    metadataListener = null;
    if (readyListener) video.removeEventListener("canplay", readyListener);
    readyListener = null;
    delete video.dataset.switching;
    button.disabled = busy;
  }
  return { reset, load, updateJobs, mediaError };
}
