import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:8001";
assert.equal(
  new URL(base).port,
  "8001",
  "Contact interval fixtures must use isolated port 8001.",
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
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  assert.equal(
    await page
      .locator("#notice")
      .evaluate((element) => element.classList.contains("error")),
    false,
  );
}

try {
  const videos = await json("/api/videos");
  const singles = videos.find((video) => video.name === "singles.mp4");
  assert.ok(singles, "The isolated sample catalog is required.");
  const root = `/api/videos/${singles.id}`;
  const doc = await json(`${root}/annotations`);
  await json(`${root}/annotations`, {
    method: "PUT",
    data: {
      ...doc,
      events: [],
      review_windows: [],
      shuttle_points: [],
      track_assignments: [],
    },
  });
  const jobs = await json(`/api/jobs?video_id=${singles.id}`);
  const shuttle = jobs.find(
    (job) =>
      job.kind === "shuttle" &&
      job.status === "completed" &&
      job.summary?.start_frame === 2000 &&
      job.summary?.end_frame === 2250,
  );
  const players = jobs.find(
    (job) =>
      job.kind === "players" &&
      job.status === "completed" &&
      job.summary?.image_size === 1280 &&
      job.summary?.start_frame === 2000 &&
      job.summary?.end_frame === 2250,
  );
  assert.ok(
    shuttle && players,
    "Cached 250-frame player and shuttle runs are required.",
  );
  const queued = await json(`${root}/contacts`, {
    method: "POST",
    data: { shuttle_run_id: shuttle.id, player_run_id: players.id },
  });
  let contactJob;
  for (let attempt = 0; attempt < 100; attempt++) {
    contactJob = (await json(`/api/jobs?video_id=${singles.id}`)).find(
      (job) => job.id === queued.id,
    );
    if (!["queued", "running"].includes(contactJob.status)) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  assert.equal(contactJob.status, "completed", contactJob.message);
  const run = await json(`${root}/runs/${queued.id}`);
  assert.equal(run.candidates.length, 5);
  const uncertain = run.candidates.find(
    (candidate) =>
      candidate.start_frame === 2076 && candidate.end_frame === 2080,
  );
  assert.ok(uncertain);
  assert.equal(uncertain.timing, "uncertain_interval");
  assert.equal(uncertain.frame, 2078);

  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent === "5",
  );
  const card = page
    .locator("#candidates .candidate-row")
    .filter({ hasText: "Frames 2076" });
  assert.match(await card.textContent(), /Review possible contact/);
  await card.click();
  assert.equal(await page.locator("#event-frame").inputValue(), "2078");
  assert.equal(await page.locator("#contact-start").inputValue(), "2076");
  assert.equal(await page.locator("#contact-end").inputValue(), "2080");
  assert.equal(
    await page
      .locator("#contact-uncertainty")
      .evaluate((details) => details.open),
    true,
  );
  assert.equal(await page.locator("#event-family").inputValue(), "unknown");
  assert.equal(await page.locator("#event-side").inputValue(), "unknown");
  assert.equal(await page.locator("#event-player").inputValue(), "");
  await page.locator("#rally-id").fill("QA-R-interval");
  await page
    .locator("#event-notes")
    .fill(
      "QA ONLY: synthetic interval review for browser testing; not badminton ground truth.",
    );

  // Moving the navigation frame cannot silently retain incompatible bounds.
  await page.locator("#event-frame").fill("2100");
  await page.locator("#apply-event").click();
  assert.match(
    await page.locator("#notice").textContent(),
    /including the event frame/,
  );
  assert.equal(await page.locator("#event-count").textContent(), "0 events");
  await page.locator("#event-frame").fill("2078");
  await page.locator("#apply-event").click();
  await save();
  const saved = await json(`${root}/export`);
  assert.equal(saved.annotations.events.length, 1);
  const event = saved.annotations.events[0];
  assert.equal(event.frame, 2078);
  assert.equal(event.contact_start_frame, 2076);
  assert.equal(event.contact_end_frame, 2080);
  assert.equal(event.source_run_id, queued.id);
  assert.equal(event.candidate_id, uncertain.id);
  assert.equal(event.family, "unknown");
  assert.equal(event.side, "unknown");
  assert.equal(event.player_id, null);
  const csvResponse = await page.request.get(
    `${base}${root}/export?format=csv`,
  );
  const csv = await csvResponse.text();
  assert.match(csv, /contact_start_frame/);
  assert.match(csv, /contact_end_frame/);
  assert.match(csv, /2076,2080/);

  await page.reload();
  await page.waitForFunction(
    () => document.querySelector("#event-count").textContent === "1 events",
  );
  await page.locator("#events .event-row").click();
  assert.equal(await page.locator("#contact-start").inputValue(), "2076");
  assert.equal(await page.locator("#contact-end").inputValue(), "2080");
  assert.equal(
    await page
      .locator("#contact-uncertainty")
      .evaluate((details) => details.open),
    true,
  );
  await page.waitForFunction(
    () => document.querySelector("#candidate-count").textContent === "5",
  );

  await page.locator("#review-panel summary").click();
  await page.locator("#review-start").fill("2000");
  await page.locator("#review-end").fill("2100");
  await page.locator("#review-scene").selectOption("live");
  await page.locator("#review-complete").check();
  await page
    .locator("#review-notes")
    .fill(
      "QA ONLY: synthetic exhaustive-coverage flag to test timing adjudication exclusion.",
    );
  await page.locator("#add-review").click();
  await save();
  const report = await json(`${root}/evaluate`, {
    method: "POST",
    data: { contacts_run_id: queued.id },
  });
  assert.equal(report.contacts.metrics, null);
  assert.ok(
    report.contacts.coverage.skipped_windows.some(
      (window) => window.reason === "contact_timing_needs_adjudication",
    ),
  );
  await page.locator("#evaluate").click();
  await page.waitForFunction(() =>
    document
      .querySelector("#evaluation-results")
      .textContent.includes("Contact timing needs review"),
  );
  assert.doesNotMatch(
    await page.locator("#evaluation-results").textContent(),
    /F1/,
  );
  await page.screenshot({
    path: fileURLToPath(new URL("contact-interval.png", output)),
    fullPage: true,
  });

  await page.locator("#clear-contact-interval").click();
  assert.equal(await page.locator("#contact-start").inputValue(), "");
  assert.equal(await page.locator("#contact-end").inputValue(), "");
  await page.locator("#apply-event").click();
  await save();
  const exact = (await json(`${root}/annotations`)).events[0];
  assert.equal(exact.frame, 2078);
  assert.equal(exact.contact_start_frame, null);
  assert.equal(exact.contact_end_frame, null);
  assert.equal(exact.source_run_id, queued.id);
  const originalPrediction = (
    await json(`${root}/runs/${queued.id}`)
  ).candidates.find((candidate) => candidate.id === uncertain.id);
  assert.equal(originalPrediction.start_frame, 2076);
  assert.equal(originalPrediction.end_frame, 2080);
  assert.equal(originalPrediction.timing, "uncertain_interval");
  assert.equal(await page.locator("#contact-audio").isChecked(), false);
  await page.locator("#contact-audio").check();
  const audioRequest = page.waitForRequest(
    (request) =>
      request.url().endsWith(`${root}/contacts`) && request.method() === "POST",
  );
  await page.locator("#detect-contacts").click();
  assert.equal((await audioRequest).postDataJSON().include_audio, true);
  await page.waitForFunction(() =>
    document
      .querySelector("#audio-status")
      .textContent.includes("experimental"),
  );
  assert.ok(
    await page
      .locator("#candidates .candidate-row")
      .filter({ hasText: "Audio hitter disagreement" })
      .count(),
  );
  const audioCard = page
    .locator("#candidates .candidate-row")
    .filter({ hasText: "Audio + vision" })
    .first();
  assert.ok(await audioCard.count());
  await audioCard.click();
  assert.ok(await page.locator("#contact-start").inputValue());
  assert.ok(await page.locator("#contact-end").inputValue());
  assert.equal(await page.locator("#event-family").inputValue(), "unknown");
  assert.equal(await page.locator("#event-side").inputValue(), "unknown");
  assert.match(
    await page.locator("#event-notes").inputValue(),
    /verify sound source/i,
  );
  await page.screenshot({
    path: fileURLToPath(new URL("audio-contacts.png", output)),
    fullPage: true,
  });
  assert.deepEqual(errors, []);
  console.log(
    "Contact browser checks passed: interval review, export, timing exclusion, immutable predictions, opt-in audio request and review.",
  );
} finally {
  await browser.close();
}
