import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:8001";
assert.equal(
  new URL(base).port,
  "8001",
  "Camera QA must use the isolated server.",
);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const output = new URL("../data/processed/qa/", import.meta.url);
await fs.mkdir(output, { recursive: true });
try {
  const videos = await (await page.request.get(`${base}/api/videos`)).json();
  const singles = videos.find((v) => v.name === "singles.mp4");
  assert.ok(singles);
  const url = `${base}/api/videos/${singles.id}`;
  const before = await (await page.request.get(`${url}/annotations`)).json();
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  await page.locator("#camera-panel summary").click();
  const request = page.waitForResponse(
    (r) => r.url() === `${url}/segments` && r.request().method() === "POST",
  );
  await page.locator("#scan-segments").click();
  const response = await request;
  assert.equal(response.status(), 202);
  const jobId = (await response.json()).id;
  await page.waitForFunction(
    () =>
      document
        .querySelector("#segment-status")
        .textContent.includes("65 possible boundaries"),
    null,
    { timeout: 90000 },
  );
  let job;
  for (let attempt = 0; attempt < 90; attempt++) {
    job = (
      await (
        await page.request.get(`${base}/api/jobs?video_id=${singles.id}`)
      ).json()
    ).find((j) => j.id === jobId);
    if (!["queued", "running"].includes(job.status)) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  assert.equal(job.status, "completed", job.message);
  await page.waitForFunction(
    (id) => document.querySelector("#camera-boundaries").dataset.runId === id,
    jobId,
  );
  const run = await (await page.request.get(`${url}/runs/${jobId}`)).json();
  assert.equal(run.cut_frames.length, 65);
  assert.equal(run.cut_frames[0], 130);
  assert.equal(run.boundaries[0].time_s, 5.2);
  assert.ok(run.camera_ranges.every((s) => s.scene === "unknown"));
  let releaseFrame;
  const frameGate = new Promise((resolve) => {
    releaseFrame = resolve;
  });
  await page.route("**/frame?index=130", async (route) => {
    await frameGate;
    await route.continue();
  });
  await page.locator('[data-boundary="130"]').click();
  await page.locator("#frame-loading").waitFor({ state: "visible" });
  assert.equal(await page.locator("#exact-frame").isHidden(), true);
  releaseFrame();
  await page.waitForFunction(
    () => document.querySelector("#frame-number").value === "130",
  );
  await page.waitForFunction(() => {
    const image = document.querySelector("#exact-frame");
    return (
      image.src.endsWith("index=130") &&
      image.complete &&
      !image.hidden &&
      image.naturalWidth === 1280
    );
  });
  assert.equal(await page.locator("#frame-loading").isHidden(), true);
  await page.unroute("**/frame?index=130");
  assert.match(
    await page.locator("#notice").textContent(),
    /not a rally boundary/,
  );
  assert.equal(await page.locator("#save").isDisabled(), true);
  assert.deepEqual(
    await (await page.request.get(`${url}/annotations`)).json(),
    before,
  );
  await page.screenshot({
    path: fileURLToPath(new URL("camera-boundaries.png", output)),
    fullPage: true,
  });
  await page.getByRole("button", { name: /doubles.mp4/ }).click();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "doubles.mp4",
  );
  assert.equal(await page.locator('[data-boundary="130"]').count(), 0);
  assert.deepEqual(errors, []);
  console.log(
    "Camera browser checks passed: full-video scan, source-frame navigation, unknown scene status, saved-label preservation, video switch reset.",
  );
} finally {
  await browser.close();
}
