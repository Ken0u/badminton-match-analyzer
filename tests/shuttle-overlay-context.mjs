/** Generated actual-canvas regression shared by editor and production checks. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";

// Serialized into the browser by Playwright; keep this function self-contained.
export function recordShuttlePath() {
  window.shuttlePath = [];
  for (const method of ["moveTo", "lineTo"]) {
    const original = CanvasRenderingContext2D.prototype[method];
    CanvasRenderingContext2D.prototype[method] = function (x, y) {
      if (this.canvas.id === "overlay" && this.strokeStyle === "#ffd379")
        window.shuttlePath.push({ method, x, y });
      return original.call(this, x, y);
    };
  }
  const clear = CanvasRenderingContext2D.prototype.clearRect;
  CanvasRenderingContext2D.prototype.clearRect = function (...args) {
    if (this.canvas.id === "overlay") window.shuttlePath = [];
    return clear.apply(this, args);
  };
}

export async function checkShuttleContextOverlay({
  page,
  api,
  rallyRoot,
  video,
  reloadSelected,
  exact,
  rawPredictionPaths,
  predictionHashes,
  sha256,
}) {
  const saved = await api(rallyRoot + "/annotations");
  const manual = saved.shuttle_points.find((point) => point.frame === 10);
  assert.ok(manual?.visible);
  const runRoute = `**${rallyRoot}/runs/qa-shuttle*`;
  const annotationRoute = `**${rallyRoot}/annotations`;
  let mode = "continuous";
  const observations = async (route) => {
    const response = await route.fetch();
    const run = await response.json();
    run.raw_cut_frames = mode === "cut" ? [10] : [];
    run.cut_frames = [...run.raw_cut_frames];
    run.frames = run.frames.map((row) => ({
      ...row,
      shuttle: { visible: true, x: 100 + row.frame * 20, y: 200 },
    }));
    await route.fulfill({ response, json: run });
  };
  const scenes = async (route) => {
    const response = await route.fetch();
    const document = await response.json();
    if (mode === "scene")
      document.scene_ranges = [
        {
          id: "generated-trail-scene",
          start_frame: 10,
          end_frame: 15,
          scene: "replay",
          notes: "Generated overlay test only",
        },
      ];
    await route.fulfill({ response, json: document });
  };
  await page.route(runRoute, observations);
  await page.route(annotationRoute, scenes);
  const receipts = [];
  try {
    for (mode of ["continuous", "cut", "scene"]) {
      await reloadSelected(video);
      await page.locator("#show-tracks").uncheck();
      await page.locator("#show-shuttle").check();
      await page.evaluate(() => {
        window.baselineArcs = [];
      });
      await exact(10);
      await page.waitForFunction(() =>
        window.shuttlePath.some((point) => point.x === 300 && point.y === 200),
      );
      const path = await page.evaluate(() => window.shuttlePath);
      if (mode === "continuous") {
        assert.ok(
          path.some((point) => point.method === "lineTo" && point.x === 300),
        );
        assert.ok(path.some((point) => point.x < 300));
      } else {
        assert.deepEqual(path, [{ method: "moveTo", x: 300, y: 200 }]);
      }
      assert.ok(
        await page.evaluate(
          (point) =>
            window.baselineArcs.some(
              (arc) =>
                arc.frame === 10 &&
                Math.abs(arc.x - point.x * 1000) < 0.01 &&
                Math.abs(arc.y - point.y * 600) < 0.01,
            ),
          manual,
        ),
      );
      await page.evaluate(() => {
        window.baselineArcs = [];
      });
      await page.locator("#show-shuttle").uncheck();
      await page.waitForFunction(() => window.shuttlePath.length === 0);
      assert.ok(
        await page.evaluate(
          (point) =>
            window.baselineArcs.some(
              (arc) =>
                arc.frame === 10 &&
                Math.abs(arc.x - point.x * 1000) < 0.01 &&
                Math.abs(arc.y - point.y * 600) < 0.01,
            ),
          manual,
        ),
      );
      await page.locator("#show-shuttle").check();
      await page.waitForFunction(() => window.shuttlePath.length > 0);
      assert.deepEqual(await page.evaluate(() => window.shuttlePath), path);
      receipts.push({
        mode,
        path,
        manualMarkerPreserved: true,
        overlayTogglePreserved: true,
      });
    }
  } finally {
    await page.unroute(runRoute, observations);
    await page.unroute(annotationRoute, scenes);
    await reloadSelected(video);
    await page.locator("#show-tracks").check();
  }
  assert.deepEqual(await api(rallyRoot + "/annotations"), saved);
  assert.deepEqual(
    await Promise.all(
      rawPredictionPaths.map(async (p) => sha256(await fs.readFile(p))),
    ),
    predictionHashes,
  );
  return { receipts, savedAnnotationsAndOriginalPredictionsUnchanged: true };
}
