import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:8002";
assert.equal(
  new URL(base).port,
  "8002",
  "Import fixtures must use isolated port 8002.",
);
const fixtures = JSON.parse(
  await fs.readFile(
    new URL(
      "../.cache/import-ui-test-data/current-fixtures.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
assert.equal(fixtures.port, 8002);
const output = new URL("../data/processed/qa/", import.meta.url);
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));

async function api(path, options) {
  const response = await page.request.fetch(`${base}${path}`, options);
  assert.ok(
    response.ok(),
    `${path}: ${response.status()} ${await response.text()}`,
  );
  return response.json();
}

async function ready(count, title) {
  await page.waitForFunction(
    ({ count, title }) => {
      const status = document.querySelector("#import-status").textContent;
      return (
        document.querySelectorAll("#library .library-item").length === count &&
        status.startsWith("Ready:") &&
        status.includes(title)
      );
    },
    { count, title },
  );
}

async function exactFrame(frame) {
  await page.locator("#frame-number").fill(String(frame));
  await page.locator("#frame-number").dispatchEvent("change");
  await page.waitForFunction((frame) => {
    const image = document.querySelector("#exact-frame");
    return (
      image.src.endsWith(`index=${frame}`) &&
      !image.hidden &&
      image.complete &&
      image.naturalWidth === 32
    );
  }, frame);
}

try {
  assert.deepEqual(
    await api("/api/videos"),
    [],
    "Start a fresh scripts/import_ui_test_server.py before running.",
  );
  await page.goto(base);
  assert.equal(await page.locator("#onboarding").isVisible(), true);
  await page.locator("#choose-youtube").click();
  await page.waitForFunction(() => document.activeElement.id === "youtube-url");
  await page.screenshot({
    path: fileURLToPath(new URL("import-empty.png", output)),
    fullPage: true,
  });
  assert.equal(await page.locator("#workspace").isHidden(), true);
  assert.equal(await page.locator("#library-count").textContent(), "0");
  const statusLog = [];
  await page.exposeFunction("recordImportStatus", (text) =>
    statusLog.push(text),
  );
  await page.evaluate(() => {
    const status = document.querySelector("#import-status");
    new MutationObserver(() =>
      window.recordImportStatus(status.textContent),
    ).observe(status, { childList: true, subtree: true });
  });

  // Pause the real upload request briefly to verify its visible progress state.
  let releaseUpload;
  const uploadGate = new Promise((resolve) => {
    releaseUpload = resolve;
  });
  await page.route("**/api/upload", async (route) => {
    await uploadGate;
    await route.continue();
  });
  await page.locator("#upload-file").setInputFiles(fixtures.upload);
  await page.locator("#upload-form button[type=submit]").click();
  await page.waitForFunction(
    () => !document.querySelector("#upload-progress").hidden,
  );
  assert.equal(await page.locator("#upload-form button").isDisabled(), true);
  assert.match(
    await page.locator("#import-status").textContent(),
    /Uploading|Checking/,
  );
  releaseUpload();
  await ready(1, "upload-fixture.mp4");
  await page.unroute("**/api/upload");
  await page.getByRole("button", { name: /upload-fixture.mp4/ }).click();
  await page.waitForFunction(
    () => document.querySelector("#video").readyState >= 2,
  );
  await exactFrame(2);
  assert.equal(
    await page.locator("#title").textContent(),
    "upload-fixture.mp4",
  );
  assert.equal(
    await page.locator("#video").evaluate((video) => video.error),
    null,
  );
  const firstVideo = (await api("/api/videos"))[0];
  assert.equal(firstVideo.source_type, "upload");
  assert.equal(firstVideo.width, 32);

  // Preserve one explicitly synthetic QA event across a duplicate source import.
  await page.locator('[data-mark="shot"]').click();
  await page
    .locator("#event-notes")
    .fill("QA synthetic event for duplicate import persistence.");
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  let firstDocument = await api(`/api/videos/${firstVideo.id}/annotations`);
  assert.equal(firstDocument.events.length, 1);
  // Terminal timing is separate from a racket contact, including in exports.
  await page.locator('[data-mark="rally_end"]').click();
  await page.locator("#event-frame").fill("30");
  await page.locator("#contact-uncertainty summary").click();
  assert.match(
    await page.locator("#timing-uncertainty-title").textContent(),
    /Rally end/,
  );
  await page.locator("#contact-start").fill("28");
  await page.locator("#apply-event").click();
  assert.match(
    await page.locator("#notice").textContent(),
    /both timing bounds/,
  );
  assert.equal(await page.locator("#event-count").textContent(), "1 events");
  await page.locator("#contact-end").fill("35");
  await page
    .locator("#event-notes")
    .fill("QA ONLY: synthetic terminal interval.");
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  firstDocument = await api(`/api/videos/${firstVideo.id}/annotations`);
  const terminal = firstDocument.events.find((e) => e.kind === "rally_end");
  assert.equal(terminal.terminal_start_frame, 28);
  assert.equal(terminal.terminal_end_frame, 35);
  assert.equal(terminal.contact_start_frame, null);
  await page.reload();
  await page.locator(`[data-event="${terminal.id}"]`).click();
  assert.equal(await page.locator("#contact-end").inputValue(), "35");
  assert.equal(await page.locator("#player-label").isHidden(), true);
  assert.equal(await page.locator("#side-label").isHidden(), true);
  await page.locator("#clear-contact-interval").click();
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  const exactDocument = await api(`/api/videos/${firstVideo.id}/annotations`);
  assert.equal(
    exactDocument.events.find((e) => e.id === terminal.id).terminal_start_frame,
    null,
  );
  const originalRevision = await api(
    `/api/videos/${firstVideo.id}/revisions/${firstDocument.revision}`,
  );
  assert.equal(
    originalRevision.events.find((e) => e.id === terminal.id)
      .terminal_end_frame,
    35,
  );
  await page.locator("#contact-uncertainty summary").click();
  await page.locator("#contact-start").fill("28");
  await page.locator("#contact-end").fill("35");
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  firstDocument = await api(`/api/videos/${firstVideo.id}/annotations`);
  await page.locator("#event-kind").selectOption("shot");
  assert.equal(await page.locator("#contact-start").inputValue(), "");
  assert.match(
    await page.locator("#timing-uncertainty-title").textContent(),
    /Contact timing/,
  );
  // Exercise the real camera-scan UI in CI using the generated two-view video.
  await page.locator("#camera-panel summary").click();
  await page.locator("#scan-segments").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#segment-status")
      .textContent.includes("1 possible boundary"),
  );
  await page.locator('[data-boundary="20"]').click();
  assert.equal(await page.locator("#frame-number").inputValue(), "20");
  assert.match(
    await page.locator("#notice").textContent(),
    /not a rally boundary/,
  );
  assert.deepEqual(
    await api(`/api/videos/${firstVideo.id}/annotations`),
    firstDocument,
  );
  await page.locator("#camera-decision").selectOption("not_cut");
  await page
    .locator("#camera-notes")
    .fill("QA ONLY: correction workflow, not real scene truth.");
  await page.locator("#camera-apply").click();
  await page.locator("#scene-start").fill("0");
  await page.locator("#scene-end").fill("20");
  await page.locator("#scene-kind").selectOption("non_play");
  await page
    .locator("#scene-notes")
    .fill("QA ONLY: generated solid-color view.");
  await page.locator("#add-scene").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  firstDocument = await api(`/api/videos/${firstVideo.id}/annotations`);
  assert.equal(firstDocument.camera_corrections[0].is_cut, false);
  assert.equal(firstDocument.scene_ranges[0].scene, "non_play");
  assert.match(
    await page.locator('[data-boundary="20"]').textContent(),
    /Rejected cut/,
  );
  await page.locator("#upload-file").setInputFiles(fixtures.upload);
  await page.locator("#upload-form button[type=submit]").click();
  await ready(1, "upload-fixture.mp4");
  assert.equal((await api("/api/videos")).length, 1);
  assert.deepEqual(
    await api(`/api/videos/${firstVideo.id}/annotations`),
    firstDocument,
  );

  const jobsBeforeInvalid = (await api("/api/jobs")).length;
  await page.locator("#upload-file").setInputFiles(fixtures.invalid);
  const badUploadResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/upload") &&
      response.request().method() === "POST",
  );
  await page.locator("#upload-form button[type=submit]").click();
  assert.equal((await badUploadResponse).status(), 422);
  await page.waitForFunction(() =>
    document.querySelector("#import-status").classList.contains("error"),
  );
  assert.match(
    await page.locator("#import-status").textContent(),
    /not a readable video|video/,
  );
  assert.equal((await api("/api/jobs")).length, jobsBeforeInvalid);
  assert.equal((await api("/api/videos")).length, 1);

  await page.locator("#youtube-url").fill("https://127.0.0.1/private");
  const badUrlResponse = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/import/youtube") &&
      response.request().method() === "POST",
  );
  await page.locator("#youtube-form button[type=submit]").click();
  assert.equal((await badUrlResponse).status(), 422);
  await page.waitForFunction(() =>
    document
      .querySelector("#import-status")
      .textContent.includes("HTTPS YouTube video URL"),
  );
  assert.equal((await api("/api/jobs")).length, jobsBeforeInvalid);

  // The QA server replaces only the download function. This request still uses
  // production URL validation, queueing, timestamp inspection, catalog, and UI.
  await page
    .locator("#youtube-url")
    .fill("https://youtu.be/abcdefghijk?si=discard");
  await page.locator("#youtube-mode").selectOption("doubles");
  await page.locator("#youtube-form button[type=submit]").click();
  await ready(2, "QA YouTube fixture");
  const videos = await api("/api/videos");
  const youtube = videos.find((video) => video.source_type === "youtube");
  assert.ok(youtube);
  assert.equal(youtube.name, "QA YouTube fixture");
  assert.equal(youtube.source.id, "abcdefghijk");
  assert.equal(
    youtube.source.url,
    "https://www.youtube.com/watch?v=abcdefghijk",
  );
  assert.match(youtube.id, /^[a-f0-9]{16}$/);
  assert.notEqual(youtube.id, firstVideo.id);
  await page.getByRole("button", { name: /QA YouTube fixture/ }).click();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "QA YouTube fixture",
  );
  await page.waitForFunction(
    () => document.querySelector("#video").readyState >= 2,
  );
  await exactFrame(1);
  assert.equal(await page.locator(".player-row").count(), 4);
  assert.equal(
    await page.locator("#video").evaluate((video) => video.error),
    null,
  );
  assert.ok(statusLog.some((text) => /Uploading|Checking/.test(text)));
  assert.ok(statusLog.some((text) => /Preparing/.test(text)));
  await page.screenshot({
    path: fileURLToPath(new URL("import-desktop.png", output)),
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: fileURLToPath(new URL("import-mobile.png", output)),
    fullPage: true,
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
    "Mobile layout must not overflow horizontally.",
  );
  assert.deepEqual(errors, []);
  console.log(
    "Import browser checks passed: upload/progress/media, terminal intervals/history/kind switch, camera/scene corrections, duplicate persistence, invalid file/URL errors, queued YouTube fixture import, content identity, mobile layout.",
  );
} finally {
  await browser.close();
}
