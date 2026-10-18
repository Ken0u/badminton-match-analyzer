import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { chromium } from "playwright";

const base = "http://127.0.0.1:8005";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
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
  await page.waitForFunction(() =>
    document
      .querySelector("#analysis-status")
      .textContent.includes("Processing complete"),
  );
  assert.equal(await page.locator("#analysis-windows option").count(), 3);
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
  await page.locator('[data-candidate="qa-contact-600"]').click();
  await page.locator("#apply-event").click();
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  const reviewed = await get(root + "/annotations");
  assert.equal(reviewed.events.length, 1);
  assert.equal(reviewed.events[0].frame, 600);
  assert.equal(reviewed.events[0].family, "unknown");
  const verified = await start();
  await completed(verified);
  await page.waitForFunction(() =>
    document
      .querySelector("#analysis-status")
      .textContent.includes("Processing complete"),
  );
  const jobs = await get("/api/jobs");
  const latest = jobs.find((j) => j.id === verified);
  assert.equal(latest.status, "completed");
  assert.equal(latest.summary.reused_stages, 16);
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
