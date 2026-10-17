import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";

const base = process.env.CONTACT_BASE_URL || "http://127.0.0.1:8004";
assert.equal(
  new URL(base).port,
  "8004",
  "Use the isolated generated contact fixture.",
);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
async function json(path, options) {
  const response = await page.request.fetch(base + path, options);
  assert.ok(response.ok(), `${response.status()} ${await response.text()}`);
  return response.json();
}
async function ready() {
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent === "1",
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
  const queued = await json(root + "/contacts", {
    method: "POST",
    data: { player_run_id: "qa-players", shuttle_run_id: "qa-shuttle" },
  });
  let job;
  for (let n = 0; n < 100; n++) {
    job = (await json("/api/jobs")).find((j) => j.id === queued.id);
    if (!["queued", "running"].includes(job.status)) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(job.status, "completed", job.message);
  const run = await json(root + `/runs/${job.id}`);
  assert.equal(run.candidates.length, 1);
  const candidate = run.candidates[0];
  assert.equal(candidate.evidence_source, "subframe_trajectory_and_pose");
  assert.equal(candidate.timing, "uncertain_interval");
  assert.ok(candidate.context_start_frame < candidate.start_frame);
  const observedStart = Math.min(...candidate.evidence.observed_context_frames);
  assert.ok(candidate.context_start_frame < observedStart);
  const shuttle = await json(root + "/runs/qa-shuttle");
  assert.equal(
    shuttle.frames[20].shuttle.selection_reason,
    "unique_reachable_component",
  );
  assert.deepEqual(await json(root + "/annotations"), before);
  await ready();
  await page.locator("#camera-panel").evaluate((e) => (e.open = true));
  await page
    .locator("#scene-start")
    .fill(String(candidate.context_start_frame));
  await page.locator("#scene-end").fill(String(observedStart));
  await page.locator("#scene-kind").selectOption("replay");
  await page.locator("#add-scene").click();
  assert.equal(await page.locator("#candidates button").isDisabled(), true);
  await ready(); // Discard the draft mask, preserving saved labels.
  await page.locator("#candidates button").click();
  assert.equal(await page.locator("#event-player").inputValue(), "");
  assert.equal(await page.locator("#event-family").inputValue(), "unknown");
  assert.equal(await page.locator("#event-side").inputValue(), "unknown");
  assert.equal(
    await page.locator("#contact-start").inputValue(),
    String(candidate.start_frame),
  );
  assert.equal(
    await page.locator("#contact-end").inputValue(),
    String(candidate.end_frame),
  );
  await page
    .locator("#event-notes")
    .fill("Synthetic software QA; not real badminton ground truth.");
  await page.locator("#apply-event").click();
  await save();
  const exported = await json(root + "/export");
  assert.equal(exported.annotations.events.length, 1);
  const event = exported.annotations.events[0];
  assert.equal(event.source_run_id, job.id);
  assert.equal(event.candidate_id, candidate.id);
  assert.equal(event.contact_start_frame, candidate.start_frame);
  assert.equal(event.contact_end_frame, candidate.end_frame);
  assert.equal(event.player_id, null);
  await ready();
  await page.waitForFunction(
    () => document.querySelector("#event-count").textContent === "1 event",
  );
  await page.locator("#events .event-row").click();
  assert.equal(
    await page.locator("#contact-start").inputValue(),
    String(candidate.start_frame),
  );
  await fs.mkdir("data/processed/qa", { recursive: true });
  await page.screenshot({
    path: "data/processed/qa/contact-profile-browser.png",
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "Generated contact browser passed: interval review, draft evidence masks, saved lineage/export/reload.",
  );
} finally {
  await browser.close();
}
