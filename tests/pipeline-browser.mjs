import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const base = "http://127.0.0.1:8005";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  window.trackText = [];
  const original = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
    if (String(text).includes("Track ")) window.trackText.push(String(text));
    return original.call(this, text, ...args);
  };
});
async function get(path) {
  const r = await page.request.get(base + path);
  assert.ok(r.ok(), await r.text());
  return r.json();
}
async function start() {
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/analysis") && r.request().method() === "POST",
    ),
    page.locator("#process-analysis").click(),
  ]);
  assert.ok(response.ok(), await response.text());
  return (await response.json()).id;
}
async function completed(id) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    const job = (await get("/api/jobs")).find((j) => j.id === id);
    if (job && !["queued", "running"].includes(job.status)) {
      assert.equal(job.status, "completed", JSON.stringify(job));
      return;
    }
    await page.waitForTimeout(100);
  }
  assert.fail(`The same processing job ${id} did not finish`);
}
async function completedInViewer(id) {
  await page.waitForFunction((current) => {
    const status = document.querySelector("#analysis-status");
    return (
      status.dataset.jobId === current &&
      status.dataset.jobStatus === "completed" &&
      status.textContent.includes("Processing complete")
    );
  }, id);
}
async function seek(frame) {
  await page.locator("#frame-number").fill(String(frame));
  await page.locator("#frame-number").dispatchEvent("change");
  await page.waitForFunction(
    (f) =>
      document.querySelector("#exact-frame").src.endsWith("index=" + f) &&
      document.querySelector("#exact-frame").complete,
    frame,
  );
}
try {
  const [v] = await get("/api/videos"),
    root = `/api/videos/${v.id}`;
  assert.equal(v.frame_count, 1300);
  const before = await get(root + "/annotations");
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "pipeline-qa.mp4",
  );
  await page.locator("#analysis-panel").evaluate((e) => (e.open = true));
  await start();
  await page.waitForFunction(() =>
    document.querySelector("#analysis-status").textContent.includes("players"),
  );
  await page.locator("#pause-analysis").click();
  await page.waitForFunction(() =>
    document.querySelector("#analysis-status").textContent.includes("Paused;"),
  );
  assert.deepEqual(await get(root + "/annotations"), before);
  const resumed = await start();
  await completed(resumed);
  await completedInViewer(resumed);
  assert.equal(await page.locator("#analysis-windows option").count(), 3);
  assert.match(
    await page.locator("#analysis-status").textContent(),
    /2 overlap-linked actor groups/,
  );
  assert.deepEqual(await get(root + "/annotations"), before);
  await seek(599);
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent === "0",
  );
  await seek(600);
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent === "2",
  );
  assert.equal(
    await page.locator('[data-candidate="qa-contact-600"]').count(),
    1,
  );
  assert.match(
    await page.locator('[data-candidate="qa-contact-600"]').textContent(),
    /Actor \d+\?/,
  );
  const plan = await get(root + "/analysis/" + resumed);
  const part = plan.parts.find((p) => p.window.core_start_frame === 600);
  const poses = await get(root + "/runs/" + part.stages.players.run_id);
  const track = poses.frames.find((r) => r.frame === 605).players[0].track_id;
  await page.evaluate(() => (window.trackText = []));
  await seek(605);
  await page.waitForFunction(
    (id) => window.trackText.some((s) => s.includes(`Track ${id} `)),
    track,
  );
  assert.ok(
    (
      await page.evaluate(
        (id) => window.trackText.filter((s) => s.includes(`Track ${id} `)),
        track,
      )
    ).every((s) => !s.includes("Actor ")),
  );
  await page.evaluate(() => (window.trackText = []));
  await seek(610);
  await page.waitForFunction(
    (id) =>
      window.trackText.some(
        (s) => s.includes(`Track ${id} `) && s.includes("Actor "),
      ),
    track,
  );
  await page.locator('[data-candidate="qa-contact-600"]').click();
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  const reviewed = await get(root + "/annotations");
  assert.equal(reviewed.events.length, 1);
  assert.equal(reviewed.events[0].frame, 600);
  assert.equal(reviewed.events[0].family, "unknown");
  assert.equal(reviewed.events[0].player_id, null);
  const verified = await start();
  await completed(verified);
  await completedInViewer(verified);
  const jobs = await get("/api/jobs");
  const latest = jobs.find((j) => j.id === verified);
  assert.equal(latest.status, "completed");
  assert.equal(latest.summary.reused_stages, 17);
  assert.match(
    await page.locator("#notice").textContent(),
    /Full-match processing complete\./,
  );
  assert.deepEqual(await get(root + "/annotations"), reviewed);
  await seek(1200);
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent === "0",
  );
  await fs.mkdir("data/processed/qa", { recursive: true });
  await page.screenshot({
    path: "data/processed/qa/pipeline-browser.png",
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "Full-source browser passed: pause/resume, source-window navigation, halo ownership, explicit review and immutable reuse.",
  );
} finally {
  await browser.close();
}
