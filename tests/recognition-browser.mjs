// Local model integration check; uses isolated QA labels, never pilot gold labels.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:8001";
assert.equal(
  new URL(base).port,
  "8001",
  "Recognition QA requires isolated port 8001.",
);
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const output = new URL("../data/processed/qa/", import.meta.url);
await fs.mkdir(output, { recursive: true });
async function json(path, options) {
  const response = await page.request.fetch(`${base}${path}`, options);
  assert.ok(
    response.ok(),
    `${path}: ${response.status()} ${await response.text()}`,
  );
  return response.json();
}
async function save() {
  await page.locator("#apply-event").click();
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
  const singles = videos.find((v) => v.name === "singles.mp4");
  const doubles = videos.find((v) => v.name === "doubles.mp4");
  assert.ok(
    singles && doubles,
    "Real sample media and checkpoints are required.",
  );
  const root = `/api/videos/${singles.id}`;
  const previous = await json(`${root}/annotations`);
  let doc = await json(`${root}/annotations`, {
    method: "PUT",
    data: {
      ...previous,
      events: [
        {
          id: "qa-stroke",
          rally_id: "QA1",
          kind: "shot",
          frame: 2077,
          family: "clear",
          side: "backhand",
          notes: "Synthetic workflow fixture; not a gold label.",
        },
      ],
      track_assignments: [],
      review_windows: [
        {
          id: "qa-recognition",
          start_frame: 2000,
          end_frame: 2250,
          scene: "live",
          contacts_complete: true,
          notes: "Synthetic workflow coverage; not real gold labels.",
        },
      ],
      shuttle_points: [],
      calibrations: [
        {
          start_frame: 2000,
          end_frame: 2250,
          corners: [
            [437, 260],
            [842, 260],
            [994, 658],
            [289, 658],
          ].map(([x, y]) => ({ x: x / 1280, y: y / 720 })),
        },
      ],
    },
  });
  const jobs = await json(`/api/jobs?video_id=${singles.id}`);
  const players = jobs.find(
    (j) =>
      j.kind === "players" &&
      j.status === "completed" &&
      j.summary?.image_size === 1280 &&
      j.summary?.start_frame === 2000,
  );
  const shuttle = jobs.find(
    (j) =>
      j.kind === "shuttle" &&
      j.status === "completed" &&
      j.summary?.start_frame === 2000,
  );
  assert.ok(players && shuttle);
  const job = await json(`${root}/recognize`, {
    method: "POST",
    data: {
      player_run_id: players.id,
      shuttle_run_id: shuttle.id,
    },
  });
  let completed = false;
  for (let attempt = 0; attempt < 60; attempt++) {
    const current = (await json("/api/jobs")).find((j) => j.id === job.id);
    if (current.status === "failed") throw Error(current.message);
    if (current.status === "completed") {
      completed = true;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  assert.equal(completed, true, "Recognition did not finish.");
  assert.deepEqual(
    await json(`${root}/annotations`),
    doc,
    "Inference must not save model labels.",
  );
  const raw = await json(`${root}/runs/${job.id}`);
  const prediction = raw.candidates.find((c) => c.event_id === "qa-stroke");
  assert.equal(prediction.status, "predicted");
  assert.ok(["forehand", "backhand", "unknown"].includes(prediction.side));
  const manualSide = prediction.side === "backhand" ? "forehand" : "backhand";
  doc = await json(`${root}/annotations`, {
    method: "PUT",
    data: {
      ...doc,
      events: doc.events.map((e) => ({ ...e, side: manualSide })),
    },
  });
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  const card = page.locator(`[data-stroke="${prediction.id}"]`);
  await card.waitFor();
  await page.locator("#review-panel summary").click();
  await page.locator("#evaluate").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#evaluation-results")
      .textContent.includes("Shot-family F1"),
  );
  assert.match(
    await page.locator("#evaluation-results").textContent(),
    /1\/6 target families/,
  );
  assert.match(
    await page.locator("#evaluation-results").textContent(),
    /conditional on the supplied contacts/,
  );
  await card.click();
  assert.equal(
    await page.locator("#event-family").inputValue(),
    prediction.family,
  );
  assert.equal(
    await page.locator("#event-side").inputValue(),
    manualSide,
    "Keep manually entered stroke side.",
  );
  assert.deepEqual(
    await json(`${root}/annotations`),
    doc,
    "Loading a suggestion is still only a draft.",
  );
  await save();
  const applied = (await json(`${root}/annotations`)).events[0];
  assert.equal(applied.classification_run_id, job.id);
  assert.equal(applied.family_score, prediction.family_score);
  assert.equal(applied.side, manualSide);
  assert.equal(await card.isDisabled(), true);
  await page.locator("#evaluate").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#evaluation-results")
      .textContent.includes("classifier-assisted label(s) excluded"),
  );
  assert.match(
    await page.locator("#evaluation-results").textContent(),
    /add independent family labels/,
  );
  const csv = await page.request.get(`${base}${root}/export?format=csv`);
  assert.ok((await csv.text()).includes(job.id));
  await page.locator("#event-frame").fill("2076");
  await save();
  assert.equal(
    (await json(`${root}/annotations`)).events[0].family_score,
    null,
    "Moving a contact clears its model score.",
  );
  assert.match(await card.textContent(), /Applied|Contact changed/);
  // An unapplied prediction for a moved event must be disabled too.
  const moved = await json(`${root}/annotations`);
  moved.events[0].classification_run_id = null;
  moved.events[0].classification_candidate_id = null;
  await json(`${root}/annotations`, { method: "PUT", data: moved });
  await page.reload();
  await card.waitFor();
  assert.match(await card.textContent(), /Contact changed/);
  assert.equal(await card.isDisabled(), true);
  const after = await json(`${root}/runs/${job.id}`);
  // The response reports the current identity revision; inference stays fixed.
  delete after.identity_annotation_revision;
  delete raw.identity_annotation_revision;
  assert.deepEqual(after, raw, "Review cannot rewrite predictions.");
  const resolved = await json(`${root}/annotations`);
  Object.assign(resolved.events[0], {
    frame: 2077,
    side: "unknown",
    family: "unknown",
    player_id: "A",
    family_score: null,
  });
  resolved.track_assignments = [
    {
      run_id: players.id,
      track_id: 1,
      player_id: "A",
      start_frame: 2000,
      end_frame: 2250,
    },
  ];
  await json(`${root}/annotations`, { method: "PUT", data: resolved });
  await page.reload();
  await card.waitFor();
  await card.click();
  assert.equal(
    await page.locator("#event-side").inputValue(),
    prediction.side,
    "An unknown side may use the compatible hitter's suggestion.",
  );
  assert.equal(await page.locator("#event-player").inputValue(), "A");
  const differentHitter = await json(`${root}/annotations`);
  differentHitter.events[0].player_id = "B";
  await json(`${root}/annotations`, { method: "PUT", data: differentHitter });
  await page.reload();
  await card.waitFor();
  await card.click();
  assert.equal(
    await page.locator("#event-side").inputValue(),
    "unknown",
    "A side suggestion for another hitter cannot fill this event.",
  );
  assert.equal(await page.locator("#event-player").inputValue(), "B");
  await page.setViewportSize({ width: 768, height: 1024 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
    true,
  );
  await page.locator("#recognition-tools").screenshot({
    path: fileURLToPath(new URL("recognition-tablet.png", output)),
  });
  await page.getByRole("button", { name: /doubles.mp4/ }).click();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "doubles.mp4",
  );
  assert.equal(await page.locator("#recognize").isDisabled(), true);
  assert.equal(await page.locator("[data-stroke]").count(), 0);
  assert.deepEqual(errors, []);
  console.log(
    "Recognition browser checks passed: real inference, explicit review/save, side preservation, score invalidation, immutable provenance, stale event, format switch and layout.",
  );
} finally {
  await browser.close();
}
