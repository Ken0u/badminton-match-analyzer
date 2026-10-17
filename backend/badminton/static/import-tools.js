export function createImportTools({ $, api, notice, pollJobs, loadLibrary }) {
  $("choose-upload").onclick = () => {
    document.querySelector(".import-panel").open = true;
    $("upload-file").click();
  };
  $("choose-youtube").onclick = () => {
    document.querySelector(".import-panel").open = true;
    $("youtube-url").focus();
    $("youtube-url").scrollIntoView({ block: "center", behavior: "smooth" });
  };
  let sending = false;
  let pendingJob = null;
  let active = false;
  const controls = () => document.querySelectorAll(".import-panel form button");
  function updateControls() {
    controls().forEach((button) => (button.disabled = sending || active));
  }
  function status(message, error = false) {
    $("import-status").textContent = message;
    $("import-status").classList.toggle("error", error);
  }
  function updateJobs(jobs) {
    active = jobs.some((j) => ["queued", "running"].includes(j.status));
    updateControls();
    const job = jobs.find((j) => j.id === pendingJob);
    if (!job) return;
    if (job.status === "completed") {
      pendingJob = null;
      status(
        `Ready: ${job.summary?.name ?? "match imported"}. Choose it in the library.`,
      );
      notice("Your match is ready in the video library.");
      loadLibrary().catch((e) => notice(e.message, true));
    } else if (["failed", "interrupted"].includes(job.status)) {
      pendingJob = null;
      status(job.message, true);
      notice(job.message, true);
    } else status(`Preparing match · ${Math.round(job.progress * 100)}%`);
  }
  async function submit(action) {
    sending = true;
    updateControls();
    try {
      const job = await action();
      pendingJob = job.id;
      status("Preparing your match…");
      await pollJobs();
    } catch (e) {
      status(e.message, true);
      notice(e.message, true);
    } finally {
      sending = false;
      updateControls();
      $("upload-progress").hidden = true;
    }
  }
  $("upload-form").onsubmit = (e) => {
    e.preventDefault();
    const file = $("upload-file").files[0];
    if (!file || sending || active) return;
    submit(
      () =>
        new Promise((resolve, reject) => {
          const body = new FormData();
          body.append("file", file);
          body.append("mode", $("upload-mode").value);
          const request = new XMLHttpRequest();
          request.open("POST", "/api/upload");
          $("upload-progress").value = 0;
          $("upload-progress").hidden = false;
          status(`Uploading ${file.name}…`);
          request.upload.onprogress = (event) => {
            if (event.lengthComputable) {
              const percent = Math.round((event.loaded / event.total) * 100);
              $("upload-progress").value = percent;
              status(
                percent === 100
                  ? "Checking uploaded video…"
                  : `Uploading · ${percent}%`,
              );
            }
          };
          request.onerror = () =>
            reject(
              Error("Upload interrupted. Check the connection and retry."),
            );
          request.onabort = () => reject(Error("Upload was cancelled."));
          request.onload = () => {
            let result;
            try {
              result = JSON.parse(request.responseText);
            } catch {
              result = null;
            }
            if (request.status < 200 || request.status >= 300)
              reject(
                Error(
                  typeof result?.detail === "string"
                    ? result.detail
                    : request.responseText ||
                        `Upload failed (${request.status})`,
                ),
              );
            else resolve(result);
          };
          request.send(body);
        }),
    );
  };
  $("youtube-form").onsubmit = (e) => {
    e.preventDefault();
    if (sending || active) return;
    submit(() =>
      api("/api/import/youtube", {
        method: "POST",
        body: JSON.stringify({
          url: $("youtube-url").value.trim(),
          mode: $("youtube-mode").value,
        }),
      }),
    );
  };
  $("import-form").onsubmit = (e) => {
    e.preventDefault();
    if (sending || active) return;
    submit(() =>
      api("/api/import", {
        method: "POST",
        body: JSON.stringify({
          path: $("import-path").value,
          mode: $("import-mode").value,
        }),
      }),
    );
  };
  return { updateJobs };
}
