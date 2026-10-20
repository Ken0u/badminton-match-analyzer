/** Generated-media regression; refuses existing applications via startFixture. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import {
  repository,
  protocol,
  sha256,
  startFixture,
} from "./frontend-fixtures.mjs";

process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(
  repository,
  ".cache/ms-playwright",
);
const { chromium } = await import("playwright");
const legacyProbe = process.argv.includes("--probe-legacy");
await fs.mkdir(path.join(repository, ".cache/evidence"), { recursive: true });
const evidence = await fs.mkdtemp(
  path.join(repository, ".cache/evidence/manual-court-"),
);
console.log(`Manual court evidence: ${evidence}`);
const write = (name, data) =>
  fs.writeFile(path.join(evidence, name), JSON.stringify(data, null, 2) + "\n");
const observations = [],
  errors = [];
let fixture, browser, page, seeded, route, original;
async function helperChecks() {
  const {
    displayCalibrations,
    effectiveCalibrations,
    courtSignature,
    cameraContextChanged,
    courtContextChanged,
  } = await import("../backend/badminton/static/court-context.js");
  const calibration = (start = 0, end = 100) => ({
    start_frame: start,
    end_frame: end,
    corners: [
      { x: 0.2, y: 0.1 },
      { x: 0.8, y: 0.1 },
      { x: 0.8, y: 0.9 },
      { x: 0.2, y: 0.9 },
    ],
  });
  const doc = {
    calibrations: [calibration()],
    camera_corrections: [{ frame: 20, is_cut: true }],
  };
  const run = {
    start_frame: 0,
    end_frame: 100,
    cut_frames: [],
    raw_cut_frames: [],
    known_preceding_cut_frames: [],
    applied_camera_corrections: [],
    automatic_calibrations: [calibration()],
  };
  const before = JSON.stringify({ doc, run });
  let rangeCases = 0;
  const ranges = (doc, run, options) => {
    rangeCases++;
    return displayCalibrations(doc, run, options).map((c) => [
      c.start_frame,
      c.end_frame,
      !!c.automatic,
    ]);
  };
  assert.deepEqual(ranges(doc, null), [[0, 20, false]]);
  assert.deepEqual(ranges(doc, run), [[0, 20, false]]);
  // Exact original persisted signature semantics remain independent of the
  // display-only change, including the legacy (no context-version) contract.
  assert.equal(effectiveCalibrations(doc, run)[0].end_frame, 100);
  assert.equal(courtSignature(doc, run, 0, 100)[0][1], 100);
  assert.equal(
    courtSignature(
      doc,
      { ...run, court_context_version: 1, cut_frames: [40] },
      0,
      100,
    )[0][1],
    40,
  );
  assert.equal(cameraContextChanged(doc, run), true);
  assert.equal(
    courtContextChanged(doc, {
      court_context: run,
      calibration_signature: courtSignature(doc, run, 0, 100),
    }),
    true,
  );
  const notCut = { ...doc, camera_corrections: [{ frame: 20, is_cut: false }] };
  assert.deepEqual(
    ranges(notCut, { ...run, raw_cut_frames: [20], cut_frames: [20] }),
    [[0, 100, false]],
  );
  // Removing a once-applied correction restores raw predictions, not yesterday's
  // corrected cut_frames. An actual raw cut still survives correction removal.
  assert.deepEqual(
    ranges(
      { ...doc, camera_corrections: [] },
      {
        ...run,
        cut_frames: [20, 40],
        raw_cut_frames: [40],
        applied_camera_corrections: [{ frame: 20, is_cut: true }],
      },
    ),
    [[0, 40, false]],
  );
  const previous = {
    ...run,
    start_frame: 50,
    cut_frames: [70],
    raw_cut_frames: [70],
    known_preceding_cut_frames: [10, 30],
    preceding_reviewed_cut_frame: 30,
    known_preceding_timestamp_gaps: [10],
  };
  assert.deepEqual(ranges({ ...doc, camera_corrections: [] }, previous), [
    [0, 10, false],
  ]);
  assert.deepEqual(
    ranges(
      { calibrations: [calibration(20)], camera_corrections: [] },
      previous,
    ),
    [[20, 30, false]],
  );
  assert.deepEqual(
    ranges(
      {
        calibrations: [calibration(20)],
        camera_corrections: [{ frame: 30, is_cut: false }],
      },
      previous,
    ),
    [[20, 70, false]],
  );
  assert.deepEqual(
    ranges(
      { ...doc, camera_corrections: [{ frame: 10, is_cut: false }] },
      previous,
    ),
    [[0, 10, false]],
  );
  assert.deepEqual(
    ranges(
      { ...doc, camera_corrections: [] },
      { ...run, raw_cut_frames: [40] },
    ),
    [[0, 40, false]],
  );
  const gapOptions = { times: [0, 0.04, 0.08, 0.68], fps: 25 };
  assert.deepEqual(
    ranges(
      {
        calibrations: [calibration(0, 4)],
        camera_corrections: [{ frame: 3, is_cut: false }],
      },
      null,
      gapOptions,
    ),
    [[0, 3, false]],
  );
  assert.deepEqual(
    ranges(
      { calibrations: [calibration(0, 4)], camera_corrections: [] },
      null,
      { times: [0, 0.04, 0.12, 0.16], fps: 25 },
    ),
    [[0, 4, false]],
  );
  assert.deepEqual(
    ranges(
      {
        calibrations: [calibration(0, 10)],
        camera_corrections: doc.camera_corrections,
      },
      null,
    ),
    [[0, 10, false]],
  );
  assert.deepEqual(
    ranges(
      {
        calibrations: [calibration(0, 20), calibration(20, 60)],
        camera_corrections: doc.camera_corrections,
      },
      null,
    ),
    [
      [0, 20, false],
      [20, 60, false],
    ],
  );
  const auto = { ...run, court_context_version: 1 };
  assert.deepEqual(
    ranges({ calibrations: [], camera_corrections: [] }, auto),
    [],
  );
  assert.deepEqual(
    ranges(
      { calibrations: [calibration(25, 75)], camera_corrections: [] },
      auto,
      { automaticValid: true },
    ),
    [
      [0, 25, true],
      [25, 75, false],
      [75, 100, true],
    ],
  );
  assert.deepEqual(
    ranges(
      { ...doc, camera_corrections: [{ frame: 40, is_cut: true }] },
      {
        ...auto,
        cut_frames: [40],
        raw_cut_frames: [40],
        automatic_calibrations: [calibration(40)],
      },
      { automaticValid: true },
    ),
    [
      [0, 40, false],
      [40, 100, true],
    ],
  );
  assert.equal(
    JSON.stringify({ doc, run }),
    before,
    "Display and signature helpers preserve input records",
  );
  await write("helper-checks.json", {
    passed: true,
    rangeCases,
    sourceContextAssertions: 5,
    signatureCompatibility: true,
    noMutation: true,
  });
}
async function api(suffix, options) {
  const response = await page.request.fetch(fixture.base + suffix, options);
  assert.ok(response.ok(), `${response.status()} ${await response.text()}`);
  return response.json();
}
async function select() {
  await page.goto(fixture.base);
  await page.locator(`[data-video="${seeded.rally.id}"]`).click();
  await page.waitForFunction(
    () => document.querySelector("#title").textContent === "rally-qa.mp4",
  );
  await page.locator("#show-tracks").uncheck();
  await page.locator("#show-shuttle").uncheck();
  await page.locator("#camera-panel").evaluate((el) => {
    el.open = true;
  });
}
async function exact(frame) {
  await page.locator("#frame-number").fill(String(frame));
  await page.locator("#frame-number").dispatchEvent("change");
  await page.waitForFunction((frame) => {
    const img = document.querySelector("#exact-frame");
    return (
      img.src.endsWith(`index=${frame}`) &&
      !img.hidden &&
      img.complete &&
      img.naturalWidth === 1000
    );
  }, frame);
}
async function observe(name, frame, expected, polygon) {
  await exact(frame);
  const result = await page.evaluate(() => {
    const canvas = document.querySelector("#overlay");
    const rgba = canvas
      .getContext("2d")
      .getImageData(0, 0, canvas.width, canvas.height).data;
    let green = 0;
    for (let i = 0; i < rgba.length; i += 4)
      if (
        rgba[i] === 181 &&
        rgba[i + 1] === 239 &&
        rgba[i + 2] === 145 &&
        rgba[i + 3] > 0
      )
        green++;
    return {
      status: document.querySelector("#court-status").textContent,
      greenPixels: green,
      frame: Number(document.querySelector("#frame-number").value),
      sourceImage: document.querySelector("#exact-frame").src,
    };
  });
  observations.push({ name, ...result });
  await write("observations.json", observations);
  assert.equal(result.status, expected, name);
  assert.equal(
    result.greenPixels > 0,
    polygon,
    `${name}: actual court canvas pixels`,
  );
  await page.screenshot({ path: path.join(evidence, `${name}.png`) });
  await page
    .locator("#stage")
    .screenshot({ path: path.join(evidence, `${name}-court.png`) });
}
async function correction(decision = "cut", frame = 20) {
  await page.locator("#camera-frame").fill(String(frame));
  await page.locator("#camera-decision").selectOption(decision);
  await page.locator("#camera-apply").click();
  assert.equal(await page.locator("#save").isEnabled(), true);
}
async function save() {
  await page.locator("#save").click();
  await page.waitForFunction(() => document.querySelector("#save").disabled);
  assert.equal(
    await page
      .locator("#notice")
      .evaluate((el) => el.classList.contains("error")),
    false,
    await page.locator("#notice").textContent(),
  );
}
async function unchanged(name) {
  const saved = await api(route + "/annotations");
  assert.deepEqual(saved.calibrations, original.calibrations, name);
  assert.deepEqual(saved.events, original.events);
  let exported;
  if (await page.locator("#save").isEnabled()) {
    // The UI intentionally blocks exporting a draft. The export API still
    // exposes the unchanged saved record, rather than display-effective ranges.
    await page.locator("#export-json").click();
    assert.match(await page.locator("#notice").textContent(), /Save/);
    exported = await api(route + "/export?format=json");
    await write(`${name}-export.json`, exported);
  } else {
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#export-json").click(),
    ]);
    const target = path.join(evidence, `${name}-export.json`);
    await download.saveAs(target);
    exported = JSON.parse(await fs.readFile(target, "utf8"));
  }
  assert.deepEqual(exported.annotations.calibrations, original.calibrations);
  assert.equal(exported.video.sha256, seeded.rally.sha256);
  assert.deepEqual(exported.annotations.events, original.events);
  await write(`${name}-annotations.json`, saved);
}
try {
  if (!legacyProbe) await helperChecks();
  fixture = await startFixture(evidence);
  seeded = await fixture.control("seed");
  route = `/api/videos/${seeded.rally.id}`;
  browser = await chromium.launch({ headless: true, channel: "chromium" });
  page = await browser.newPage({ viewport: protocol.viewport });
  page.setDefaultTimeout(15000);
  page.on("pageerror", (error) => errors.push(error.message));
  await write("source-manifest.json", await fixture.control("manifest", "GET"));
  const sources = {};
  for (const name of ["app.js", "court-context.js"])
    sources[name] = sha256(
      await fs.readFile(
        path.join(repository, "backend/badminton/static", name),
      ),
    );
  await write("environment.json", {
    browser: browser.version(),
    sources,
    legacyProbe,
  });
  original = await api(route + "/annotations");
  const artifacts = {};
  for (const name of ["qa-players", "qa-shuttle"])
    artifacts[name] = sha256(
      await fs.readFile(
        path.join(
          fixture.root,
          "processed",
          seeded.rally.id,
          "runs",
          `${name}.json`,
        ),
      ),
    );
  await write("original-artifact-hashes.json", artifacts);
  await select();
  await page.waitForFunction(() =>
    document
      .querySelector("#track-status")
      .textContent.includes("synthetic_qa"),
  );
  await observe("initial-valid-run", 30, "Calibrated · frames 0–99", true);
  await correction();
  if (legacyProbe) {
    await save();
    await observe(
      "legacy-saved-cut-stale-run",
      30,
      "Calibrated · frames 0–99",
      true,
    );
    assert.equal(
      (await api(route + "/runs/qa-players")).requires_tracking_rerun,
      true,
    );
    await unchanged("legacy-unchanged");
  } else {
    await observe("draft-before-cut", 19, "Calibrated · frames 0–19", true);
    await observe("draft-at-cut", 20, "No calibration for this frame", false);
    await observe(
      "draft-after-cut",
      30,
      "No calibration for this frame",
      false,
    );
    await unchanged("draft-unchanged");
    await save();
    assert.equal(
      (await api(route + "/runs/qa-players")).requires_tracking_rerun,
      true,
    );
    const stale = await page.request.post(fixture.base + route + "/rallies", {
      data: { player_run_id: "qa-players", shuttle_run_id: "qa-shuttle" },
    });
    assert.equal(stale.status(), 422);
    await select();
    await observe(
      "saved-reloaded-before-cut",
      19,
      "Calibrated · frames 0–19",
      true,
    );
    await observe(
      "saved-reloaded-at-cut",
      20,
      "No calibration for this frame",
      false,
    );
    await observe(
      "saved-reloaded-after-cut",
      99,
      "No calibration for this frame",
      false,
    );
    await unchanged("saved-unchanged");
    await correction("not_cut");
    await observe("draft-not-cut", 30, "Calibrated · frames 0–99", true);
    await save();
    await select();
    await observe("saved-not-cut", 30, "Calibrated · frames 0–99", true);
    await page.locator('[data-reset-cut="20"]').click();
    await observe("removed-not-cut", 30, "Calibrated · frames 0–99", true);
    await correction();
    await observe("cut-reapplied", 20, "No calibration for this frame", false);
    await page.locator('[data-reset-cut="20"]').click();
    await observe("removed-cut", 30, "Calibrated · frames 0–99", true);
    await save();

    // Hide generated tracking jobs at the HTTP boundary to exercise state.run=null
    // without rewriting or deleting the saved predictions or job catalog.
    let noRunResponses = 0;
    await page.route("**/api/jobs**", async (request) => {
      const response = await request.fetch();
      const jobs = await response.json();
      assert.ok(Array.isArray(jobs));
      noRunResponses++;
      await request.fulfill({
        response,
        json: jobs.filter((job) => !["players", "shuttle"].includes(job.kind)),
      });
    });
    await select();
    assert.equal(
      await page.locator("#track-status").textContent(),
      "No tracking run loaded",
    );
    await correction();
    await observe("no-run-before-cut", 19, "Calibrated · frames 0–19", true);
    await observe("no-run-at-cut", 20, "No calibration for this frame", false);
    await observe(
      "no-run-after-cut",
      30,
      "No calibration for this frame",
      false,
    );
    await save();
    await select();
    await observe(
      "no-run-reloaded",
      30,
      "No calibration for this frame",
      false,
    );
    await unchanged("no-run-unchanged");
    await page.locator('[data-reset-cut="20"]').click();
    await observe("no-run-removed-cut", 30, "Calibrated · frames 0–99", true);
    await save();
    assert.ok(noRunResponses > 0);
    await page.unroute("**/api/jobs**");

    // Actual editor makes two explicitly applicable, adjacent half-open records.
    await page.locator("#court-start").fill("0");
    await page.locator("#court-end").fill("100");
    await page.locator("#clear-court").click();
    async function calibrate(start, end) {
      await page.locator("#court-start").fill(String(start));
      await page.locator("#court-end").fill(String(end));
      await page.locator("#calibrate").click();
      const bounds = await page.locator("#overlay").boundingBox();
      for (const [x, y] of [
        [0.2, 0.1],
        [0.8, 0.1],
        [0.8, 0.9],
        [0.2, 0.9],
      ])
        await page
          .locator("#overlay")
          .click({ position: { x: x * bounds.width, y: y * bounds.height } });
    }
    await calibrate(0, 20);
    await observe(
      "explicit-expiry-before",
      19,
      "Calibrated · frames 0–19",
      true,
    );
    await observe(
      "explicit-expiry-at",
      20,
      "No calibration for this frame",
      false,
    );
    await calibrate(20, 60);
    await correction();
    await save();
    await select();
    await observe("replacement-at-cut", 20, "Calibrated · frames 20–59", true);
    await observe(
      "replacement-last-frame",
      59,
      "Calibrated · frames 20–59",
      true,
    );
    await observe(
      "replacement-expired",
      60,
      "No calibration for this frame",
      false,
    );
    const explicit = await api(route + "/annotations");
    assert.deepEqual(
      explicit.calibrations.map((c) => [c.start_frame, c.end_frame]),
      [
        [0, 20],
        [20, 60],
      ],
    );
    await api(route + "/annotations", {
      method: "PUT",
      data: {
        ...explicit,
        calibrations: original.calibrations,
        camera_corrections: [],
      },
    });
    await select();
    const automatic = await fixture.control("automatic");
    await select();
    await page.waitForFunction(() =>
      document
        .querySelector("#court-status")
        .textContent.includes("Auto-detected"),
    );
    await observe(
      "valid-automatic",
      30,
      "Auto-detected · unreviewed · frames 0–99",
      true,
    );
    await correction();
    await observe(
      "stale-automatic-before-cut",
      19,
      "No calibration for this frame",
      false,
    );
    await observe(
      "stale-automatic-after-cut",
      30,
      "No calibration for this frame",
      false,
    );
    assert.equal((await api(route + "/annotations")).calibrations.length, 0);
    assert.deepEqual(automatic.original_calibrations, original.calibrations);
  }
  for (const [name, expected] of Object.entries(artifacts))
    assert.equal(
      sha256(
        await fs.readFile(
          path.join(
            fixture.root,
            "processed",
            seeded.rally.id,
            "runs",
            `${name}.json`,
          ),
        ),
      ),
      expected,
    );
  assert.deepEqual(errors, []);
  await write("result.json", {
    passed: true,
    legacyProbe,
    observations: observations.length,
    immutableArtifacts: artifacts,
    errors,
  });
  console.log(
    `PASS ${legacyProbe ? "historical gap reproduced" : "manual court boundary regression"} (${observations.length} canvas/status observations)`,
  );
} catch (error) {
  await write("failure.json", { error: error.stack, errors });
  throw error;
} finally {
  await browser?.close();
  await fixture?.stop();
}
