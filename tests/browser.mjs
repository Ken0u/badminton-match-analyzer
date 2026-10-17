import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";
const base = process.env.BASE_URL || "http://127.0.0.1:8001";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const output = new URL("../data/processed/qa/", import.meta.url);
await fs.mkdir(output, { recursive: true });
try {
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  await page.waitForFunction(
    () => document.querySelector("#video").readyState >= 2,
  );
  assert.equal(await page.locator("#event-family option").count(), 8);
  assert.equal(
    await page.locator('#event-family option[value="half_smash"]').count(),
    0,
  );
  // Restore a clean isolated test document, retaining optimistic revisions.
  await page.evaluate(async () => {
    const videos = await (await fetch("/api/videos")).json();
    const v = videos.find((v) => v.name === "singles.mp4");
    const url = `/api/videos/${v.id}/annotations`;
    const doc = await (await fetch(url)).json();
    doc.events = [];
    doc.calibrations = [];
    doc.review_windows = [];
    doc.shuttle_points = [];
    doc.track_assignments = [];
    await fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(doc),
    });
  });
  await page.reload();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  async function seek(frame) {
    await page.locator("#frame-number").fill(String(frame));
    await page.locator("#frame-number").dispatchEvent("change");
    await page.waitForFunction((f) => {
      const i = document.querySelector("#exact-frame");
      return (
        i.src.endsWith(`index=${f}`) &&
        !i.hidden &&
        i.complete &&
        i.naturalWidth > 0
      );
    }, frame);
  }
  await seek(2000);
  await page.locator("#play").click();
  await page.waitForFunction(
    () => document.querySelector("#video").currentTime > 80.12,
  );
  await page.locator("#play").click();
  await seek(2000);
  await page.locator('[data-mark="serve"]').click();
  await page.locator("#rally-id").fill("QA-R1");
  await page.locator("#event-player").selectOption("A");
  await page.locator("#apply-event").click();
  await seek(2010);
  await page.locator('[data-mark="shot"]').click();
  await page.locator("#event-player").selectOption("B");
  await page.locator("#event-family").selectOption("clear");
  await page.locator("#event-side").selectOption("forehand");
  await page.locator("#apply-event").click();
  await page.locator("#event-side").selectOption("backhand");
  await page.locator("#apply-event").click();
  await seek(2050);
  await page.locator('[data-mark="rally_end"]').click();
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  await seek(2004);
  await page.locator("#court-start").fill("2000");
  await page.locator("#court-end").fill("2250");
  await page.locator("#calibrate").click();
  const bounds = await page.locator("#overlay").boundingBox();
  for (const [x, y] of [
    [437, 260],
    [842, 260],
    [994, 658],
    [289, 658],
  ]) {
    await page.locator("#overlay").click({
      position: {
        x: (x / 1280) * bounds.width,
        y: (y / 720) * bounds.height,
      },
    });
  }
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  const payload = await page.evaluate(async () => {
    const videos = await (await fetch("/api/videos")).json();
    return (
      await fetch(
        `/api/videos/${videos.find((v) => v.name === "singles.mp4").id}/export`,
      )
    ).json();
  });
  assert.equal(payload.annotations.events.length, 3);
  assert.equal(payload.annotations.events[1].family, "clear");
  assert.equal(payload.annotations.events[1].side, "backhand");
  assert.equal(payload.annotations.events[1].frame, 2010);
  assert.equal(payload.annotations.events[1].time_s, 80.4);
  assert.equal(payload.annotations.calibrations.length, 1);
  // Edits made while a save is in flight must survive its older response.
  await page.locator("#event-notes").fill("First version");
  await page.locator("#apply-event").click();
  let releaseSave;
  const saveGate = new Promise((resolve) => {
    releaseSave = resolve;
  });
  let saveEntered;
  const saving = new Promise((resolve) => {
    saveEntered = resolve;
  });
  const annotationRoute = "**/api/videos/*/annotations";
  await page.route(annotationRoute, async (route) => {
    if (route.request().method() === "PUT") {
      saveEntered();
      await saveGate;
    }
    await route.continue();
  });
  await page.locator("#save").click();
  await saving;
  await page.getByRole("button", { name: /doubles.mp4/ }).click();
  assert.equal(await page.locator("#title").textContent(), "singles.mp4");
  await page.locator("#event-notes").fill("Newest version");
  await page.locator("#apply-event").click();
  releaseSave();
  await page.waitForFunction(() =>
    document
      .querySelector("#notice")
      .textContent.includes("Earlier edits saved"),
  );
  await page.unroute(annotationRoute);
  assert.equal(await page.locator("#save").isDisabled(), false);
  assert.equal(
    await page.locator("#event-notes").inputValue(),
    "Newest version",
  );
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  let expectedEventCount = 3;
  const hasContactFixtures = await page.evaluate(async () => {
    const videos = await (await fetch("/api/videos")).json();
    const video = videos.find((v) => v.name === "singles.mp4");
    const jobs = await (await fetch(`/api/jobs?video_id=${video.id}`)).json();
    return jobs.some(
      (j) =>
        j.kind === "contacts" &&
        j.status === "completed" &&
        j.summary?.candidate_count > 0,
    );
  });
  if (hasContactFixtures) {
    // Cached model output is a suggestion, not an automatic annotation.
    await page.waitForFunction(
      () => Number(document.querySelector("#candidate-count").textContent) > 0,
    );
    assert.equal(await page.locator("#event-count").textContent(), "3 events");
    await page
      .locator("#candidates .candidate-row:not([disabled])")
      .first()
      .click();
    assert.equal(await page.locator("#event-player").inputValue(), "");
    await page.locator("#rally-id").fill("QA-R2");
    await page.locator("#apply-event").click();
    await page.locator("#save").click();
    await page.waitForFunction(() => document.querySelector("#save").disabled);
    const reviewed = await page.evaluate(async () => {
      const videos = await (await fetch("/api/videos")).json();
      const data = await (
        await fetch(
          `/api/videos/${videos.find((v) => v.name === "singles.mp4").id}/export`,
        )
      ).json();
      return data.annotations.events.find((e) => e.candidate_id);
    });
    assert.ok(reviewed.source_run_id && reviewed.candidate_id);
    assert.equal(reviewed.family, "unknown");
    assert.equal(reviewed.status, "reviewed");
    expectedEventCount = 4;
  } else {
    console.log(
      "Optional contact-review check skipped: no cached contact run.",
    );
  }
  await seek(2004);
  await page.screenshot({
    path: fileURLToPath(new URL("viewer-desktop.png", output)),
    fullPage: true,
  });
  await page.reload();
  await page.waitForFunction(
    (count) =>
      document.querySelector("#event-count").textContent === `${count} events`,
    expectedEventCount,
  );
  await page.getByRole("button", { name: /doubles.mp4/ }).click();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "doubles.mp4",
  );
  assert.equal(await page.locator(".player-row").count(), 4);
  assert.equal(await page.locator("#event-count").textContent(), "0 events");
  // A slower response from a previously selected video cannot replace the new one.
  let releaseSelection;
  const selectionGate = new Promise((resolve) => {
    releaseSelection = resolve;
  });
  let selectionEntered;
  const selecting = new Promise((resolve) => {
    selectionEntered = resolve;
  });
  const singlesId = await page
    .getByRole("button", { name: /singles.mp4/ })
    .getAttribute("data-video");
  const singlesRoute = `**/api/videos/${singlesId}/annotations`;
  await page.route(singlesRoute, async (route) => {
    selectionEntered();
    await selectionGate;
    await route.continue();
  });
  await page.getByRole("button", { name: /singles.mp4/ }).click();
  await selecting;
  await page.getByRole("button", { name: /doubles.mp4/ }).click();
  releaseSelection();
  await page.waitForLoadState("networkidle");
  assert.equal(await page.locator("#title").textContent(), "doubles.mp4");
  await page.unroute(singlesRoute);
  await seek(675);
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.screenshot({
    path: fileURLToPath(new URL("viewer-tablet.png", output)),
    fullPage: true,
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  assert.deepEqual(errors, []);
  console.log(
    "Browser checks passed: playback, exact-frame seeking, six families, event create/edit, persistence, export, singles/doubles, responsive layout.",
  );
} finally {
  await browser.close();
}
