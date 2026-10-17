import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:8001";
assert.equal(
  new URL(base).port,
  "8001",
  "Synthetic scene edits must use isolated QA.",
);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
let backup, url;
async function json(path, options) {
  const r = await page.request.fetch(`${base}${path}`, options);
  assert.ok(r.ok(), `${r.status()} ${await r.text()}`);
  return r.json();
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
  const v = (await json("/api/videos")).find((v) => v.name === "singles.mp4");
  url = `/api/videos/${v.id}`;
  backup = await json(`${url}/annotations`);
  await json(`${url}/annotations`, {
    method: "PUT",
    data: { ...backup, scene_ranges: [], camera_corrections: [] },
  });
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent !== "0",
  );
  await page.locator("#camera-panel summary").click();
  await page.locator("#scene-start").fill("2000");
  await page.locator("#scene-end").fill("2100");
  await page.locator("#scene-kind").selectOption("replay");
  await page
    .locator("#scene-notes")
    .fill("QA ONLY: synthetic replay exclusion, not real scene ground truth.");
  await page.locator("#add-scene").click();
  assert.equal(
    await page
      .locator("#notice")
      .evaluate((e) => e.classList.contains("error")),
    false,
    await page.locator("#notice").textContent(),
  );
  const blocked = page
    .locator("#candidates button")
    .filter({ hasText: "Excluded by scene review" });
  assert.ok(await blocked.count());
  assert.equal(await blocked.first().isDisabled(), true);
  await page.locator("#scene-start").fill("2050");
  await page.locator("#scene-end").fill("2150");
  await page.locator("#add-scene").click();
  assert.match(await page.locator("#notice").textContent(), /must not overlap/);
  await save();
  const sceneDoc = await json(`${url}/annotations`);
  assert.equal(sceneDoc.scene_ranges[0].scene, "replay");
  assert.deepEqual(sceneDoc.events, backup.events);
  const jobs = await json(`/api/jobs?video_id=${v.id}`);
  const shuttle = jobs.find(
    (j) =>
      j.kind === "shuttle" &&
      j.status === "completed" &&
      j.summary?.start_frame === 2000 &&
      j.summary?.end_frame === 2250,
  );
  const players = jobs.find(
    (j) =>
      j.kind === "players" &&
      j.status === "completed" &&
      j.summary?.image_size === 1280 &&
      j.summary?.start_frame === 2000 &&
      j.summary?.end_frame === 2250,
  );
  assert.ok(shuttle && players);
  const queued = await json(`${url}/contacts`, {
    method: "POST",
    data: { shuttle_run_id: shuttle.id, player_run_id: players.id },
  });
  let done;
  for (let i = 0; i < 100; i++) {
    done = (await json(`/api/jobs?video_id=${v.id}`)).find(
      (j) => j.id === queued.id,
    );
    if (!["queued", "running"].includes(done.status)) break;
    await new Promise((r) => setTimeout(r, 100));
  }
  assert.equal(done.status, "completed", done.message);
  const artifact = await json(`${url}/runs/${queued.id}`);
  assert.ok(
    artifact.candidates.every((c) => c.frame < 2000 || c.frame >= 2100),
  );
  assert.equal(artifact.scene_annotation_revision, sceneDoc.revision);

  await page.locator("#camera-frame").fill("2039");
  await page.locator("#camera-decision").selectOption("cut");
  await page
    .locator("#camera-notes")
    .fill("QA ONLY: synthetic missed cut, not real boundary truth.");
  await page.locator("#camera-apply").click();
  assert.ok(
    await page
      .locator("#candidates button")
      .filter({ hasText: "Camera review changed" })
      .count(),
  );
  await save();
  const stale = await page.request.post(`${base}${url}/contacts`, {
    data: { shuttle_run_id: shuttle.id, player_run_id: players.id },
  });
  assert.equal(stale.status(), 422);
  assert.match(await stale.text(), /rerun tracking/);
  assert.ok(await page.locator('[data-reset-cut="2039"]').count());
  await page.locator('[data-reset-cut="2039"]').click();
  await save();
  await page.locator("[data-edit-scene]").click();
  await page.locator("#scene-kind").selectOption("live");
  await page.locator("#add-scene").click();
  await save();
  assert.equal(
    (await json(`${url}/annotations`)).scene_ranges[0].scene,
    "live",
  );
  await fs.mkdir(new URL("../data/processed/qa/", import.meta.url), {
    recursive: true,
  });
  await page.screenshot({
    path: fileURLToPath(
      new URL("../data/processed/qa/scene-review.png", import.meta.url),
    ),
    fullPage: true,
  });
  await page.locator("[data-remove-scene]").click();
  await save();
  assert.deepEqual((await json(`${url}/annotations`)).scene_ranges, []);
  assert.deepEqual(errors, []);
  console.log(
    "Scene browser checks passed: draft exclusions, overlap errors, revision/export persistence, replay-filtered inference, stale tracking rejection, correction removal and scene edit/removal.",
  );
} finally {
  if (backup && url) {
    const current = await json(`${url}/annotations`);
    await json(`${url}/annotations`, {
      method: "PUT",
      data: { ...backup, revision: current.revision },
    });
  }
  await browser.close();
}
