import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

const base = process.env.RALLY_BASE_URL || "http://127.0.0.1:8003";
assert.equal(
  new URL(base).port,
  "8003",
  "Use the isolated generated rally fixture.",
);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
async function json(path, options) {
  const r = await page.request.fetch(base + path, options);
  assert.ok(r.ok(), `${path}: ${r.status()} ${await r.text()}`);
  return r.json();
}
async function ready() {
  await page.goto(base);
  await page.waitForFunction(
    () => !document.querySelector("#suggest-rallies").disabled,
  );
}
async function save() {
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  assert.equal(
    await page
      .locator("#notice")
      .evaluate((e) => e.classList.contains("error")),
    false,
  );
}
try {
  const videos = await json("/api/videos");
  assert.equal(videos.length, 1);
  const root = `/api/videos/${videos[0].id}`;
  const before = await json(root + "/annotations");
  assert.equal(before.events.length, 0);
  await ready();
  assert.equal(await page.locator("#player-model").inputValue(), "small");
  assert.equal(await page.locator("#auto-court").isChecked(), true);
  await page.locator("#player-model").selectOption("nano");
  let requestBody;
  await page.route("**/track", async (route) => {
    requestBody = route.request().postDataJSON();
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({ detail: "QA intercepted tracking request" }),
    });
  });
  await page.locator("#track").click();
  await page.waitForFunction(() =>
    document.querySelector("#notice").textContent.includes("QA intercepted"),
  );
  assert.equal(requestBody.player_model, "nano");
  assert.equal(requestBody.auto_calibrate, true);
  await page.locator("#auto-court").uncheck();
  await Promise.all([
    page.waitForResponse((r) => r.url().endsWith("/track")),
    page.locator("#track").click(),
  ]);
  assert.equal(requestBody.auto_calibrate, false);
  await page.unroute("**/track");
  await page.locator("#suggest-rallies").click();
  await page.waitForFunction(
    () => document.querySelector("#rally-count").textContent === "2",
  );
  assert.deepEqual(
    await json(root + "/annotations"),
    before,
    "Proposals must not save annotations",
  );

  // An unsaved scene edit outside a candidate's interval still invalidates its context.
  await page.locator("#camera-panel").evaluate((e) => (e.open = true));
  await page.locator("#scene-start").fill("1");
  await page.locator("#scene-end").fill("15");
  await page.locator("#scene-kind").selectOption("replay");
  await page.locator("#add-scene").click();
  assert.equal(
    await page.locator("#rally-candidates button:disabled").count(),
    2,
  );
  await page.locator("#suggest-rallies").click();
  assert.match(await page.locator("#notice").textContent(), /Save annotations/);
  await ready(); // Discards the unsaved mask.
  await page.waitForFunction(
    () => document.querySelector("#rally-count").textContent === "2",
  );
  await page.locator("#clear-court").click();
  assert.equal(
    await page.locator("#rally-candidates button:disabled").count(),
    2,
  );
  await ready();
  await page.waitForFunction(
    () => document.querySelector("#rally-count").textContent === "2",
  );
  const jobs = await json("/api/jobs");
  const job = jobs.find(
    (j) => j.kind === "rallies" && j.status === "completed",
  );
  const run = await json(root + `/runs/${job.id}`);
  const ending = run.candidates.find((c) => c.kind === "rally_end");
  assert.equal(ending.evidence.settled_region, "near_court_surround");
  assert.equal(ending.evidence.line_call_verified, false);
  assert.match(
    await page.locator(`[data-rally-candidate="${ending.id}"]`).textContent(),
    /near court edge/,
  );
  for (const kind of ["serve", "rally_end"]) {
    const c = run.candidates.find((c) => c.kind === kind);
    await page.locator(`[data-rally-candidate="${c.id}"]`).click();
    if (kind === "rally_end")
      assert.match(
        await page.locator("#event-notes").inputValue(),
        /line call are unverified/,
      );
    assert.equal(await page.locator("#event-kind").inputValue(), kind);
    assert.equal(await page.locator("#event-player").inputValue(), "");
    assert.equal(await page.locator("#event-family").inputValue(), "unknown");
    assert.equal(await page.locator("#event-side").inputValue(), "unknown");
    assert.equal(
      await page.locator("#contact-start").inputValue(),
      String(c.start_frame),
    );
    assert.equal(
      await page.locator("#contact-end").inputValue(),
      String(c.end_frame),
    );
    await page.locator("#apply-event").click();
    await save();
    assert.equal(
      await page.locator(`[data-rally-candidate="${c.id}"]`).isDisabled(),
      true,
    );
  }
  const exported = await json(root + "/export");
  assert.equal(exported.annotations.events.length, 2);
  for (const event of exported.annotations.events) {
    const c = run.candidates.find((c) => c.kind === event.kind);
    assert.equal(event.source_run_id, job.id);
    assert.equal(event.candidate_id, c.id);
    assert.equal(event.player_id, null);
    if (event.kind === "rally_end")
      assert.match(event.notes, /line call are unverified/);
    const prefix = event.kind === "rally_end" ? "terminal" : "contact";
    assert.equal(event[`${prefix}_start_frame`], c.start_frame);
    assert.equal(event[`${prefix}_end_frame`], c.end_frame);
  }
  await ready();
  await page.waitForFunction(
    () => document.querySelector("#event-count").textContent === "2 events",
  );
  assert.equal(
    await page.locator("#rally-candidates button:disabled").count(),
    2,
  );
  // Simulated derived geometry exercises UI review without changing server truth.
  const playerRun = await json(root + "/runs/qa-players");
  const currentDoc = await json(root + "/annotations");
  await page.route(`**${root}/annotations`, async (route) => {
    assert.equal(route.request().method(), "GET");
    await route.fulfill({ json: { ...currentDoc, calibrations: [] } });
  });
  await page.route(`**${root}/runs/qa-players`, async (route) => {
    await route.fulfill({
      json: {
        ...playerRun,
        court_context_version: 1,
        automatic_calibrations: currentDoc.calibrations,
      },
    });
  });
  await ready();
  await page.waitForFunction(() =>
    document
      .querySelector("#court-status")
      .textContent.includes("Auto-detected"),
  );
  assert.match(await page.locator("#court-status").textContent(), /unreviewed/);
  // A draft camera change immediately hides the run-local fit.
  await page.locator("#camera-panel").evaluate((e) => (e.open = true));
  await page.locator("#camera-frame").fill("20");
  await page.locator("#camera-decision").selectOption("cut");
  await page.locator("#camera-apply").click();
  assert.match(
    await page.locator("#court-status").textContent(),
    /No calibration/,
  );
  await page.unroute(`**${root}/annotations`);
  await page.unroute(`**${root}/runs/qa-players`);
  await ready();
  await fs.mkdir("data/processed/qa", { recursive: true });
  await page.screenshot({
    path: "data/processed/qa/rally-browser.png",
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "Rally browser passed: model choice, proposal isolation, draft staleness, reviewed save/export/reload.",
  );
} finally {
  await browser.close();
}
