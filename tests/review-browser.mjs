import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import { fileURLToPath } from "node:url";

const base = process.env.BASE_URL || "http://127.0.0.1:8001";
assert.equal(
  new URL(base).port,
  "8001",
  "Review fixtures must use the isolated QA server on port 8001.",
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

async function seek(frame) {
  await page.locator("#frame-number").fill(String(frame));
  await page.locator("#frame-number").dispatchEvent("change");
  await page.waitForFunction((index) => {
    const image = document.querySelector("#exact-frame");
    return (
      image.src.endsWith(`index=${index}`) &&
      !image.hidden &&
      image.complete &&
      image.naturalWidth > 0
    );
  }, frame);
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
  const singles = videos.find((video) => video.mode === "singles");
  const doubles = videos.find((video) => video.mode === "doubles");
  assert.ok(
    singles && doubles,
    "Both sample videos are required for review UI checks.",
  );
  const root = `/api/videos/${singles.id}`;
  const previous = await json(`${root}/annotations`);
  await json(`${root}/annotations`, {
    method: "PUT",
    data: {
      ...previous,
      events: [],
      review_windows: [],
      shuttle_points: [],
      track_assignments: [],
    },
  });
  const doublesDoc = await json(`/api/videos/${doubles.id}/annotations`);
  await page.goto(base);
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "singles.mp4",
  );
  await page.waitForFunction(
    () =>
      document
        .querySelector("#track-status")
        .textContent.includes("250 frames") &&
      document
        .querySelector("#shuttle-status")
        .textContent.includes("250 frames") &&
      Number(document.querySelector("#candidate-count").textContent) > 0,
  );
  assert.equal(await page.locator("#event-count").textContent(), "0 events");

  await page.locator("#identity-panel summary").click();
  await page.waitForFunction(
    () => document.querySelector("#identity-track").options.length > 0,
  );
  const track = Number(await page.locator("#identity-track").inputValue());
  await page.locator("#identity-player").selectOption("A");
  await page.locator("#identity-start").fill("2000");
  await page.locator("#identity-end").fill("2250");
  await page.locator("#assign-identity").click();
  assert.equal(await page.locator("#identity-list .review-row").count(), 1);
  await save();
  const savedIdentity = await json(`${root}/annotations`);
  const mapping = savedIdentity.track_assignments[0];
  assert.deepEqual(
    { ...mapping, run_id: "loaded-run" },
    {
      start_frame: 2000,
      end_frame: 2250,
      run_id: "loaded-run",
      track_id: track,
      player_id: "A",
    },
  );
  const players = await json(`${root}/runs/${mapping.run_id}`);
  const assigned = players.frames.flatMap((row) =>
    row.players.filter((player) => player.track_id === track),
  );
  assert.ok(assigned.length > 0);
  assert.ok(assigned.every((player) => player.player_id === "A"));
  assert.equal(players.identity_annotation_revision, savedIdentity.revision);

  await page.locator("#review-panel summary").click();
  await seek(2004);
  await page.locator("#label-shuttle").click();
  assert.equal(
    await page.locator("#show-shuttle").isChecked(),
    false,
    "Manual labeling hides model positions.",
  );
  const overlay = page.locator("#overlay");
  const bounds = await overlay.boundingBox();
  assert.ok(bounds);
  // Deliberately synthetic QA positions, never ground truth for real sample data.
  await overlay.click({
    position: { x: bounds.width * 0.45, y: bounds.height * 0.35 },
  });
  await seek(2005);
  await page.locator("#label-invisible").click();
  await page.locator("#review-start").fill("2000");
  await page.locator("#review-end").fill("2100");
  await page.locator("#review-scene").selectOption("live");
  await page.locator("#review-complete").check();
  await page
    .locator("#review-notes")
    .fill(
      "QA ONLY: synthetic labels and empty contact set for interface tests; not badminton ground truth.",
    );
  await page.locator("#add-review").click();
  await save();

  const exported = await json(`${root}/export`);
  const labels = exported.annotations.shuttle_points;
  assert.equal(labels.length, 2);
  const visible = labels.find((point) => point.frame === 2004);
  const invisible = labels.find((point) => point.frame === 2005);
  assert.equal(visible.visible, true);
  assert.ok(Math.abs(visible.x - 0.45) < 0.003);
  assert.ok(Math.abs(visible.y - 0.35) < 0.003);
  assert.deepEqual(invisible, {
    frame: 2005,
    visible: false,
    x: null,
    y: null,
    notes: "",
  });
  assert.deepEqual(
    exported.annotations.review_windows.map(
      ({ start_frame, end_frame, scene, contacts_complete }) => ({
        start_frame,
        end_frame,
        scene,
        contacts_complete,
      }),
    ),
    [
      {
        start_frame: 2000,
        end_frame: 2100,
        scene: "live",
        contacts_complete: true,
      },
    ],
  );
  assert.equal(exported.annotations.events.length, 0);

  await page.locator("#evaluate").click();
  await page.waitForFunction(
    () => !document.querySelector("#download-evaluation").hidden,
  );
  assert.match(
    await page.locator("#evaluation-results").textContent(),
    /Contacts F1/,
  );
  assert.match(
    await page.locator("#evaluation-results").textContent(),
    /Shuttle F1/,
  );
  assert.match(
    await page.locator("#evaluation-results").textContent(),
    /0 reviewed contacts/,
  );
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.locator("#download-evaluation").click(),
  ]);
  const reportFile = fileURLToPath(
    new URL("review-evaluation-fixture.json", output),
  );
  await download.saveAs(reportFile);
  const report = JSON.parse(await fs.readFile(reportFile, "utf8"));
  assert.equal(report.annotation_revision, exported.annotations.revision);
  assert.equal(report.contacts.status, "scored");
  assert.equal(report.contacts.coverage.reviewed_frames, 100);
  assert.equal(report.contacts.coverage.reviewed_contacts, 0);
  assert.ok(report.contacts.metrics.fp > 0);
  assert.equal(report.shuttle.coverage.labeled_frames, 2);
  await page.screenshot({
    path: fileURLToPath(new URL("review-tools-desktop.png", output)),
    fullPage: true,
  });

  // A mode that was waiting for a click must not label the next selected video.
  await page.locator("#label-shuttle").click();
  await page.getByRole("button", { name: /doubles.mp4/ }).click();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "doubles.mp4",
  );
  await page.waitForFunction(
    () =>
      document
        .querySelector("#track-status")
        .textContent.includes("250 frames") &&
      document
        .querySelector("#shuttle-status")
        .textContent.includes("250 frames"),
  );
  await seek(doubles.review_start_frame || 0);
  assert.equal(
    await page.locator("#label-shuttle").textContent(),
    "Mark visible shuttle",
  );
  assert.equal(await page.locator("#review-complete").isChecked(), false);
  assert.equal(await page.locator("#review-scene").inputValue(), "unknown");
  assert.equal(await page.locator("#review-notes").inputValue(), "");
  assert.equal(
    await page.locator("#review-start").inputValue(),
    String(doubles.review_start_frame || 0),
  );
  assert.equal(await page.locator("#download-evaluation").isHidden(), true);
  assert.equal(
    await page.locator("#identity-list .review-row").count(),
    doublesDoc.track_assignments.length,
  );
  assert.equal(
    await page.locator("#review-list .review-row").count(),
    doublesDoc.review_windows.length,
  );
  assert.match(
    await page.locator("#shuttle-label-status").textContent(),
    new RegExp(`^${doublesDoc.shuttle_points.length} labeled frames`),
  );
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.screenshot({
    path: fileURLToPath(new URL("review-tools-tablet.png", output)),
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
    "Review UI checks passed: reviewed identity, exact-frame shuttle labels, synthetic QA coverage, saved-revision metrics/download, selection reset, tablet layout.",
  );
} finally {
  await browser.close();
}
