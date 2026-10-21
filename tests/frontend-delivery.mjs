/** Production delivery: FastAPI assets and the complete frozen editor matrix. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
// Keep any newly downloaded test browser inside this task, never user Chrome.
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(
  repository,
  ".cache/ms-playwright",
);
const { chromium } = await import("playwright");
import {
  repository,
  python,
  protocol,
  sha256,
  startFixture,
} from "./frontend-fixtures.mjs";

const requestedModes = process.argv.slice(2);
const knownModes = new Set(["--exports", "--library"]);
for (const mode of requestedModes)
  assert.ok(knownModes.has(mode), `Unknown delivery mode: ${mode}`);
assert.ok(
  !(
    requestedModes.includes("--exports") && requestedModes.includes("--library")
  ),
  "Choose only one delivery mode",
);

if (requestedModes.includes("--exports")) {
  await runExportsMode();
} else if (requestedModes.includes("--library")) {
  await runLibraryMode();
} else {
  assert.ok(
    !process.env.BASE_URL,
    "Delivery check refuses existing applications",
  );
  const runtime = path.join(repository, "backend/badminton/static");
  await fs.access(path.join(runtime, "build-manifest.json"));
  const evidenceParent = path.join(repository, ".cache/evidence");
  await fs.mkdir(evidenceParent, { recursive: true });
  const evidence = await fs.mkdtemp(
    path.join(evidenceParent, "frontend-delivery-"),
  );
  console.log(`Frontend delivery evidence: ${evidence}`);
  const write = (name, data) =>
    fs.writeFile(
      path.join(evidence, name),
      JSON.stringify(data, null, 2) + "\n",
    );
  const hashes = {};
  for (const file of [
    "tests/frontend-fixtures.mjs",
    "tests/frontend-editor.mjs",
    "tests/frontend-delivery.mjs",
    "tests/frontend-parity.mjs",
    "tests/media_fixtures.py",
    "tests/rally_fixture.py",
    "scripts/pipeline_ui_test_server.py",
    "package-lock.json",
    "uv.lock",
    ...Object.keys(await treeHashes(runtime)).map(
      (file) => `backend/badminton/static/${file}`,
    ),
  ]) {
    hashes[file] = sha256(await fs.readFile(path.join(repository, file)));
  }
  await write("protocol.json", {
    ...protocol,
    sha256: sha256(JSON.stringify(protocol)),
    hashes,
    frozenBeforeMeasurement: true,
  });
  const checks = [],
    errors = [],
    latencies = {};
  let fixture, browser, page, seeded, oriented, youtube, rallyRoot, largeRoot;
  const releases = [],
    routeEvents = [];
  const p95 = (values) =>
    [...values].sort((a, b) => a - b)[Math.ceil(values.length * 0.95) - 1];
  async function check(name, action) {
    const start = Date.now();
    try {
      const result = await action();
      checks.push({
        name,
        status: "passed",
        durationMs: Date.now() - start,
        result,
      });
      console.log(`PASS ${name}`);
    } catch (error) {
      checks.push({
        name,
        status: "failed",
        durationMs: Date.now() - start,
        error: error.stack,
      });
      throw error;
    } finally {
      await write("checks.json", checks);
    }
  }
  async function api(route, options) {
    const response = await page.request.fetch(fixture.base + route, options);
    assert.ok(
      response.ok(),
      `${route}: ${response.status()} ${await response.text()}`,
    );
    return response.json();
  }
  async function selected(video) {
    await page.locator(`button[data-video="${video.id}"]`).click();
    await page.waitForFunction((video) => {
      const player = document.querySelector("#video");
      return (
        document.querySelector("#title").textContent === video.name &&
        player.currentSrc.includes(`/api/videos/${video.id}/`) &&
        (video.name === "long-gap-vfr.mkv" || player.readyState >= 2)
      );
    }, video);
    await page.evaluate(
      () =>
        new Promise((resolve) =>
          requestAnimationFrame(() => requestAnimationFrame(resolve)),
        ),
    );
  }
  async function exact(frame) {
    await page.locator("#frame-number").fill(String(frame));
    await page.locator("#frame-number").dispatchEvent("change");
    await imageReady(frame);
  }
  async function imageReady(frame, videoId) {
    await page.waitForFunction(
      ({ f, id }) => {
        const img = document.querySelector("#exact-frame");
        return (
          img.src.endsWith(`index=${f}`) &&
          (!id ||
            (img.dataset.video === id &&
              img.dataset.frame === String(f) &&
              new URL(img.src).pathname === `/api/videos/${id}/frame`)) &&
          !img.hidden &&
          img.complete &&
          img.naturalWidth > 0
        );
      },
      { f: frame, id: videoId },
    );
  }
  async function save() {
    const response = page.waitForResponse(
      (r) => r.url().endsWith("/annotations") && r.request().method() === "PUT",
    );
    await page.locator("#save").click();
    const saved = await response;
    assert.equal(saved.status(), 200, await saved.text());
    await saved.finished();
    await page.waitForFunction(() => document.querySelector("#save").disabled);
    assert.equal(
      await page
        .locator("#notice")
        .evaluate((el) => el.classList.contains("error")),
      false,
      await page.locator("#notice").textContent(),
    );
  }
  async function addShot(
    frame,
    notes = "Generated QA event",
    family = "unknown",
    side = "unknown",
  ) {
    await exact(frame);
    await page.locator('[data-mark="shot"]').click();
    await page.locator("#rally-id").fill("QA-manual");
    await page.locator("#event-family").selectOption(family);
    await page.locator("#event-side").selectOption(side);
    await page.locator("#event-notes").fill(notes);
    await page.locator("#apply-event").click();
  }
  async function reloadSelected(video) {
    await page.reload();
    await page.locator(`button[data-video="${video.id}"]`).waitFor();
    await selected(video);
  }
  async function waitJob(id, expected = "completed") {
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      const job = (await api("/api/jobs")).find((j) => j.id === id);
      if (job && !["queued", "running"].includes(job.status)) {
        assert.equal(job.status, expected, JSON.stringify(job));
        return job;
      }
      await page.waitForTimeout(100);
    }
    assert.fail(
      `Owned fixture job ${id} did not complete; artifacts preserved`,
    );
  }
  async function download(selector, name) {
    const [file] = await Promise.all([
      page.waitForEvent("download"),
      page.locator(selector).click(),
    ]);
    const target = path.join(evidence, name);
    await file.saveAs(target);
    return fs.readFile(target, "utf8");
  }
  // RFC4180, including escaped quotes/newlines in annotation notes.
  function csv(text) {
    const rows = [];
    let row = [],
      value = "",
      quoted = false;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === '"') {
        if (quoted && text[i + 1] === '"') {
          value += '"';
          i++;
        } else quoted = !quoted;
      } else if (ch === "," && !quoted) {
        row.push(value);
        value = "";
      } else if (ch === "\n" && !quoted) {
        row.push(value.replace(/\r$/, ""));
        rows.push(row);
        row = [];
        value = "";
      } else value += ch;
    }
    return rows
      .slice(1)
      .map((values) =>
        Object.fromEntries(rows[0].map((name, i) => [name, values[i]])),
      );
  }

  async function continueOwnedRoute(route) {
    try {
      await route.continue();
    } catch (error) {
      const expectedCancellation =
        /already handled|has been closed|Target.*closed|cancelled|Invalid InterceptionId/i.test(
          error.message,
        );
      routeEvents.push({ message: error.message, expectedCancellation });
      if (!expectedCancellation) errors.push(error.message);
    }
  }
  async function treeHashes(folder) {
    const out = {};
    for (const entry of await fs.readdir(folder, { withFileTypes: true })) {
      const file = path.join(folder, entry.name);
      if (entry.isFile()) out[entry.name] = sha256(await fs.readFile(file));
      else if (entry.isDirectory())
        for (const [key, hash] of Object.entries(await treeHashes(file)))
          out[`${entry.name}/${key}`] = hash;
    }
    return out;
  }
  async function upload(name, mode = "singles") {
    const response = await page.request.post(fixture.base + "/api/upload", {
      multipart: {
        mode,
        file: {
          name,
          mimeType: "application/octet-stream",
          buffer: await fs.readFile(path.join(fixture.root, name)),
        },
      },
    });
    assert.ok(response.ok(), await response.text());
    const job = await response.json();
    await waitJob(job.id);
    return job;
  }

  try {
    fixture = await startFixture(evidence);
    await write("listeners.json", {
      backend: fixture.receipt,
      application: fixture.base,
      delivery:
        "Production FastAPI serves both UI and API; no frontend listener",
    });
    browser = await chromium.launch({ headless: true, channel: "chromium" });
    page = await browser.newPage({
      viewport: protocol.viewport,
      deviceScaleFactor: 1,
    });
    page.setDefaultTimeout(15000);
    page.on("pageerror", (error) => errors.push(error.message));
    await page.addInitScript(() => {
      window.baselineDraws = [];
      window.baselineArcs = [];
      const arc = CanvasRenderingContext2D.prototype.arc;
      CanvasRenderingContext2D.prototype.arc = function (x, y, ...rest) {
        if (this.canvas.id === "overlay")
          window.baselineArcs.push({
            frame: Number(document.querySelector("#frame-number").value),
            x,
            y,
          });
        return arc.call(this, x, y, ...rest);
      };
      const original = CanvasRenderingContext2D.prototype.clearRect;
      CanvasRenderingContext2D.prototype.clearRect = function (...args) {
        if (this.canvas.id === "overlay")
          window.baselineDraws.push({
            frame: Number(document.querySelector("#frame-number").value),
            time: performance.now(),
          });
        return original.apply(this, args);
      };
    });
    const executable = chromium.executablePath();
    await write("environment.json", {
      collectedAt: new Date().toISOString(),
      host: os.hostname(),
      platform: os.platform(),
      release: os.release(),
      arch: os.arch(),
      cpu: os.cpus()[0].model,
      cores: os.cpus().length,
      totalMemory: os.totalmem(),
      node: process.version,
      browser: browser.version(),
      executable,
      executableSha256: sha256(await fs.readFile(executable)),
      viewport: protocol.viewport,
      frontendSource: await treeHashes(
        path.join(repository, "backend/frontend/src"),
      ),
      builtAssets: await treeHashes(runtime),
      python: execFileSync(
        python,
        [
          "-c",
          "import platform,importlib.metadata as m,json; print(json.dumps({'python':platform.python_version(),'packages':{n:m.version(n) for n in ['av','numpy','opencv-python','fastapi','uvicorn','psutil']}}))",
        ],
        { encoding: "utf8" },
      ).trim(),
      gitHead: execFileSync("git", ["rev-parse", "HEAD"], {
        cwd: repository,
        encoding: "utf8",
      }).trim(),
    });

    await check(
      "production routes, staged assets and default library",
      async () => {
        const manifestBytes = await fs.readFile(
          path.join(runtime, "build-manifest.json"),
        );
        const manifest = JSON.parse(manifestBytes);
        assert.equal(manifest.schema_version, 1);
        assert.match(manifest.input_fingerprint, /^sha256:[a-f0-9]{64}$/);
        const inputEntries = Object.entries(manifest.inputs);
        assert.ok(inputEntries.length > 0);
        assert.deepEqual(
          inputEntries.map(([name]) => name),
          inputEntries.map(([name]) => name).sort(),
        );
        const fingerprint = sha256(
          Buffer.from(
            inputEntries.map(([name, hash]) => `${name}\0${hash}\n`).join(""),
          ),
        );
        assert.equal(manifest.input_fingerprint, `sha256:${fingerprint}`);
        for (const [name, hash] of inputEntries) {
          assert.ok(
            !name.startsWith("/") &&
              !name.includes("\\") &&
              !name
                .split("/")
                .some((part) => !part || part === "." || part === ".."),
          );
          assert.match(hash, /^[a-f0-9]{64}$/);
          assert.equal(
            sha256(await fs.readFile(path.join(repository, name))),
            hash,
            `Stale build input ${name}`,
          );
        }
        const assetNames = Object.keys(manifest.assets);
        assert.ok(assetNames.includes("index.html"));
        assert.ok(assetNames.includes("app.js"));
        assert.ok(assetNames.includes("style.css"));
        assert.deepEqual(
          Object.keys(await treeHashes(runtime)).sort(),
          [...assetNames, "build-manifest.json"].sort(),
        );
        for (const name of [...assetNames, "build-manifest.json"]) {
          assert.ok(
            !name.startsWith("/") &&
              !name.includes("\\") &&
              !name
                .split("/")
                .some((part) => !part || part === "." || part === ".."),
          );
          assert.doesNotMatch(
            name,
            /(^|\/)(src|scripts|tests|node_modules)(\/|$)|\.(?:map|tsx?|jsx)$/i,
          );
          const expected = await fs.readFile(path.join(runtime, name));
          const response = await page.request.get(fixture.base + "/" + name);
          assert.equal(response.status(), 200, name);
          assert.deepEqual(
            await response.body(),
            expected,
            `Served bytes differ: ${name}`,
          );
          if (name !== "build-manifest.json")
            assert.equal(
              sha256(expected),
              manifest.assets[name],
              `Asset digest differs: ${name}`,
            );
          if (
            [
              "index.html",
              "app.js",
              "style.css",
              "build-manifest.json",
            ].includes(name)
          )
            assert.equal(
              response.headers()["cache-control"],
              "no-cache",
              `Mutable entry point must revalidate: ${name}`,
            );
          const contentType = response.headers()["content-type"];
          if (name.endsWith(".js")) assert.match(contentType, /javascript/);
          if (name.endsWith(".css")) assert.match(contentType, /^text\/css/);
        }
        const index = await fs.readFile(path.join(runtime, "index.html"));
        assert.match(index.toString(), /id="root"/);
        assert.doesNotMatch(
          index.toString(),
          /id="library"|Open legacy editor|Frontend foundation/,
        );
        for (const route of ["/", "/library", "/editor"]) {
          const response = await page.request.get(fixture.base + route);
          assert.equal(response.status(), 200, route);
          assert.match(response.headers()["content-type"], /^text\/html/);
          assert.equal(response.headers()["cache-control"], "no-cache");
          assert.deepEqual(await response.body(), index, route);
        }
        for (const route of [
          "/not-an-application-route",
          "/api/not-an-api-route",
          "/missing.js",
          "/src/main.tsx",
          "/node_modules/react/index.js",
          "/legacy",
          "/foundation",
          "/editor/not-a-route",
        ]) {
          const response = await page.request.get(fixture.base + route);
          assert.equal(
            response.status(),
            404,
            `SPA fallback swallowed ${route}`,
          );
        }
        for (const route of ["/", "/library"]) {
          await page.goto(fixture.base + route);
          await page.getByTestId("library").waitFor();
          await page
            .getByRole("heading", { name: "Match library", exact: true })
            .waitFor();
          await page
            .getByText("Automatic annotation accuracy is not established.", {
              exact: false,
            })
            .waitFor();
          assert.equal(
            await page.getByText("Open legacy editor", { exact: true }).count(),
            0,
          );
          const link = page.getByRole("link", {
            name: "Open review editor",
            exact: true,
          });
          await link.focus();
          assert.equal(
            await link.evaluate(
              (element) => element === document.activeElement,
            ),
            true,
          );
        }
        await page.screenshot({
          path: path.join(evidence, "default-library-desktop.png"),
          fullPage: true,
        });
        await page.setViewportSize({ width: 768, height: 1024 });
        assert.equal(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          true,
        );
        await page.screenshot({
          path: path.join(evidence, "default-library-tablet.png"),
          fullPage: true,
        });
        await page.setViewportSize(protocol.viewport);
        await write("delivery-assets.json", {
          manifest,
          application: fixture.base,
          authCoverage:
            "Real authenticated installed-wheel and container checks run separately; this generated parity fixture explicitly disables auth",
        });
        return {
          routes: ["/", "/library", "/editor"],
          assetCount: assetNames.length,
          unknownRoutesRemain404: true,
          sourceAndAssetHashes: true,
          defaultLibrary: true,
        };
      },
    );

    await check("imports and library handoff", async () => {
      // Exercise imports through the same FastAPI-served default library users open.
      assert.deepEqual(await api("/api/videos"), []);
      await page.goto(fixture.base);
      await page.getByTestId("library").waitFor();
      await page
        .getByLabel("Video file", { exact: true })
        .setInputFiles(path.join(fixture.root, "invalid.mp4"));
      const invalid = page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/upload") &&
          response.request().method() === "POST",
      );
      await page
        .getByRole("button", { name: "Upload video", exact: true })
        .click();
      assert.equal((await invalid).status(), 422);
      await page
        .getByRole("alert")
        .filter({ hasText: /422|valid video|decode|media/i })
        .first()
        .waitFor();
      assert.deepEqual(await api("/api/videos"), []);
      await page
        .getByLabel("Video file", { exact: true })
        .setInputFiles(path.join(fixture.root, "oriented-vfr.mp4"));
      let releaseUpload;
      const uploadGate = new Promise((resolve) => {
        releaseUpload = resolve;
        releases.push(resolve);
      });
      await page.route("**/api/upload", async (route) => {
        await uploadGate;
        await continueOwnedRoute(route);
      });
      const uploadResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/upload") &&
          response.request().method() === "POST",
      );
      await page
        .getByRole("button", { name: "Upload video", exact: true })
        .click();
      await page
        .getByRole("progressbar", {
          name: "Upload transfer progress",
          exact: true,
        })
        .waitFor();
      assert.equal(
        await page
          .getByRole("button", { name: "Upload video", exact: true })
          .isDisabled(),
        true,
      );
      releaseUpload();
      const uploaded = await uploadResponse;
      assert.equal(uploaded.status(), 202, await uploaded.text());
      await waitJob((await uploaded.json()).id);
      await page.unroute("**/api/upload");
      oriented = (await api("/api/videos"))[0];
      await page
        .getByRole("button", { name: `Select ${oriented.name}`, exact: true })
        .waitFor();
      await page
        .getByRole("button", { name: `Select ${oriented.name}`, exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await page.waitForFunction(
        (id) =>
          document.querySelector('[data-testid="selected-video-id"]')
            ?.textContent === id,
        oriented.id,
      );
      await page
        .getByRole("link", { name: "Open review editor", exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await page.waitForURL(
        (url) =>
          url.pathname === "/editor" &&
          url.searchParams.get("video") === oriented.id,
      );
      await selected(oriented);
      assert.deepEqual(
        [oriented.frame_count, oriented.width, oriented.height],
        [4, 64, 128],
      );
      await addShot(2, 'Generated "quoted", note\nsecond line');
      await save();
      const before = await api(`/api/videos/${oriented.id}/annotations`);
      await upload("oriented-vfr.mp4");
      assert.equal((await api("/api/videos")).length, 1);
      assert.deepEqual(
        await api(`/api/videos/${oriented.id}/annotations`),
        before,
      );
      await page.goto(fixture.base);
      await page
        .getByRole("button", { name: `Select ${oriented.name}`, exact: true })
        .click();
      await page.waitForFunction(
        (id) =>
          document.querySelector('[data-testid="selected-video-id"]')
            ?.textContent === id,
        oriented.id,
      );
      await page
        .getByLabel("Match mode", { exact: true })
        .selectOption("doubles");
      await page
        .getByLabel("Public YouTube URL", { exact: true })
        .fill("https://127.0.0.1/private");
      await page
        .getByRole("button", { name: "Import YouTube", exact: true })
        .click();
      await page
        .getByRole("alert")
        .filter({ hasText: /YouTube|URL|422|invalid/i })
        .first()
        .waitFor();
      await page
        .getByLabel("Public YouTube URL", { exact: true })
        .fill("https://www.youtube.com/watch?v=errorerror1");
      const failedResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/import/youtube") &&
          response.request().method() === "POST",
      );
      await page
        .getByRole("button", { name: "Import YouTube", exact: true })
        .click();
      const failedJob = await (await failedResponse).json();
      const failed = await waitJob(failedJob.id, "failed");
      assert.match(failed.message, /Generated external download failure/);
      await page
        .getByLabel("Public YouTube URL", { exact: true })
        .fill("https://youtu.be/abcdefghijk?si=discard");
      const importedResponse = page.waitForResponse(
        (response) =>
          response.url().endsWith("/api/import/youtube") &&
          response.request().method() === "POST",
      );
      await page
        .getByRole("button", { name: "Import YouTube", exact: true })
        .click();
      const imported = await (await importedResponse).json();
      await waitJob(imported.id);
      youtube = (await api("/api/videos")).find(
        (v) => v.source_type === "youtube",
      );
      assert.equal(
        await page.getByTestId("selected-video-id").textContent(),
        oriented.id,
        "Background import changed the selected source",
      );
      await page
        .getByRole("button", { name: `Select ${youtube.name}`, exact: true })
        .click();
      await page.waitForFunction(
        (id) =>
          document.querySelector('[data-testid="selected-video-id"]')
            ?.textContent === id,
        youtube.id,
      );
      await page
        .getByRole("link", { name: "Open review editor", exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await page.waitForURL(
        (url) =>
          url.pathname === "/editor" &&
          url.searchParams.get("video") === youtube.id,
      );
      assert.equal(
        youtube.source.url,
        "https://www.youtube.com/watch?v=abcdefghijk",
      );
      assert.equal(youtube.source.id, "abcdefghijk");
      await page.reload();
      await selected(youtube);
      assert.equal(await page.locator(".player-row").count(), 4);
      assert.equal(await page.locator("#recognize").isDisabled(), true);
      return {
        ingestion: "production",
        externalDownload: "stubbed",
        importUiCoverage:
          "Production default library: invalid media, upload progress, invalid URL, failed import, success, selection preservation and keyboard handoff",
        sourceTypes: [oriented.source_type, youtube.source_type],
      };
    });

    await check("source-clock", async () => {
      await selected(oriented);
      const root = `/api/videos/${oriented.id}`;
      const before = await api(root + "/annotations");
      assert.deepEqual(await api(root + "/timestamps"), [0, 0.04, 0.12, 0.16]);
      await exact(2);
      assert.deepEqual(
        await page
          .locator("#exact-frame")
          .evaluate((im) => [im.naturalWidth, im.naturalHeight]),
        [64, 128],
      );
      await page.locator("#prepare-playback").click();
      await page.waitForFunction(() =>
        document
          .querySelector("#playback-status")
          .textContent.includes("source frame timing preserved"),
      );
      const proxy = JSON.parse(
        await fs.readFile(
          path.join(
            fixture.root,
            "processed",
            oriented.id,
            "playback/receipt.json",
          ),
          "utf8",
        ),
      );
      assert.equal(proxy.frame_mapping, "identity");
      assert.equal(proxy.context.source_sha256, oriented.sha256);
      assert.equal(proxy.context.rotation, oriented.rotation);
      assert.equal(proxy.context.frame_count, 4);
      await write("oriented-proxy-receipt.json", proxy);
      await exact(2);
      await page.waitForFunction(
        () =>
          Math.abs(document.querySelector("#video").currentTime - 0.12) <
          0.00002,
      );
      await page.waitForFunction(
        () =>
          !document.querySelector("#video").seeking &&
          document.querySelector("#video").readyState >= 2,
      );
      assert.deepEqual(
        await page
          .locator("#video")
          .evaluate((v) => [v.videoWidth, v.videoHeight]),
        [64, 128],
      );
      const pixels = await page.evaluate(() => {
        const image = document.querySelector("#exact-frame"),
          video = document.querySelector("#video");
        function samples(source) {
          const canvas = document.createElement("canvas");
          canvas.width = 64;
          canvas.height = 128;
          const context = canvas.getContext("2d");
          context.drawImage(source, 0, 0, 64, 128);
          return [
            [16, 32],
            [48, 32],
            [16, 96],
            [48, 96],
          ].map(([x, y]) =>
            [...context.getImageData(x, y, 1, 1).data].slice(0, 3),
          );
        }
        return { native: samples(image), proxy: samples(video) };
      });
      for (let quadrant = 0; quadrant < 4; quadrant++)
        for (let color = 0; color < 3; color++)
          assert.ok(
            Math.abs(
              pixels.native[quadrant][color] - pixels.proxy[quadrant][color],
            ) < 25,
            "Proxy/native oriented quadrant mismatch",
          );
      await write("oriented-pixel-comparison.json", pixels);
      // Frame 2 is green/yellow/red/blue after its genuine 90-degree matrix.
      // Yellow has equal R/G in the generator; codec rounding may put either
      // channel first. Check all source RGB channels with the same frozen
      // 25-level codec tolerance instead of assigning yellow a red argmax.
      const expectedQuadrants = [
        [20, 220, 30],
        [220, 220, 30],
        [230, 30, 20],
        [30, 20, 230],
      ];
      for (let quadrant = 0; quadrant < 4; quadrant++)
        for (let color = 0; color < 3; color++)
          assert.ok(
            Math.abs(
              pixels.native[quadrant][color] -
                expectedQuadrants[quadrant][color],
            ) < 25,
            `Native oriented quadrant ${quadrant}, channel ${color} differs from generated source`,
          );
      await page.screenshot({
        path: path.join(evidence, "oriented-proxy.png"),
        fullPage: true,
      });
      assert.ok(proxy.max_timestamp_error_s <= 0.00002);
      assert.deepEqual((await api(root + "/export")).annotations, before);
      await reloadSelected(oriented);
      await exact(3);
      assert.equal((await api(root + "/annotations")).events[0].time_s, 0.12);
      await upload("long-gap-vfr.mkv");
      const gap = (await api("/api/videos")).find(
        (v) => v.name === "long-gap-vfr.mkv",
      );
      // Hold the real media request until after a manual source-frame seek.
      // A real HTTP error then produces the browser's own MediaError, making
      // this race deterministic even on hosts that can decode the MKV codec.
      const mediaRoute = `**/api/videos/${gap.id}/media`;
      let releaseMedia;
      const mediaGate = new Promise((resolve) => {
        releaseMedia = resolve;
        releases.push(resolve);
      });
      const mediaStarted = page.waitForRequest(
        (request) =>
          new URL(request.url()).pathname === `/api/videos/${gap.id}/media`,
      );
      await page.route(mediaRoute, async (route) => {
        await mediaGate;
        await route.fulfill({
          status: 415,
          contentType: "text/plain",
          body: "Generated unsupported native playback; exact source frames remain available",
        });
      });
      await page.reload();
      await selected(gap);
      await mediaStarted;
      assert.deepEqual(
        await api(`/api/videos/${gap.id}/timestamps`),
        [0, 0.04, 0.08, 0.68],
      );
      assert.equal(await page.locator("#video").evaluate((v) => v.error), null);
      await page.locator("#frame-number").fill("3");
      await page.locator("#frame-number").dispatchEvent("change");
      assert.equal(await page.locator("#clock").textContent(), "0:00.68");
      releaseMedia();
      await page.waitForFunction(() => document.querySelector("#video").error);
      await write("unsupported-seek-before-error.json", {
        video: gap.id,
        requestedFrame: 3,
        sourcePts: 0.68,
        stateAfterNativeError: await page.evaluate(() => {
          const v = document.querySelector("#video"),
            img = document.querySelector("#exact-frame");
          return {
            frame: document.querySelector("#frame-number").value,
            clock: document.querySelector("#clock").textContent,
            readyState: v.readyState,
            nativeError: v.error.code,
            exactSrc: img.getAttribute("src"),
            exactHidden: img.hidden,
          };
        }),
      });
      await imageReady(3, gap.id);
      await exact(2);
      await imageReady(2, gap.id);
      assert.equal(await page.locator("#clock").textContent(), "0:00.08");
      const gapRoot = `/api/videos/${gap.id}`,
        originalGapAnnotations = await api(gapRoot + "/annotations"),
        recoveryNote = "Unsupported-media exact-frame draft";
      await addShot(2, recoveryNote);
      await page.locator("#play").click();
      await page.waitForFunction(() => {
        const v = document.querySelector("#video");
        return v.paused && v.error;
      });
      await imageReady(2, gap.id);
      assert.equal(await page.locator("#frame-number").inputValue(), "2");
      assert.equal(await page.locator("#save").isEnabled(), true);
      assert.equal(
        await page.locator("#event-notes").inputValue(),
        recoveryNote,
      );
      assert.deepEqual(
        await api(gapRoot + "/annotations"),
        originalGapAnnotations,
        "Native playback errors must not save or discard the current draft",
      );

      await save();
      const savedGapAnnotations = await api(gapRoot + "/annotations");
      assert.equal(savedGapAnnotations.events[0].notes, recoveryNote);
      assert.equal(savedGapAnnotations.events[0].frame, 2);

      // Hold real source-frame requests while newer frame/video selections
      // finish. A superseded image may be cancelled by the browser; either
      // outcome must leave the current image and source clock untouched.
      async function delayedFrame(frame, changeSelection) {
        const routePattern = `**/api/videos/${gap.id}/frame?index=${frame}`;
        let release, completed;
        const gate = new Promise((resolve) => {
          release = resolve;
          releases.push(resolve);
        });
        const started = page.waitForRequest((request) => {
          const url = new URL(request.url());
          return (
            url.pathname === `/api/videos/${gap.id}/frame` &&
            url.searchParams.get("index") === String(frame)
          );
        });
        const finished = new Promise((resolve) => {
          completed = resolve;
        });
        await page.route(routePattern, async (route) => {
          await gate;
          await continueOwnedRoute(route);
          completed();
        });
        await page.locator("#frame-number").fill(String(frame));
        await page.locator("#frame-number").dispatchEvent("change");
        await started;
        await changeSelection();
        release();
        await finished;
        await page.waitForLoadState("networkidle");
        await page.unroute(routePattern);
      }
      await delayedFrame(1, () => exact(3));
      await imageReady(3, gap.id);
      assert.equal(await page.locator("#clock").textContent(), "0:00.68");
      await delayedFrame(0, async () => {
        await selected(oriented);
        await exact(2);
      });
      await imageReady(2, oriented.id);
      assert.equal(await page.locator("#clock").textContent(), "0:00.12");
      await selected(gap);
      await page.waitForFunction(() => document.querySelector("#video").error);
      await exact(3);
      await imageReady(3, gap.id);
      assert.deepEqual(
        await api(gapRoot + "/annotations"),
        savedGapAnnotations,
      );
      // Preserve a genuine unavailable-frame error, then recover by retrying
      // the same native frame after removing only this generated fault.
      // Use a fresh document so the earlier delayed frame cannot be satisfied
      // from Chromium's decoded-image cache without issuing a new request.
      const unavailableRoute = `**/api/videos/${gap.id}/frame?index=0`;
      await page.route(unavailableRoute, (route) =>
        route.fulfill({
          status: 404,
          body: "Generated unavailable source frame",
        }),
      );
      await page.reload();
      await selected(gap);
      await page.locator("#frame-number").fill("0");
      await page.locator("#frame-number").dispatchEvent("change");
      await page.waitForFunction(() =>
        document
          .querySelector("#frame-loading")
          .textContent.includes("unavailable"),
      );
      assert.equal(await page.locator("#exact-frame").isHidden(), true);
      await page.unroute(unavailableRoute);
      await exact(0);
      await imageReady(0, gap.id);
      await page
        .locator(`[data-event="${savedGapAnnotations.events[0].id}"]`)
        .click();
      assert.equal(
        await page.locator("#event-notes").inputValue(),
        recoveryNote,
      );
      await write("unsupported-media-recovery.json", {
        beforeErrorSeek: { frame: 3, sourcePts: 0.68, video: gap.id },
        afterErrorSeek: { frame: 2, sourcePts: 0.08, video: gap.id },
        failedPlayRestoresExactImage: true,
        unavailableFrameAndRetry: true,
        delayedPriorFrameAndVideoIgnored: true,
        unsavedDraftPreservedUntilExplicitSave: true,
        savedAnnotationsUnchangedByRecovery: true,
      });
      await page.unroute(mediaRoute);
      // Hold the prepared source before metadata. Exact-frame review must
      // remain usable, and an explicit Play must survive metadata arriving
      // afterwards rather than being cancelled by the source-time restore.
      const preparedMedia = `**/api/videos/${gap.id}/playback/media`;
      let releasePrepared;
      const heldPrepared = new Promise((resolve) => {
        releasePrepared = resolve;
      });
      releases.push(releasePrepared);
      await page.route(preparedMedia, async (route) => {
        await heldPrepared;
        await route.continue();
      });
      await page.locator("#prepare-playback").click();
      await page.waitForFunction(() =>
        document
          .querySelector("#playback-status")
          .textContent.includes("source frame timing preserved"),
      );
      const gapProxy = JSON.parse(
        await fs.readFile(
          path.join(fixture.root, "processed", gap.id, "playback/receipt.json"),
          "utf8",
        ),
      );
      assert.equal(gapProxy.frame_mapping, "identity");
      assert.equal(gapProxy.context.duration_s, gap.duration_s);
      await write("gap-proxy-receipt.json", gapProxy);
      await exact(2);
      const pendingMetadata = await page
        .locator("#video")
        .evaluate((video) => ({
          readyState: video.readyState,
          source: video.src,
          frame: document.querySelector("#frame-number").value,
        }));
      assert.equal(pendingMetadata.readyState, 0);
      assert.ok(
        pendingMetadata.source.endsWith(`/videos/${gap.id}/playback/media`),
      );
      assert.equal(pendingMetadata.frame, "2");
      await page.locator("#play").click();
      await page.waitForFunction(
        () => !document.querySelector("#video").paused,
      );
      releasePrepared();
      await page.waitForFunction(() => document.querySelector("#video").ended);
      assert.equal(await page.locator("#frame-number").inputValue(), "3");
      await page.unroute(preparedMedia);
      await write("play-before-metadata.json", {
        pendingMetadata,
        playRequestedBeforeMetadata: true,
        playedThroughNativeGap: true,
        endedAtFrame: 3,
      });
      assert.deepEqual(
        await api(gapRoot + "/annotations"),
        savedGapAnnotations,
      );
      await page.screenshot({
        path: path.join(evidence, "vfr-gap.png"),
        fullPage: true,
      });
      return {
        orientedPts: [0, 0.04, 0.12, 0.16],
        gapPts: [0, 0.04, 0.08, 0.68],
        proxyMapping: "identity",
      };
    });

    await check("selection", async () => {
      await selected(oriented);
      await addShot(1, "unsaved selection draft");
      page.once("dialog", (dialog) => dialog.dismiss());
      await page.locator(`button[data-video="${youtube.id}"]`).click();
      assert.equal(await page.locator("#title").textContent(), oriented.name);
      assert.equal(await page.locator("#save").isEnabled(), true);
      const cancelFocus = await page.evaluate(
        () => document.activeElement.id || document.activeElement.tagName,
      );
      page.once("dialog", (dialog) => dialog.accept());
      await selected(youtube);
      const discardFocus = await page.evaluate(
        () => document.activeElement.id || document.activeElement.tagName,
      );
      assert.notEqual(
        cancelFocus,
        "BODY",
        "Canceled switch lost keyboard focus",
      );
      assert.notEqual(
        discardFocus,
        "BODY",
        "Accepted switch lost keyboard focus",
      );
      await write("selection-focus.json", { cancelFocus, discardFocus });
      assert.equal(
        (await api(`/api/videos/${oriented.id}/annotations`)).events.length,
        1,
      );
      // Delay an actual response, rather than replacing its contents.
      const route = `**/api/videos/${oriented.id}/annotations`;
      let release, entered;
      const gate = new Promise((resolve) => {
        release = resolve;
        releases.push(resolve);
      });
      const started = new Promise((resolve) => {
        entered = resolve;
      });
      await page.route(route, async (r) => {
        entered();
        await gate;
        await continueOwnedRoute(r);
      });
      await page.locator(`button[data-video="${oriented.id}"]`).click();
      await started;
      await selected(youtube);
      release();
      await page.waitForLoadState("networkidle");
      assert.equal(await page.locator("#title").textContent(), youtube.name);
      await page.unroute(route);
      await addShot(1, "earlier draft");
      const saveRoute = `**/api/videos/${youtube.id}/annotations`;
      let releaseSave, saveEntered;
      const saveGate = new Promise((resolve) => {
        releaseSave = resolve;
        releases.push(resolve);
      });
      const saving = new Promise((resolve) => {
        saveEntered = resolve;
      });
      await page.route(saveRoute, async (r) => {
        if (r.request().method() === "PUT") {
          saveEntered();
          await saveGate;
        }
        await continueOwnedRoute(r);
      });
      await page.locator("#save").click();
      await saving;
      await page.locator(`button[data-video="${oriented.id}"]`).click();
      assert.match(
        await page.locator("#notice").textContent(),
        /Saving annotations/,
      );
      await addShot(2, "newer draft during save");
      releaseSave();
      await page.waitForFunction(() =>
        document
          .querySelector("#notice")
          .textContent.includes("Earlier edits saved"),
      );
      assert.equal(await page.locator("#save").isEnabled(), true);
      assert.equal(
        (await api(`/api/videos/${youtube.id}/annotations`)).events.length,
        1,
      );
      await page.unroute(saveRoute);
      await save();
      assert.equal(
        (await api(`/api/videos/${youtube.id}/annotations`)).events.length,
        2,
      );
      return {
        staleSelectionIgnored: true,
        discardConfirm: "cancel and accept",
        newerEditsPreserved: true,
      };
    });

    await check("conflict", async () => {
      await addShot(3, "local conflict draft");
      const root = `/api/videos/${youtube.id}`;
      const prior = await api(root + "/annotations");
      const other = await api(root + "/annotations", {
        method: "PUT",
        data: {
          ...prior,
          players: prior.players.map((p, i) =>
            i ? p : { ...p, name: "Other window" },
          ),
        },
      });
      const failed = page.waitForResponse(
        (r) =>
          r.url().endsWith(root + "/annotations") &&
          r.request().method() === "PUT",
      );
      await page.locator("#save").click();
      assert.equal((await failed).status(), 409);
      await page.waitForFunction(() =>
        document
          .querySelector("#notice")
          .textContent.includes("another window"),
      );
      assert.equal(await page.locator("#save").isEnabled(), true);
      assert.match(
        await page.locator("#event-notes").inputValue(),
        /local conflict draft/,
      );
      assert.deepEqual(await api(root + "/annotations"), other);
      page.once("dialog", (dialog) => dialog.accept());
      await selected(oriented);
      return {
        rejectedStatus: 409,
        persistedRevision: other.revision,
        localDraftRetained: true,
      };
    });

    seeded = await fixture.control("seed");
    await write(
      "fixture-manifest.json",
      await fixture.control("manifest", "GET"),
    );
    await write("source-bundle.json", {
      path: seeded.source_bundle,
      ...seeded.source_manifest,
    });
    rallyRoot = `/api/videos/${seeded.rally.id}`;
    largeRoot = `/api/videos/${seeded.large.id}`;
    await page.reload();
    await selected(seeded.rally);
    const rawPredictionPaths = ["qa-players", "qa-shuttle"].map((id) =>
      path.join(
        fixture.root,
        "processed",
        seeded.rally.id,
        "runs",
        `${id}.json`,
      ),
    );
    const predictionHashes = await Promise.all(
      rawPredictionPaths.map(async (p) => sha256(await fs.readFile(p))),
    );

    await check("rallies", async () => {
      await page.waitForFunction(
        () => !document.querySelector("#suggest-rallies").disabled,
      );
      const before = await api(rallyRoot + "/annotations");
      await page.locator("#suggest-rallies").click();
      await page.waitForFunction(
        () => document.querySelector("#rally-count").textContent === "2",
      );
      assert.deepEqual(await api(rallyRoot + "/annotations"), before);
      const job = (await api("/api/jobs")).find((j) => j.kind === "rallies");
      const run = await api(rallyRoot + `/runs/${job.id}`);
      await write("rally-predictions.json", run);
      for (const kind of ["serve", "rally_end"]) {
        const candidate = run.candidates.find((c) => c.kind === kind);
        await page.locator(`[data-rally-candidate="${candidate.id}"]`).click();
        assert.equal(await page.locator("#event-player").inputValue(), "");
        await page.locator("#apply-event").click();
        await save();
        const event = (await api(rallyRoot + "/annotations")).events.find(
          (e) => e.kind === kind,
        );
        assert.equal(event.source_run_id, job.id);
        assert.equal(event.candidate_id, candidate.id);
        assert.equal(event.player_id, null);
        const prefix = kind === "rally_end" ? "terminal" : "contact";
        assert.equal(event[`${prefix}_start_frame`], candidate.start_frame);
        assert.equal(event[`${prefix}_end_frame`], candidate.end_frame);
        if (kind === "rally_end") {
          assert.equal(event.contact_start_frame, null);
          assert.match(event.notes, /line call are unverified/);
        }
      }
      return {
        candidateCount: run.candidates.length,
        autoSaved: false,
        acceptedKinds: ["serve", "rally_end"],
      };
    });

    await check("identity", async () => {
      await page.locator("#identity-panel").evaluate((e) => {
        e.open = true;
      });
      await page.waitForFunction(
        () => document.querySelector("#identity-track").options.length > 0,
      );
      const track = Number(await page.locator("#identity-track").inputValue());
      await page.locator("#identity-player").selectOption("A");
      await page.locator("#identity-start").fill("0");
      await page.locator("#identity-end").fill("50");
      await page.locator("#assign-identity").click();
      await save();
      const doc = await api(rallyRoot + "/annotations");
      assert.deepEqual(doc.track_assignments[0], {
        start_frame: 0,
        end_frame: 50,
        run_id: "qa-players",
        track_id: track,
        player_id: "A",
      });
      const run = await api(rallyRoot + "/runs/qa-players");
      assert.equal(run.identity_annotation_revision, doc.revision);
      assert.equal(
        run.frames[10].players.find((p) => p.track_id === track).player_id,
        "A",
      );
      assert.notEqual(
        run.frames[60].players.find((p) => p.track_id === track).player_id,
        "A",
      );
      return { track, interval: [0, 50], revision: doc.revision };
    });

    await check("late-derived", async () => {
      await selected(youtube);
      let release, entered;
      const gate = new Promise((resolve) => {
        release = resolve;
        releases.push(resolve);
      });
      const started = new Promise((resolve) => {
        entered = resolve;
      });
      const route = `**${rallyRoot}/runs/qa-players`;
      await page.route(route, async (r) => {
        entered();
        await gate;
        await continueOwnedRoute(r);
      });
      await selected(seeded.rally);
      await started;
      await selected(youtube);
      release();
      await page.waitForLoadState("networkidle");
      assert.equal(await page.locator("#title").textContent(), youtube.name);
      assert.equal(
        await page.locator("#track-status").textContent(),
        "No tracking run loaded",
      );
      assert.deepEqual(
        await page.locator("#overlay").evaluate((c) => [c.width, c.height]),
        [128, 64],
      );
      assert.equal(await page.locator("#identity-track option").count(), 0);
      await page.unroute(route);
      await selected(seeded.rally);
      await page.waitForFunction(() =>
        document
          .querySelector("#track-status")
          .textContent.includes("100 frames"),
      );
      return { latePlayerRunIgnored: true, nextVideoCanvas: [128, 64] };
    });

    await check("review", async () => {
      await page.locator("#review-panel").evaluate((e) => {
        e.open = true;
      });
      await exact(10);
      await page.locator("#label-shuttle").click();
      assert.equal(await page.locator("#show-shuttle").isChecked(), false);
      const bounds = await page.locator("#overlay").boundingBox();
      await page.locator("#overlay").click({
        position: { x: bounds.width * 0.45, y: bounds.height * 0.35 },
      });
      await exact(11);
      await page.locator("#label-invisible").click();
      await page.locator("#review-start").fill("0");
      await page.locator("#review-end").fill("15");
      await page.locator("#review-scene").selectOption("unknown");
      await page.locator("#add-review").click();
      await save();
      const unknown = await api(rallyRoot + "/annotations");
      assert.equal(unknown.review_windows[0].scene, "unknown");
      assert.equal(unknown.review_windows[0].contacts_complete, false);
      const visible = unknown.shuttle_points.find((p) => p.frame === 10);
      assert.equal(visible.visible, true);
      await exact(10);
      assert.equal(
        await page.evaluate(
          (point) =>
            window.baselineArcs.some(
              (arc) =>
                arc.frame === 10 &&
                Math.abs(arc.x - point.x * 1000) < 0.01 &&
                Math.abs(arc.y - point.y * 600) < 0.01,
            ),
          visible,
        ),
        true,
        "Manual normalized point must render at the native source canvas coordinate",
      );
      assert.ok(
        Math.abs(visible.x - 0.45) < 0.003 &&
          Math.abs(visible.y - 0.35) < 0.003,
      );
      assert.deepEqual(
        unknown.shuttle_points.find((p) => p.frame === 11),
        { frame: 11, visible: false, x: null, y: null, notes: "" },
      );
      // Add a disjoint, explicitly complete empty-contact window for real metrics.
      await page.locator("#review-start").fill("80");
      await page.locator("#review-end").fill("100");
      await page.locator("#review-scene").selectOption("live");
      await page.locator("#review-complete").check();
      await page.locator("#add-review").click();
      await save();
      await page.locator("#evaluate").click();
      await page.locator("#download-evaluation").waitFor({ state: "visible" });
      const report = JSON.parse(
        await download("#download-evaluation", "evaluation.json"),
      );
      const doc = await api(rallyRoot + "/annotations");
      assert.equal(report.annotation_revision, doc.revision);
      assert.equal(report.video_sha256, seeded.rally.sha256);
      assert.equal(report.shuttle.coverage.labeled_frames, 2);
      assert.deepEqual(
        await Promise.all(
          rawPredictionPaths.map(async (p) => sha256(await fs.readFile(p))),
        ),
        predictionHashes,
      );
      return {
        visiblePoint: visible,
        unknownWindowPreserved: true,
        evaluationRevision: report.annotation_revision,
        coverage: report.shuttle.coverage,
      };
    });

    await check("strokes", async () => {
      const families = ["clear", "lift", "net", "drop", "smash", "drive"];
      assert.equal(
        await page.locator('#event-family option[value="half_smash"]').count(),
        0,
      );
      let frame = 60;
      for (const family of families)
        for (const side of ["forehand", "backhand"])
          await addShot(frame++, `Generated ${family} ${side}`, family, side);
      await save();
      const doc = await api(rallyRoot + "/annotations");
      assert.deepEqual(
        doc.events
          .filter((e) => e.kind === "shot")
          .map((e) => [e.family, e.side]),
        families.flatMap((family) => [
          [family, "forehand"],
          [family, "backhand"],
        ]),
      );
      const event = doc.events.find((e) => e.kind === "shot");
      const predicted = await api(rallyRoot + "/annotations", {
        method: "PUT",
        data: {
          ...doc,
          events: doc.events.map((e) =>
            e.id === event.id ? { ...e, status: "predicted" } : e,
          ),
        },
      });
      await reloadSelected(seeded.rally);
      await page.locator(`[data-event="${event.id}"]`).click();
      await page.locator("#event-notes").fill("Generated corrected annotation");
      await page.locator("#apply-event").click();
      await save();
      assert.equal(
        (await api(rallyRoot + "/annotations")).events.find(
          (e) => e.id === event.id,
        ).status,
        "corrected",
      );
      assert.equal(
        (await api(rallyRoot + `/revisions/${predicted.revision}`)).events.find(
          (e) => e.id === event.id,
        ).status,
        "predicted",
      );
      await reloadSelected(seeded.rally);
      assert.equal(
        await page.locator("#event-count").textContent(),
        "14 events",
      );
      return {
        combinations: 12,
        correctedStatus: true,
        absentFamily: "half_smash",
      };
    });

    await check("classification", async () => {
      const fixturePrediction = await fixture.control("classification");
      await page.waitForFunction(() =>
        document.querySelector('[data-stroke="qa-classification"]'),
      );
      const before = await api(rallyRoot + "/annotations");
      await page.locator('[data-stroke="qa-classification"]').click();
      assert.equal(await page.locator("#event-family").inputValue(), "clear");
      assert.equal(
        await page.locator("#event-side").inputValue(),
        "forehand",
        "Unknown model side must preserve manual side",
      );
      assert.deepEqual(await api(rallyRoot + "/annotations"), before);
      await page.locator("#apply-event").click();
      await save();
      let saved = await api(rallyRoot + "/annotations");
      const candidate = saved.events.find((e) => e.classification_run_id);
      assert.equal(candidate.classification_run_id, "qa-classification");
      assert.equal(candidate.classification_candidate_id, "qa-classification");
      assert.equal(candidate.family_score, 0.7);
      await page.locator(`[data-event="${candidate.id}"]`).click();
      await page.locator("#event-family").selectOption("lift");
      await page.locator("#apply-event").click();
      await save();
      saved = await api(rallyRoot + "/annotations");
      assert.equal(
        saved.events.find((e) => e.id === candidate.id).family_score,
        null,
      );
      const raw = path.join(
        fixture.root,
        "processed",
        seeded.rally.id,
        "runs/qa-classification.json",
      );
      assert.equal(sha256(await fs.readFile(raw)), fixturePrediction.sha256);
      await write("classification-prediction.json", fixturePrediction);
      return {
        explicitReview: true,
        manualSidePreserved: true,
        staleScoreCleared: true,
        rawPredictionSha256: fixturePrediction.sha256,
      };
    });

    await check("context", async () => {
      await page.waitForFunction(
        () => document.querySelector("#rally-count").textContent === "2",
      );
      await page.locator("#camera-panel").evaluate((e) => {
        e.open = true;
      });
      await page.locator("#scene-start").fill("1");
      await page.locator("#scene-end").fill("15");
      await page.locator("#scene-kind").selectOption("replay");
      await page.locator("#add-scene").click();
      assert.equal(
        await page.locator("#rally-candidates button:disabled").count(),
        2,
      );
      await page.locator("#scene-start").fill("10");
      await page.locator("#scene-end").fill("20");
      await page.locator("#add-scene").click();
      assert.match(await page.locator("#notice").textContent(), /overlap/);
      await save();
      assert.equal(
        (await api(rallyRoot + "/annotations")).scene_ranges[0].scene,
        "replay",
      );
      await page.locator("[data-edit-scene]").click();
      await page.locator("#scene-kind").selectOption("live");
      await page.locator("#add-scene").click();
      await save();
      assert.equal(
        (await api(rallyRoot + "/annotations")).scene_ranges[0].scene,
        "live",
      );
      await page.locator("[data-remove-scene]").click();
      await page.locator("#camera-frame").fill("20");
      await page.locator("#camera-decision").selectOption("cut");
      await page.locator("#camera-apply").click();
      await save();
      await exact(30);
      // Approved task130 repair: current cut truth expires the display even when
      // tracking is stale. The historical phase94 gap remains in its receipts.
      const manualCourtAfterCut = await page
        .locator("#court-status")
        .textContent();
      assert.equal(manualCourtAfterCut, "No calibration for this frame");
      const doc = await api(rallyRoot + "/annotations");
      assert.equal(doc.camera_corrections[0].is_cut, true);
      assert.equal(doc.calibrations[0].end_frame, 100);
      const rerun = await page.request.post(
        fixture.base + rallyRoot + "/rallies",
        { data: { player_run_id: "qa-players", shuttle_run_id: "qa-shuttle" } },
      );
      assert.equal(rerun.status(), 422);
      await page.locator('[data-reset-cut="20"]').click();
      await save();
      await page.locator("#court-start").fill("0");
      await page.locator("#court-end").fill("100");
      await page.locator("#clear-court").click();
      await save();
      assert.equal(
        (await api(rallyRoot + "/annotations")).calibrations.length,
        0,
      );
      await page.locator("#court-end").fill("20");
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
      await save();
      await exact(10);
      assert.match(
        await page.locator("#court-status").textContent(),
        /Calibrated/,
      );
      await exact(20);
      assert.match(
        await page.locator("#court-status").textContent(),
        /No calibration/,
      );
      const calibrated = await api(rallyRoot + "/annotations");
      assert.equal(calibrated.calibrations[0].end_frame, 20);
      // Restore the original reviewed court through real saved revision for timing.
      await api(rallyRoot + "/annotations", {
        method: "PUT",
        data: {
          ...calibrated,
          calibrations: [
            {
              start_frame: 0,
              end_frame: 100,
              corners: [
                { x: 0.2, y: 0.1 },
                { x: 0.8, y: 0.1 },
                { x: 0.8, y: 0.9 },
                { x: 0.2, y: 0.9 },
              ],
            },
          ],
        },
      });
      await reloadSelected(seeded.rally);
      return {
        overlapRejected: true,
        staleRunStatus: 422,
        calibrationExpiryFrame: 20,
        sceneEditAndRemoval: true,
        manualCourtRepair: {
          manualCourtAfterCut,
          savedCalibrationEndExclusive: doc.calibrations[0].end_frame,
          task: 130,
        },
      };
    });

    await check("automatic-court", async () => {
      const automatic = await fixture.control("automatic");
      await reloadSelected(seeded.rally);
      await page.waitForFunction(() =>
        document
          .querySelector("#court-status")
          .textContent.includes("Auto-detected"),
      );
      assert.match(
        await page.locator("#court-status").textContent(),
        /unreviewed/,
      );
      assert.equal(
        (await api(rallyRoot + "/annotations")).calibrations.length,
        0,
      );
      await page.locator("#camera-panel").evaluate((e) => {
        e.open = true;
      });
      await page.locator("#camera-frame").fill("20");
      await page.locator("#camera-decision").selectOption("cut");
      await page.locator("#camera-apply").click();
      assert.match(
        await page.locator("#court-status").textContent(),
        /No calibration/,
      );
      // Discard this camera draft and restore original manual geometry using the
      // current real revision; automatic geometry has never been saved as truth.
      const current = await api(rallyRoot + "/annotations");
      await api(rallyRoot + "/annotations", {
        method: "PUT",
        data: { ...current, calibrations: automatic.original_calibrations },
      });
      page.once("dialog", (d) => d.accept());
      await selected(youtube);
      await selected(seeded.rally);
      return {
        automaticUnreviewed: true,
        hiddenAfterDraftCameraCut: true,
        automaticSavedAsManual: false,
      };
    });

    await check("processing", async () => {
      await selected(seeded.large);
      await page.locator("#analysis-panel").evaluate((e) => {
        e.open = true;
      });
      const before = await api(largeRoot + "/annotations");
      async function start() {
        const response = page.waitForResponse(
          (r) =>
            r.url().endsWith("/analysis") && r.request().method() === "POST",
        );
        await page.locator("#process-analysis").click();
        const r = await response;
        assert.equal(r.status(), 202, await r.text());
        return (await r.json()).id;
      }
      const first = await start();
      await page.waitForFunction(() =>
        document
          .querySelector("#analysis-status")
          .textContent.includes("players"),
      );
      await page.locator("#pause-analysis").click();
      const paused = await waitJob(first, "interrupted");
      await page.waitForFunction(() =>
        document
          .querySelector("#analysis-status")
          .textContent.includes("Paused;"),
      );
      assert.deepEqual(await api(largeRoot + "/annotations"), before);
      const resumed = await start();
      const complete = await waitJob(resumed);
      await page.waitForFunction(
        (id) =>
          document.querySelector("#analysis-status").dataset.jobId === id &&
          document.querySelector("#analysis-status").dataset.jobStatus ===
            "completed",
        resumed,
      );
      assert.equal(await page.locator("#analysis-windows option").count(), 3);
      assert.deepEqual(await api(largeRoot + "/annotations"), before);
      // Same-video polling must not restore the old window over a newer user seek.
      // Hold the real analysis GET after refresh has captured the previous view.
      const pollRoute = `**${largeRoot}/analysis/${resumed}`;
      let holdPoll = true,
        releasePoll,
        enteredPoll;
      const pollGate = new Promise((resolve) => {
        releasePoll = resolve;
        releases.push(resolve);
      });
      const pollStarted = new Promise((resolve) => {
        enteredPoll = resolve;
      });
      await page.route(pollRoute, async (route) => {
        if (holdPoll && route.request().method() === "GET") {
          holdPoll = false;
          enteredPoll();
          await pollGate;
        }
        await continueOwnedRoute(route);
      });
      await Promise.race([
        pollStarted,
        new Promise((_, reject) =>
          setTimeout(
            () => reject(Error("Owned analysis poll did not start")),
            15000,
          ),
        ),
      ]);
      await page.locator("#analysis-windows").selectOption("1");
      await page.locator("#review-analysis").click();
      await imageReady(600);
      await page.waitForFunction(
        () =>
          Math.abs(document.querySelector("#video").currentTime - 60) < 0.00002,
      );
      assert.equal(await page.locator("#frame-number").inputValue(), "600");
      releasePoll();
      await page.waitForFunction(
        () => document.querySelector("#candidate-count").textContent === "2",
      );
      await page.waitForFunction(() =>
        document
          .querySelector("#stroke-predictions")
          .textContent.includes("Needs source review"),
      );
      assert.match(
        await page.locator("#stroke-predictions").textContent(),
        /Needs source review/,
      );
      await page.locator('[data-candidate="qa-contact-600"]').waitFor();
      await page.waitForTimeout(2200);
      assert.equal(
        await page.locator('[data-candidate="qa-contact-600"]').count(),
        1,
        "Late poll replaced current window proposals",
      );
      assert.equal(await page.locator("#frame-number").inputValue(), "600");
      await page.unroute(pollRoute);
      const plan = await api(largeRoot + `/analysis/${resumed}`);
      const part = plan.parts.find((p) => p.window.core_start_frame === 600);
      const contactPath = path.join(
        fixture.root,
        "processed",
        seeded.large.id,
        "runs",
        `${part.stages.contacts.run_id}.json`,
      );
      const rawBefore = sha256(await fs.readFile(contactPath));
      await page.locator('[data-candidate="qa-contact-600"]').click();
      assert.equal(await page.locator("#event-family").inputValue(), "unknown");
      assert.equal(await page.locator("#event-side").inputValue(), "unknown");
      assert.equal(await page.locator("#event-player").inputValue(), "");
      await page.locator("#apply-event").click();
      await save();
      const reviewed = await api(largeRoot + "/annotations");
      assert.equal(reviewed.events.length, 1);
      assert.equal(reviewed.events[0].frame, 600);
      assert.equal(reviewed.events[0].time_s, 60);
      assert.equal(reviewed.events[0].candidate_id, "qa-contact-600");
      assert.equal(
        reviewed.events[0].source_run_id,
        part.stages.contacts.run_id,
      );
      assert.equal(reviewed.events[0].player_id, null);
      assert.equal(sha256(await fs.readFile(contactPath)), rawBefore);
      const reused = await start();
      const cached = await waitJob(reused);
      assert.ok(cached.summary.reused_stages > 0);
      assert.deepEqual(await api(largeRoot + "/annotations"), reviewed);
      await write("pipeline-plan.json", plan);
      await write("pipeline-jobs.json", { paused, complete, cached });
      // Initial selection exposes the source before the first derived plan returns.
      // Seeking during that first run read must reconcile the view at publication.
      const firstPlan = await api(largeRoot + `/analysis/${reused}`);
      const firstPlayers = firstPlan.parts.find(
        (p) => p.window.core_start_frame === 0,
      ).stages.players.run_id;
      await page.reload();
      await page.locator(`button[data-video="${seeded.large.id}"]`).waitFor();
      const firstRoute = `**${largeRoot}/runs/${firstPlayers}`;
      let firstHeld = false,
        releaseFirst,
        enteredFirst;
      const firstGate = new Promise((resolve) => {
        releaseFirst = resolve;
        releases.push(resolve);
      });
      const firstStarted = new Promise((resolve) => {
        enteredFirst = resolve;
      });
      await page.route(firstRoute, async (route) => {
        if (!firstHeld) {
          firstHeld = true;
          enteredFirst();
          await firstGate;
        }
        await continueOwnedRoute(route);
      });
      await selected(seeded.large);
      await Promise.race([
        firstStarted,
        new Promise((_, reject) =>
          setTimeout(
            () => reject(Error("Initial owned players read did not start")),
            15000,
          ),
        ),
      ]);
      await exact(600);
      releaseFirst();
      await page.locator('[data-candidate="qa-contact-600"]').waitFor();
      await page.waitForTimeout(2200);
      assert.equal(
        await page.locator('[data-candidate="qa-contact-600"]').count(),
        1,
        "Initial run response restored the old source core",
      );
      assert.equal(await page.locator("#frame-number").inputValue(), "600");
      assert.equal(
        await page.locator('[data-candidate="qa-contact-0"]').count(),
        0,
      );
      await page.unroute(firstRoute);
      return {
        paused: paused.status,
        resumed: complete.status,
        reusedStages: cached.summary.reused_stages,
        sourceContactFrame: reviewed.events[0].frame,
        predictionSha256: rawBefore,
        recognition: "synthetic abstention, no model",
      };
    });

    await check("recovery", async () => {
      const result = await fixture.control("recovery");
      assert.equal(result.competing_rejected, true);
      assert.equal(result.recovered.status, "interrupted");
      assert.match(result.recovered.message, /Worker stopped/);
      assert.ok(
        result.jobs.some(
          (j) =>
            j.status === "interrupted" &&
            j.message === "Generated cooperative interruption" &&
            j.progress === 0.4,
        ),
      );
      await write("recovery.json", result);
      return {
        competingJobRejected: true,
        staleLifetime: result.recovered.status,
        cancellation: "real run_local_job + JobCancelled",
      };
    });

    await check("exports", async () => {
      await selected(oriented);
      const payload = JSON.parse(
        await download("#export-json", "oriented-export.json"),
      );
      const rows = csv(await download("#export-csv", "oriented-export.csv"));
      const doc = await api(`/api/videos/${oriented.id}/annotations`);
      assert.deepEqual(payload.annotations, doc);
      assert.equal(payload.video.sha256, oriented.sha256);
      assert.equal(rows[0].frame, "2");
      assert.equal(rows[0].time_s, "0.12");
      assert.equal(rows[0].family, "unknown");
      assert.equal(rows[0].side, "unknown");
      assert.equal(rows[0].player_id, "");
      assert.equal(rows[0].notes, 'Generated "quoted", note\nsecond line');
      await selected(seeded.large);
      const contacts = JSON.parse(
        await download("#export-json", "contact-export.json"),
      );
      const contactRows = csv(
        await download("#export-csv", "contact-export.csv"),
      );
      const event = contacts.annotations.events[0];
      for (const key of [
        "id",
        "candidate_id",
        "source_run_id",
        "family",
        "side",
        "status",
      ])
        assert.equal(contactRows[0][key], String(event[key]));
      for (const key of [
        "frame",
        "time_s",
        "contact_start_frame",
        "contact_end_frame",
      ])
        assert.equal(Number(contactRows[0][key]), event[key]);
      await selected(seeded.rally);
      const rallyExport = JSON.parse(
        await download("#export-json", "rally-export.json"),
      );
      const rallyCsv = csv(await download("#export-csv", "rally-export.csv"));
      assert.equal(rallyExport.annotations.track_assignments.length, 1);
      assert.equal(rallyExport.annotations.shuttle_points.length, 2);
      assert.equal(rallyExport.annotations.review_windows[0].scene, "unknown");
      for (const event of rallyExport.annotations.events) {
        const row = rallyCsv.find((r) => r.id === event.id);
        assert.equal(Number(row.frame), event.frame);
        assert.equal(Number(row.time_s), event.time_s);
        assert.equal(row.status, event.status);
        assert.equal(row.candidate_id, event.candidate_id ?? "");
        assert.equal(row.source_run_id, event.source_run_id ?? "");
        assert.equal(
          row.terminal_start_frame,
          String(event.terminal_start_frame ?? ""),
        );
      }
      return {
        jsonRevision: rallyExport.annotations.revision,
        csvEvents: rallyCsv.length,
        csvBoundary: "event-only; no revision column",
      };
    });

    await check("accessibility", async () => {
      const visualControls = await page.evaluate(() => {
        const panel = getComputedStyle(document.querySelector(".review-panel"));
        const clock = getComputedStyle(document.querySelector("#clock"));
        const checkbox = document
          .querySelector("#auto-court")
          .getBoundingClientRect();
        function luminance(rgb) {
          return rgb
            .match(/[\d.]+/g)
            .slice(0, 3)
            .map(Number)
            .map((v) => {
              const s = v / 255;
              return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
            })
            .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0);
        }
        const bg = luminance(panel.backgroundColor),
          fg = luminance(clock.color);
        return {
          panelBackground: panel.backgroundColor,
          clockColor: clock.color,
          contrast: (Math.max(bg, fg) + 0.05) / (Math.min(bg, fg) + 0.05),
          checkbox: { width: checkbox.width, height: checkbox.height },
        };
      });
      await write("visual-controls.json", visualControls);
      assert.ok(
        visualControls.contrast >= 4.5,
        "Source clock text is unreadable on the review panel",
      );
      assert.ok(
        visualControls.checkbox.width <= 24 &&
          visualControls.checkbox.height <= 24,
        "Checkbox inherited full-width text input geometry",
      );
      await exact(15);
      await page.locator("#next-frame").focus();
      await page.keyboard.press("ArrowRight");
      await imageReady(16);
      await page.keyboard.press("ArrowLeft");
      await imageReady(15);
      await page.locator("#frame-number").focus();
      await page.keyboard.press("2");
      assert.equal(
        await page.locator("#event-count").textContent(),
        "14 events",
      );
      await exact(15);
      await page.locator("#next-frame").focus();
      await page.keyboard.press("Enter");
      await imageReady(16);
      await page.keyboard.press("Tab");
      const tabFocus = await page.evaluate(() => document.activeElement.id);
      assert.equal(tabFocus, "frame-number");
      await page.locator("#next-frame").focus();
      await page.keyboard.press("Space");
      await page.waitForFunction(
        () => !document.querySelector("#video").paused,
      );
      await page.keyboard.press("Space");
      await page.waitForFunction(() => document.querySelector("#video").paused);
      for (const [key, kind] of [
        ["1", "serve"],
        ["2", "shot"],
        ["3", "rally_end"],
      ]) {
        await page.locator("#next-frame").focus();
        await page.keyboard.press(key);
        await page.waitForFunction((kind) => {
          const focus =
            kind === "shot"
              ? "event-family"
              : kind === "serve"
                ? "event-player"
                : "event-frame";
          return (
            document.querySelector("#event-kind").value === kind &&
            document.activeElement.id === focus
          );
        }, kind);
        assert.equal(await page.locator("#event-kind").inputValue(), kind);
      }
      await addShot(16, "Keyboard saved QA");
      await page.locator("#save").focus();
      const keyboardSave = page.waitForResponse(
        (r) =>
          r.url().endsWith("/annotations") && r.request().method() === "PUT",
      );
      await page.keyboard.press(
        process.platform === "darwin" ? "Meta+s" : "Control+s",
      );
      assert.equal((await keyboardSave).status(), 200);
      await page.waitForFunction(() =>
        document.querySelector("#save-state").textContent.startsWith("Saved"),
      );
      await page.evaluate(
        () =>
          new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          ),
      );
      const afterSaveFocus = await page.evaluate(
        () => document.activeElement.id || document.activeElement.tagName,
      );
      assert.notEqual(afterSaveFocus, "BODY", "Saving lost keyboard focus");
      assert.equal(
        await page.locator("#notice").getAttribute("role"),
        "status",
      );
      assert.equal(
        await page.locator("#notice").getAttribute("aria-live"),
        "polite",
      );

      const inventory = await page
        .locator("input,select,textarea,button,canvas")
        .evaluateAll((elements) =>
          elements.map((el) => ({
            id: el.id,
            tag: el.tagName,
            text: el.textContent.trim().slice(0, 100),
            ariaLabel: el.getAttribute("aria-label"),
            title: el.title,
            labels: [...(el.labels ?? [])].map((l) =>
              l.textContent.trim().slice(0, 100),
            ),
            tabIndex: el.tabIndex,
          })),
        );
      await write("accessibility-inventory.json", {
        tabFocus,
        afterSaveFocus,
        controls: inventory,
        gaps: [
          "Canvas review is pointer-only and not a keyboard widget",
          "No screen-reader or WCAG conformance assertion",
        ],
      });
      await page.screenshot({
        path: path.join(evidence, "review-desktop.png"),
        fullPage: true,
      });
      await page.setViewportSize({ width: 768, height: 1024 });
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        true,
      );
      await page.screenshot({
        path: path.join(evidence, "review-tablet.png"),
        fullPage: false,
      });
      await page.setViewportSize(protocol.viewport);
      return {
        arrowKeys: true,
        inputGuard: true,
        nativeEnter: true,
        tabFocus,
        afterSaveFocus,
        knownGaps: "accessibility-inventory.json",
      };
    });

    await check("performance", async () => {
      await selected(seeded.rally);
      await page.waitForFunction(() =>
        document
          .querySelector("#track-status")
          .textContent.includes("100 frames"),
      );
      await page.locator("#show-shuttle").check();
      await page.waitForFunction(
        () => document.querySelector("#video").readyState >= 2,
      );
      for (const frame of protocol.seekFrames.slice(0, protocol.warmupSeeks))
        await exact(frame);
      latencies.seek = [];
      for (let i = 0; i < protocol.samples; i++) {
        const frame = protocol.seekFrames[i % protocol.seekFrames.length];
        const value = await page.evaluate(async (frame) => {
          const start = performance.now();
          const input = document.querySelector("#frame-number");
          window.baselineDraws = [];
          input.value = frame;
          input.dispatchEvent(new Event("change", { bubbles: true }));
          await new Promise((resolve, reject) => {
            const end = performance.now() + 10000;
            const poll = () => {
              const image = document.querySelector("#exact-frame");
              if (
                image.src.endsWith(`index=${frame}`) &&
                image.complete &&
                !image.hidden &&
                image.naturalWidth > 0 &&
                window.baselineDraws.some((d) => d.frame === frame)
              )
                return requestAnimationFrame(() =>
                  requestAnimationFrame(resolve),
                );
              if (performance.now() > end)
                return reject(Error("seek-to-overlay timed out"));
              requestAnimationFrame(poll);
            };
            poll();
          });
          const canvas = document.querySelector("#overlay");
          return {
            frame,
            ms: performance.now() - start,
            sourceWidth: document.querySelector("#exact-frame").naturalWidth,
            canvasWidth: canvas.width,
            draw: window.baselineDraws.at(-1),
          };
        }, frame);
        assert.equal(value.sourceWidth, 1000);
        assert.equal(value.canvasWidth, 1000);
        latencies.seek.push(value);
      }
      latencies.playback = [];
      for (let sample = 0; sample < protocol.playbackSamples; sample++) {
        await exact(0);
        latencies.playback.push(
          await page.evaluate(async (duration) => {
            const video = document.querySelector("#video"),
              start = performance.now(),
              initialRenders = Number(
                document.querySelector('[data-testid="editor-renders"]')
                  .textContent,
              );
            let lastRaf = start,
              firstAdvance = null,
              done = false;
            const raf = [],
              lags = [],
              frames = [];
            function tick(now) {
              if (done) return;
              raf.push(now - lastRaf);
              lastRaf = now;
              const displayed = Number(
                document.querySelector("#frame-number").value,
              );
              if (displayed > 0 && firstAdvance === null)
                firstAdvance = now - start;
              lags.push(Math.max(0, video.currentTime - displayed / 25));
              requestAnimationFrame(tick);
            }
            function frameTick(now, metadata) {
              if (done) return;
              frames.push({
                at: now - start,
                mediaTime: metadata.mediaTime,
                presentedFrames: metadata.presentedFrames,
              });
              video.requestVideoFrameCallback(frameTick);
            }
            requestAnimationFrame(tick);
            video.requestVideoFrameCallback(frameTick);
            document.querySelector("#play").click();
            await new Promise((resolve) => setTimeout(resolve, duration));
            done = true;
            video.pause();
            return {
              firstAdvanceMs: firstAdvance,
              rootRenderDelta:
                Number(
                  document.querySelector('[data-testid="editor-renders"]')
                    .textContent,
                ) - initialRenders,
              rafMs: raf,
              overlayLagSeconds: lags,
              frames,
              finalSourceFrame: Number(
                document.querySelector("#frame-number").value,
              ),
              currentTime: video.currentTime,
            };
          }, protocol.playbackDurationMs),
        );
        assert.ok(
          latencies.playback.at(-1).frames.length > 10,
          "Actual decoded video callbacks required",
        );
        assert.ok(latencies.playback.at(-1).finalSourceFrame > 25);
        assert.equal(
          latencies.playback.at(-1).rootRenderDelta,
          0,
          "Playback frames rerendered broad editor panels",
        );
      }
      const dense = await fixture.control("density");
      assert.equal(dense.events.length, protocol.timelineEvents);
      await selected(seeded.large);
      assert.equal(await page.locator("#event-markers button").count(), 1000);
      assert.equal(await page.locator("#events button").count(), 1000);
      latencies.timeline = [];
      for (let i = 0; i < protocol.samples; i++) {
        const frame = (i * 47 + 13) % 1000;
        const result = await page.evaluate(async (frame) => {
          const button = document.querySelector(
              `[data-jump="density-${String(frame).padStart(4, "0")}"]`,
            ),
            start = performance.now();
          button.click();
          await new Promise((resolve) =>
            requestAnimationFrame(() => requestAnimationFrame(resolve)),
          );
          if (Number(document.querySelector("#event-frame").value) !== frame)
            throw Error("Marker selected wrong event");
          return {
            frame,
            ms: performance.now() - start,
            editorFrame: Number(document.querySelector("#event-frame").value),
          };
        }, frame);
        await imageReady(frame);
        latencies.timeline.push(result);
      }
      latencies.summary = {
        seekP95: p95(latencies.seek.map((s) => s.ms)),
        timelineP95: p95(latencies.timeline.map((s) => s.ms)),
        playbackStartP95: p95(latencies.playback.map((s) => s.firstAdvanceMs)),
        rafP95: p95(latencies.playback.flatMap((s) => s.rafMs)),
        overlayLagP95Seconds: p95(
          latencies.playback.flatMap((s) => s.overlayLagSeconds),
        ),
      };
      await write("latencies.json", latencies);
      for (const [metric, ceiling] of Object.entries(protocol.ceilingsMs)) {
        assert.equal(typeof latencies.summary[metric], "number");
        assert.ok(
          latencies.summary[metric] <= ceiling,
          `${metric} ${latencies.summary[metric]} exceeds frozen ${ceiling}ms`,
        );
      }
      await page.screenshot({
        path: path.join(evidence, "large-timeline.png"),
        fullPage: true,
      });
      return {
        ...latencies.summary,
        samples: protocol.samples,
        timelineEvents: 1000,
      };
    });
    assert.deepEqual(
      checks.map(({ name }) => name),
      [
        "production routes, staged assets and default library",
        "imports and library handoff",
        "source-clock",
        "selection",
        "conflict",
        "rallies",
        "identity",
        "late-derived",
        "review",
        "strokes",
        "classification",
        "context",
        "automatic-court",
        "processing",
        "recovery",
        "exports",
        "accessibility",
        "performance",
      ],
    );
    assert.deepEqual(errors, []);
    await write("route-events.json", routeEvents);
    for (const [file, hash] of Object.entries(hashes)) {
      if (file.startsWith("backend/badminton/static/"))
        assert.equal(
          sha256(await fs.readFile(path.join(repository, file))),
          hash,
          "Staged production runtime bytes changed during browser checks",
        );
    }
    await write(
      "fixture-manifest.json",
      await fixture.control("manifest", "GET"),
    );
    await write("result.json", {
      status: "passed",
      protocolSha256: sha256(JSON.stringify(protocol)),
      hashes,
      checks: checks.length,
      frozenParityBlocks: 17,
      productionDeliveryBlocks: 1,
      limitations: [
        "Generated software checks do not establish badminton annotation accuracy",
        "External downloader and model perception use explicit fixture stubs",
        "Authenticated installed-wheel and container HTTP checks are separate required gates",
        "Frozen relative performance comparison requires three same-host legacy and candidate runs",
      ],
      errors,
      summary: latencies.summary,
    });
    console.log(
      `Frontend delivery passed: ${checks.length} checks; ${JSON.stringify(latencies.summary)}`,
    );
  } catch (error) {
    await write("result.json", {
      status: "failed",
      error: error.stack,
      errors,
    });
    if (page)
      await write(
        "failure-state.json",
        await page.evaluate(() => ({
          title: document.querySelector("#title")?.textContent,
          notice: document.querySelector("#notice")?.textContent,
          frame: document.querySelector("#frame-number")?.value,
          exact: {
            src: document.querySelector("#exact-frame")?.src,
            hidden: document.querySelector("#exact-frame")?.hidden,
            complete: document.querySelector("#exact-frame")?.complete,
          },
          video: {
            src: document.querySelector("#video")?.src,
            time: document.querySelector("#video")?.currentTime,
            ready: document.querySelector("#video")?.readyState,
            error: document.querySelector("#video")?.error?.message,
          },
        })),
      ).catch(() => {});
    if (page)
      await page
        .screenshot({
          path: path.join(evidence, "failure.png"),
          fullPage: true,
        })
        .catch(() => {});
    process.exitCode = 1;
    console.error(error);
  } finally {
    if (Object.keys(latencies).length) await write("latencies.json", latencies);
    for (const release of releases) release();
    if (browser) await browser.close();
    if (fixture) await fixture.stop();
  }
}

async function runExportsMode() {
  const assert = (await import("node:assert/strict")).default;
  const fs = await import("node:fs/promises");
  const path = (await import("node:path")).default;
  const os = (await import("node:os")).default;
  const { spawn, execFileSync } = await import("node:child_process");
  const { once } = await import("node:events");
  const { chromium } = await import("playwright");
  const { repository, python, protocol, sha256, startFixture } =
    await import("./frontend-fixtures.mjs");
  assert.ok(
    !process.env.BASE_URL,
    "Export check refuses existing applications",
  );
  const runtime = path.join(repository, "backend/badminton/static");
  await fs.access(path.join(runtime, "build-manifest.json"));
  await fs.mkdir(path.join(repository, ".cache/evidence"), { recursive: true });
  const evidence = await fs.mkdtemp(
    path.join(repository, ".cache/evidence/frontend-delivery-exports-"),
  );
  console.log(`Frontend exports evidence: ${evidence}`);
  // Pin the disposable export root before the fixture imports backend config.
  const exportRoot = path.join(evidence, "exports");
  process.env.BADMINTON_EXPORT_DIR = exportRoot;
  const write = (name, data) =>
    fs.writeFile(
      path.join(evidence, name),
      JSON.stringify(data, null, 2) + "\n",
    );
  const checks = [],
    errors = [],
    routeEvents = [],
    releases = [];
  let fixture, browser, page, frontendBase, admission;
  const hashes = {};
  for (const name of [
    "tests/frontend-fixtures.mjs",
    "tests/frontend-delivery.mjs",
    "tests/media_fixtures.py",
    "tests/rally_fixture.py",
    "tests/test_rally_overlay.py",
    "scripts/pipeline_ui_test_server.py",
    "package-lock.json",
    "uv.lock",
  ])
    hashes[name] = sha256(await fs.readFile(path.join(repository, name)));
  async function sourceHashes(folder) {
    for (const item of await fs.readdir(path.join(repository, folder), {
      withFileTypes: true,
    })) {
      const file = `${folder}/${item.name}`;
      if (item.isDirectory()) await sourceHashes(file);
      else if (item.isFile())
        hashes[file] = sha256(await fs.readFile(path.join(repository, file)));
    }
  }
  await sourceHashes("backend/badminton/static");
  await write("protocol.json", {
    purpose:
      "Production generated functional export checks; stubs and generated media do not evaluate annotation accuracy",
    mode: "exports",
    uiOrigin: "fixture.base served by production FastAPI",
    hashes,
    viewport: protocol.viewport,
  });

  async function check(name, action) {
    const started = Date.now();
    try {
      const result = await action();
      checks.push({
        name,
        status: "passed",
        durationMs: Date.now() - started,
        result,
      });
      console.log(`PASS ${name}`);
      return result;
    } catch (error) {
      checks.push({ name, status: "failed", error: error.stack });
      throw error;
    } finally {
      await write("checks.json", checks);
    }
  }
  const defer = () => {
    let resolve;
    const promise = new Promise((yes) => {
      resolve = yes;
    });
    releases.push(resolve);
    return { promise, resolve };
  };
  async function enteredGate(gate) {
    let timer;
    try {
      await Promise.race([
        gate.promise,
        new Promise((_, reject) => {
          timer = setTimeout(
            () =>
              reject(
                new Error(
                  "Owned route did not enter; inspect preserved fixture",
                ),
              ),
            20000,
          );
        }),
      ]);
    } finally {
      clearTimeout(timer);
    }
  }
  async function waitFor(action, message, timeout = 20000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const result = await action();
      if (result) return result;
      await new Promise((resolve) => setTimeout(resolve, 75));
    }
    assert.fail(message);
  }
  async function api(route, options) {
    const response = await page.request.fetch(fixture.base + route, options);
    assert.ok(
      response.ok(),
      `${route}: ${response.status()} ${await response.text()}`,
    );
    return response.json();
  }
  const endpoint = (video, id = "") =>
    `/api/videos/${video.id}/media-exports${id ? "/" + id : ""}`;
  const card = (id) => page.locator(`[data-export-job="${id}"]`);
  async function jobs(video) {
    return api(`/api/jobs?video_id=${video.id}`);
  }
  async function waitJob(video, id, status = "completed") {
    return waitFor(
      async () => {
        const found = (await jobs(video)).find((job) => job.id === id);
        if (!found || ["queued", "running"].includes(found.status))
          return false;
        assert.equal(found.status, status, JSON.stringify(found));
        return found;
      },
      `Owned job ${id} did not finish; preserve artifacts`,
      45000,
    );
  }
  async function selected(video) {
    await page.locator(`button[data-video="${video.id}"]`).click();
    await page.waitForFunction(
      (video) =>
        document.querySelector("#title")?.textContent === video.name &&
        document
          .querySelector("#video")
          ?.currentSrc.includes(`/api/videos/${video.id}/`),
      video,
    );
    await page.locator("#media-export-mode").waitFor();
    await page.waitForFunction(
      () => !document.querySelector("#media-export-refresh").disabled,
    );
  }
  async function refresh() {
    await page.locator("#media-export-refresh").waitFor({ state: "visible" });
    await page.waitForFunction(
      () => !document.querySelector("#media-export-refresh").disabled,
    );
    await page.locator("#media-export-refresh").click();
  }
  async function ready(video, job) {
    await waitJob(video, job.id);
    await refresh();
    await card(job.id).locator('[data-export-file="manifest.json"]').waitFor();
    return api(endpoint(video, job.id));
  }
  async function start(video, mode, keyboard = false) {
    await page.locator("#media-export-mode").selectOption(mode);
    await page.waitForFunction(
      () => !document.querySelector("#media-export-start").disabled,
    );
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith(endpoint(video)) && r.request().method() === "POST",
    );
    if (keyboard) {
      await page.locator("#media-export-start").focus();
      await page.keyboard.press("Space");
    } else await page.locator("#media-export-start").click();
    const actual = await response;
    assert.equal(actual.status(), 202, await actual.text());
    const job = await actual.json();
    return { job, result: await ready(video, job) };
  }
  async function save() {
    const response = page.waitForResponse(
      (r) => r.url().endsWith("/annotations") && r.request().method() === "PUT",
    );
    await page.locator("#save").click();
    const actual = await response;
    assert.equal(actual.status(), 200, await actual.text());
    const saved = await actual.json();
    await page.waitForFunction(() => document.querySelector("#save").disabled);
    return saved;
  }
  async function safeFulfill(route, options) {
    try {
      await route.fulfill(options);
    } catch (error) {
      const cancelled =
        /already handled|closed|cancelled|Invalid InterceptionId/i.test(
          error.message,
        );
      routeEvents.push({
        message: error.message,
        expectedCancellation: cancelled,
      });
      if (!cancelled) throw error;
    }
  }
  // Trusted native assertions independently inspect the downloaded media. The
  // launcher and all input manifests remain in the evidence directory.
  const nativeProbe = String.raw`
import json,os,sys
from pathlib import Path
repo,root,folder=map(Path,sys.argv[1:4])
os.environ['BADMINTON_ROOT']=str(repo)
os.environ['BADMINTON_DATA_DIR']=str(root/'processed')
sys.path[:0]=[str(repo/'backend'),str(repo/'tests')]
import numpy as np
from badminton.video import iter_frames
from test_rally_overlay import assert_native_media
m=json.loads((folder/'manifest.json').read_text())
v=m['source']; times=json.loads((root/'processed'/v['id']/'timestamps.json').read_text())
plain=m['purpose']=='reviewed_rally_videos'
clips=[r['clip'] for r in m['rallies'] if r['clip'] is not None] if plain else m['exports']
results=[]
for clip in clips:
 start,end=clip['start_frame'],clip['end_frame_exclusive']
 frames=assert_native_media(folder/clip['file'],v,times,start,end,clip['duration_s'])
 errors=[]
 if plain:
  original=list(iter_frames(v,root,times,start,end))
  assert len(original)==len(frames)
  for (_,_,expected),actual in zip(original,frames,strict=True):
   a=actual.to_ndarray(format='rgb24')[:v['height'],:v['width']].astype(float)
   b=expected.to_ndarray(format='rgb24').astype(float)
   errors.append(float(np.mean(np.abs(a-b))))
  assert max(errors)<10,errors
 results.append({'file':clip['file'],'frames':len(frames),'source_start':start,'source_end_exclusive':end,'duration_s':clip['duration_s'],'display_dimensions':[v['width'],v['height']],'plain_pixel_mae':max(errors) if errors else None})
print(json.dumps({'source_sha256':v['sha256'],'revision':m['annotation_revision'],'counts':m['counts'],'native_downloads':results}))
`;
  await fs.writeFile(path.join(evidence, "native-probe.py"), nativeProbe);
  async function downloads(video, job, result, name) {
    assert.equal(result.available, true);
    const folder = path.join(evidence, name);
    await fs.mkdir(folder);
    const links = card(job.id).locator("[data-export-file]");
    assert.equal(await links.count(), result.files.length);
    for (const descriptor of result.files) {
      const link = card(job.id).locator(
        `[data-export-file="${descriptor.filename}"]`,
      );
      const url = new URL(await link.getAttribute("href"), frontendBase);
      assert.equal(url.origin, frontendBase);
      assert.equal(
        url.pathname,
        endpoint(video, job.id) + "/files/" + descriptor.filename,
      );
      const incoming = page.waitForEvent("download");
      await link.click();
      const file = await incoming;
      assert.equal(file.suggestedFilename(), descriptor.filename);
      const target = path.join(folder, descriptor.filename);
      await file.saveAs(target);
      const bytes = await fs.readFile(target);
      assert.equal(bytes.length, descriptor.size_bytes);
      assert.equal(sha256(bytes), descriptor.sha256);
    }
    const manifest = JSON.parse(
      await fs.readFile(path.join(folder, "manifest.json"), "utf8"),
    );
    assert.deepEqual(manifest, result.manifest);
    const native = JSON.parse(
      execFileSync(
        python,
        [
          path.join(evidence, "native-probe.py"),
          repository,
          fixture.root,
          folder,
        ],
        {
          encoding: "utf8",
          env: {
            ...process.env,
            BADMINTON_ROOT: repository,
            BADMINTON_DATA_DIR: path.join(fixture.root, "processed"),
          },
        },
      ),
    );
    await write(name + "-native.json", native);
    return manifest;
  }

  // Real shared Store admission, with a cooperative gate in THIS disposable app.
  const admissionProbe = String.raw`
import json,os,sys,time
from pathlib import Path
repo,root,evidence=map(Path,sys.argv[1:4]);video=sys.argv[4]
os.environ['BADMINTON_ROOT']=str(repo);os.environ['BADMINTON_DATA_DIR']=str(root/'processed')
sys.path.insert(0,str(repo/'backend'))
import psutil
from badminton.storage import Store
from badminton.jobs import run_local_job
def work(job,progress):
 progress(.2)
 p=psutil.Process()
 (evidence/'admission-receipt.json').write_text(json.dumps({'pid':p.pid,'started':p.create_time(),'cwd':p.cwd(),'command':p.cmdline(),'job_id':job,'root':str(root)}))
 deadline=time.monotonic()+45
 while not (evidence/'admission-release').exists():
  if time.monotonic()>deadline: raise RuntimeError('Owned admission gate expired; do not restart')
  time.sleep(.05)
 return {'purpose':'Generated CPU admission check; no inference'}
print(json.dumps(run_local_job(Store(root/'processed'),'fixture',video,work)))
`;
  async function admit(video) {
    const script = path.join(evidence, "admission-probe.py");
    await fs.writeFile(script, admissionProbe);
    const log = await fs.open(path.join(evidence, "admission.log"), "w");
    const child = spawn(
      python,
      ["-u", script, repository, fixture.root, evidence, video.id],
      {
        cwd: repository,
        env: {
          ...process.env,
          BADMINTON_ROOT: repository,
          BADMINTON_DATA_DIR: path.join(fixture.root, "processed"),
        },
        stdio: ["ignore", log.fd, log.fd],
      },
    );
    await log.close();
    const finished = once(child, "exit");
    const receipt = await waitFor(async () => {
      try {
        return JSON.parse(
          await fs.readFile(
            path.join(evidence, "admission-receipt.json"),
            "utf8",
          ),
        );
      } catch {
        assert.equal(
          child.exitCode,
          null,
          "Owned admission worker exited early",
        );
        return false;
      }
    }, "Owned admission startup failed; inspect durable log");
    assert.equal(receipt.pid, child.pid);
    const verify = String.raw`import json,psutil,sys;r=json.loads(sys.argv[1]);p=psutil.Process(r['pid']);assert abs(p.create_time()-r['started'])<.01 and p.cwd()==r['cwd'] and p.cmdline()==r['command'];print('verified')`;
    assert.equal(
      execFileSync(python, ["-c", verify, JSON.stringify(receipt)], {
        encoding: "utf8",
      }).trim(),
      "verified",
    );
    admission = {
      child,
      receipt,
      async stop() {
        await fs.writeFile(
          path.join(evidence, "admission-release"),
          "cooperative release\n",
        );
        const [code, signal] = await finished;
        assert.equal(code, 0, "Owned admission worker failed; preserve log");
        assert.equal(signal, null);
        await write("admission-cleanup.json", {
          ...receipt,
          code,
          signal,
          released: true,
        });
        admission = null;
      },
    };
    return admission;
  }

  try {
    fixture = await startFixture(evidence);
    frontendBase = fixture.base;
    await write("listeners.json", {
      backend: fixture.receipt,
      application: frontendBase,
      delivery:
        "Production FastAPI serves both UI and API; no frontend listener",
    });
    browser = await chromium.launch({ headless: true, channel: "chromium" });
    page = await browser.newPage({ viewport: protocol.viewport });
    page.setDefaultTimeout(20000);
    page.on("pageerror", (error) => errors.push(error.message));
    await write("environment.json", {
      host: os.hostname(),
      node: process.version,
      browser: browser.version(),
      python,
      viewport: protocol.viewport,
    });
    const seeded = await fixture.control("seed"),
      rally = seeded.rally;
    await write("source-bundle.json", seeded.source_manifest);
    const upload = await page.request.post(fixture.base + "/api/upload", {
      multipart: {
        mode: "doubles",
        file: {
          name: "oriented-vfr.mp4",
          mimeType: "video/mp4",
          buffer: await fs.readFile(
            path.join(fixture.root, "oriented-vfr.mp4"),
          ),
        },
      },
    });
    assert.equal(upload.status(), 202, await upload.text());
    const uploadJob = await upload.json();
    await waitFor(async () => {
      const job = (await api("/api/jobs")).find((j) => j.id === uploadJob.id);
      if (!job || ["queued", "running"].includes(job.status)) return false;
      assert.equal(job.status, "completed", JSON.stringify(job));
      return true;
    }, "Generated upload did not complete");
    const oriented = (await api("/api/videos")).find(
      (v) => v.name === "oriented-vfr.mp4",
    );
    assert.ok(oriented);
    const rawRuns = {};
    for (const id of ["qa-players", "qa-shuttle"])
      rawRuns[id] = sha256(
        await fs.readFile(
          path.join(fixture.root, "processed", rally.id, "runs", id + ".json"),
        ),
      );
    const event = (id, kind, frame, rally_id = "R1", extra = {}) => ({
      id,
      rally_id,
      kind,
      frame,
      status: "reviewed",
      ...extra,
    });
    const initial = await api(`/api/videos/${rally.id}/annotations`);
    initial.events = [
      event("serve", "serve", 10, "R1", { side: "unknown" }),
      event("unknown-shot", "shot", 20, "R1", {
        family: "unknown",
        side: "unknown",
      }),
      event("prediction", "shot", 25, "R1", {
        family: "drive",
        side: "backhand",
        status: "predicted",
        confidence: 0.8,
      }),
      event("end", "rally_end", 40),
      event("partial", "shot", 60, "partial", {
        family: "unknown",
        side: "unknown",
      }),
    ];
    const original = await api(`/api/videos/${rally.id}/annotations`, {
      method: "PUT",
      data: initial,
    });
    let current = original;
    await page.goto(frontendBase + "/editor");
    await selected(rally);

    await check(
      "Explicit source/revision/mode controls never save or start on selection",
      async () => {
        assert.equal(
          (await jobs(rally)).filter((j) => j.kind === "media-export").length,
          0,
        );
        assert.equal(
          await page.locator("#media-export-start").isEnabled(),
          true,
        );
        await page.locator("#media-export-mode").selectOption("annotated-full");
        assert.deepEqual(
          await api(`/api/videos/${rally.id}/annotations`),
          original,
        );
        assert.equal(
          (await jobs(rally)).filter((j) => j.kind === "media-export").length,
          0,
        );
        return {
          revision: original.revision,
          modes: await page
            .locator("#media-export-mode option")
            .allTextContents(),
        };
      },
    );

    let historical;
    await check(
      "Real plain export pins its historical snapshot while a newer editor save completes",
      async () => {
        const entered = defer(),
          release = defer();
        let captured, active;
        const url = frontendBase + endpoint(rally);
        const handler = async (route) => {
          if (route.request().method() !== "POST") return route.continue();
          assert.deepEqual(route.request().postDataJSON(), {
            revision: original.revision,
            mode: "plain-rallies",
          });
          const response = await route.fetch();
          assert.equal(response.status(), 202);
          captured = await response.json();
          active = await api(endpoint(rally, captured.id));
          entered.resolve();
          await release.promise;
          await safeFulfill(route, { response });
        };
        await page.route(url, handler);
        try {
          await page
            .locator("#media-export-mode")
            .selectOption("plain-rallies");
          await page.locator("#media-export-start").click();
          await enteredGate(entered);
          assert.equal(active.available, false);
          assert.ok(["queued", "running"].includes(active.job.status));
          assert.equal(
            await page.locator("#media-export-start").isDisabled(),
            true,
            "A submitted mutation must block duplicate exports until its response is reconciled",
          );
          await page.locator("#event-frame").fill("50");
          await page.locator("#rally-id").fill("partial");
          await page.locator("#event-kind").selectOption("shot");
          await page.locator("#event-family").selectOption("unknown");
          await page.locator("#event-side").selectOption("unknown");
          await page
            .locator("#event-notes")
            .fill("Newer saved revision after explicit export request");
          await page.locator("#apply-event").click();
          assert.equal(
            await page.locator("#media-export-start").isDisabled(),
            true,
          );
          current = await save();
          assert.equal(current.revision, original.revision + 1);
          release.resolve();
          const result = await ready(rally, captured);
          assert.equal(result.manifest.annotation_revision, original.revision);
          assert.deepEqual(result.manifest.annotations, original);
          assert.deepEqual(result.manifest.counts, {
            total: 2,
            eligible: 1,
            ineligible: 1,
          });
          const manifest = await downloads(
            rally,
            captured,
            result,
            "historical-plain",
          );
          assert.deepEqual(manifest.annotations, original);
          assert.deepEqual(
            await api(`/api/videos/${rally.id}/annotations`),
            current,
          );
          const text = await card(captured.id).textContent();
          assert.match(text, /partial/);
          assert.match(text, /missing.or.ambiguous.start/i);
          assert.match(text, /missing.or.ambiguous.end/i);
          historical = { job: captured, result };
          return {
            job: captured.id,
            requested: original.revision,
            current: current.revision,
            activeStatus: active.job.status,
            counts: manifest.counts,
          };
        } finally {
          release.resolve();
          await page.unroute(url, handler);
        }
      },
    );

    await check(
      "Real annotated rally and full-video modes download complete provenance",
      async () => {
        const results = [];
        for (const mode of ["annotated-rallies", "annotated-full"]) {
          const { job, result } = await start(rally, mode);
          const manifest = await downloads(rally, job, result, mode);
          assert.equal(manifest.purpose, "annotated_videos");
          assert.equal(
            manifest.scope,
            mode === "annotated-full" ? "full" : "rallies",
          );
          assert.deepEqual(manifest.annotations, current);
          assert.equal(
            manifest.annotations.events.find((e) => e.id === "prediction")
              .status,
            "predicted",
          );
          assert.equal(
            manifest.annotations.events.find((e) => e.id === "unknown-shot")
              .family,
            "unknown",
          );
          assert.deepEqual(manifest.counts, {
            total: 2,
            eligible: 1,
            ineligible: 1,
          });
          results.push({
            mode,
            id: job.id,
            scope: manifest.scope,
            files: result.files.map((f) => f.filename),
          });
        }
        return results;
      },
    );

    await check(
      "Damaged completed artifacts remove UI download availability and recover explicitly",
      async () => {
        const file = path.join(
          exportRoot,
          historical.job.id,
          "rally-000001.mp4",
        );
        const originalBytes = await fs.readFile(file);
        try {
          await fs.writeFile(
            file,
            Buffer.from("Generated damaged export artifact"),
          );
          assert.equal(
            (
              await page.request.get(
                fixture.base + endpoint(rally, historical.job.id),
              )
            ).status(),
            409,
          );
          await refresh();
          await waitFor(
            async () =>
              /409|unavailable|changed/i.test(
                await card(historical.job.id).textContent(),
              ) &&
              (await card(historical.job.id)
                .locator("[data-export-file]")
                .count()) === 0,
            "Unavailable job retained download links",
          );
        } finally {
          await fs.writeFile(file, originalBytes);
        }
        await refresh();
        await card(historical.job.id)
          .locator('[data-export-file="manifest.json"]')
          .waitFor();
        return {
          unavailableStatus: 409,
          restoredHash: sha256(await fs.readFile(file)),
        };
      },
    );

    await check(
      "Real shared admission denies a competing export and explicit retry succeeds",
      async () => {
        const owned = await admit(rally);
        try {
          const before = (await jobs(rally)).filter(
            (j) => j.kind === "media-export",
          ).length;
          const response = page.waitForResponse(
            (r) =>
              r.url().endsWith(endpoint(rally)) &&
              r.request().method() === "POST",
          );
          await page.locator("#media-export-start").click();
          assert.equal((await response).status(), 409);
          await waitFor(
            async () =>
              /409|another|running|busy|admission/i.test(
                await page.locator("#media-export-status").textContent(),
              ),
            "Admission error not explained",
          );
          assert.equal(
            (await jobs(rally)).filter((j) => j.kind === "media-export").length,
            before,
          );
        } finally {
          await owned.stop();
        }
        const { job, result } = await start(rally, "plain-rallies");
        assert.equal(result.available, true);
        return { admissionJob: owned.receipt.job_id, retryJob: job.id };
      },
    );

    await check(
      "Authentication denial preserves drafts and requires explicit retry",
      async () => {
        const url = frontendBase + endpoint(rally);
        const handler = async (route) =>
          route.request().method() === "POST"
            ? route.fulfill({
                status: 401,
                contentType: "application/json",
                body: JSON.stringify({
                  detail: "Generated authentication required",
                }),
              })
            : route.continue();
        const before = (await jobs(rally)).length;
        await page.route(url, handler);
        try {
          await page.locator("#media-export-start").click();
          await waitFor(
            async () =>
              /401|authentication|sign.in/i.test(
                await page.locator("#media-export-status").textContent(),
              ),
            "Authentication guidance missing",
          );
          assert.equal((await jobs(rally)).length, before);
          assert.deepEqual(
            await api(`/api/videos/${rally.id}/annotations`),
            current,
          );
        } finally {
          await page.unroute(url, handler);
        }
        const { job } = await start(rally, "plain-rallies");
        return { injectedFrontendResponse: 401, explicitRetryJob: job.id };
      },
    );

    await check(
      "A delayed selection list cannot strand explicit recovery after a rejected export",
      async () => {
        const results = [];
        for (const denied of [401, 409]) {
          const entered = defer(),
            release = defer(),
            postUrl = frontendBase + endpoint(rally);
          let held = 0;
          const listHandler = async (route) => {
            const url = new URL(route.request().url());
            if (url.searchParams.get("video_id") !== rally.id)
              return route.continue();
            const response = await route.fetch();
            held++;
            entered.resolve();
            await release.promise;
            await safeFulfill(route, { response });
          };
          const postHandler = async (route) =>
            route.request().method() === "POST"
              ? route.fulfill({
                  status: denied,
                  contentType: "application/json",
                  body: JSON.stringify({
                    detail: `Generated ${denied} during delayed job-list recovery`,
                  }),
                })
              : route.continue();
          const before = (await jobs(rally)).length;
          await page.route(frontendBase + "/api/jobs?*", listHandler);
          await page.route(postUrl, postHandler);
          try {
            await page.reload();
            await page.locator(`button[data-video="${rally.id}"]`).click();
            await page.locator("#media-export-start").waitFor();
            await enteredGate(entered);
            await page.waitForFunction(
              () => document.querySelector("#media-export-refresh").disabled,
            );
            const startWasBlocked = await page
              .locator("#media-export-start")
              .isDisabled();
            if (startWasBlocked) {
              release.resolve();
              await page.waitForFunction(
                () => !document.querySelector("#media-export-refresh").disabled,
              );
            }
            const response = page.waitForResponse(
              (r) => r.url() === postUrl && r.request().method() === "POST",
            );
            await page.locator("#media-export-start").click();
            assert.equal((await response).status(), denied);
            await waitFor(
              async () =>
                /authentication|sign.in|unavailable|admission|busy/i.test(
                  await page.locator("#media-export-status").textContent(),
                ),
              "Rejected mutation lost its recovery guidance",
            );
            release.resolve();
            await page.waitForFunction(
              () => !document.querySelector("#media-export-refresh").disabled,
            );
            await page.unroute(frontendBase + "/api/jobs?*", listHandler);
            await page.unroute(postUrl, postHandler);
            await refresh();
            await card(historical.job.id)
              .locator('[data-export-file="manifest.json"]')
              .waitFor();
            assert.equal((await jobs(rally)).length, before);
            assert.deepEqual(
              await api(`/api/videos/${rally.id}/annotations`),
              current,
            );
            results.push({
              denied,
              held,
              startWasBlocked,
              explicitRefresh: true,
            });
          } finally {
            release.resolve();
            await page.unroute(frontendBase + "/api/jobs?*", listHandler);
            await page.unroute(postUrl, postHandler);
          }
        }
        return results;
      },
    );

    await check(
      "A real failed renderer job stays unavailable without changing annotations",
      async () => {
        const file = path.join(fixture.root, rally.path),
          bytes = await fs.readFile(file);
        let job;
        try {
          await fs.writeFile(
            file,
            Buffer.from("Generated unavailable source for failure recovery"),
          );
          await page
            .locator("#media-export-mode")
            .selectOption("plain-rallies");
          const response = page.waitForResponse(
            (r) =>
              r.url().endsWith(endpoint(rally)) &&
              r.request().method() === "POST",
          );
          await page.locator("#media-export-start").click();
          const submitted = await response;
          assert.equal(submitted.status(), 202, await submitted.text());
          job = await submitted.json();
          await waitJob(rally, job.id, "failed");
        } finally {
          await fs.writeFile(file, bytes);
        }
        await refresh();
        await waitFor(
          async () => /failed/i.test(await card(job.id).textContent()),
          "Failed export not shown",
        );
        assert.equal(
          await card(job.id).locator("[data-export-file]").count(),
          0,
        );
        assert.equal((await api(endpoint(rally, job.id))).available, false);
        assert.deepEqual(
          await api(`/api/videos/${rally.id}/annotations`),
          current,
        );
        assert.equal(sha256(await fs.readFile(file)), rally.sha256);
        return {
          job: job.id,
          actualBackendFailure: true,
          sourceRestored: true,
        };
      },
    );

    await check(
      "Unknown status and malformed availability remain non-actionable",
      async () => {
        const url = frontendBase + endpoint(rally, historical.job.id);
        for (const variant of ["unknown", "malformed"]) {
          const handler = async (route) => {
            const body =
              variant === "unknown"
                ? {
                    job: {
                      ...historical.result.job,
                      status: "future-export-state",
                    },
                    available: false,
                  }
                : {
                    ...historical.result,
                    files: [
                      {
                        ...historical.result.files[0],
                        filename: "../escape.mp4",
                      },
                    ],
                  };
            await route.fulfill({
              status: 200,
              contentType: "application/json",
              body: JSON.stringify(body),
            });
          };
          await page.route(url, handler);
          try {
            await refresh();
            const message =
              variant === "unknown"
                ? /future.export.state|unknown|unsupported/i
                : /invalid|unavailable|reload|response/i;
            await waitFor(
              async () =>
                (await card(historical.job.id)
                  .locator("[data-export-file]")
                  .count()) === 0 &&
                message.test(await card(historical.job.id).textContent()),
              `${variant} response exposed downloads or hid its unavailable state`,
            );
          } finally {
            await page.unroute(url, handler);
          }
        }
        await refresh();
        await card(historical.job.id)
          .locator('[data-export-file="manifest.json"]')
          .waitFor();
        return {
          frontendFaults: ["future status", "unsafe descriptor"],
          guessedDownloads: 0,
        };
      },
    );

    await check(
      "Late status success and authentication errors cannot cross video selections",
      async () => {
        for (const variant of ["success", "error"]) {
          await selected(rally);
          const url = frontendBase + endpoint(rally, historical.job.id),
            entered = defer(),
            release = defer();
          let blocked = false;
          const handler = async (route) => {
            if (blocked) return route.continue();
            blocked = true;
            const response = variant === "success" ? await route.fetch() : null;
            entered.resolve();
            await release.promise;
            await safeFulfill(
              route,
              response
                ? { response }
                : {
                    status: 401,
                    contentType: "application/json",
                    body: JSON.stringify({
                      detail: "Generated late authentication error",
                    }),
                  },
            );
          };
          await page.route(url, handler);
          try {
            await refresh();
            await enteredGate(entered);
            await selected(oriented);
            release.resolve();
            await page.waitForTimeout(100);
            assert.equal(
              await page
                .locator(`[data-export-job="${historical.job.id}"]`)
                .count(),
              0,
            );
            assert.doesNotMatch(
              await page.locator("#media-export-status").textContent(),
              /Generated late/,
            );
            assert.equal(
              (await api(`/api/videos/${oriented.id}/annotations`)).revision,
              0,
            );
          } finally {
            release.resolve();
            await page.unroute(url, handler);
          }
        }
        return {
          variants: ["late success", "late 401"],
          selectedVideo: oriented.id,
        };
      },
    );

    await check(
      "Empty eligible output and keyboard controls preserve source review",
      async () => {
        await selected(oriented);
        const frame = await page.locator("#frame-number").inputValue();
        await page.locator("#media-export-mode").focus();
        await page.keyboard.press("ArrowDown");
        assert.equal(await page.locator("#frame-number").inputValue(), frame);
        const { job, result } = await start(oriented, "plain-rallies", true);
        assert.deepEqual(result.manifest.counts, {
          total: 0,
          eligible: 0,
          ineligible: 0,
        });
        assert.deepEqual(
          result.files.map((f) => f.filename),
          ["manifest.json"],
        );
        const manifest = await downloads(oriented, job, result, "empty");
        assert.equal(manifest.rallies.length, 0);
        assert.equal(await page.locator("#frame-number").inputValue(), frame);
        assert.equal(
          await page.locator("#video").evaluate((v) => v.paused),
          true,
        );
        await page.locator("#media-export-refresh").focus();
        await page.keyboard.press("Enter");
        return {
          job: job.id,
          counts: manifest.counts,
          keyboard: ["select arrows", "button Space", "refresh Enter"],
        };
      },
    );

    await check(
      "Rotated VFR downloads retain native frame timing and display pixels",
      async () => {
        const doc = await api(`/api/videos/${oriented.id}/annotations`);
        doc.events = [
          event("oriented-serve", "serve", 0),
          event("oriented-end", "rally_end", 2),
        ];
        const saved = await api(`/api/videos/${oriented.id}/annotations`, {
          method: "PUT",
          data: doc,
        });
        await page.reload();
        await selected(oriented);
        const { job, result } = await start(oriented, "plain-rallies");
        const manifest = await downloads(oriented, job, result, "oriented-vfr");
        assert.equal(manifest.source.rotation, 90);
        assert.equal(manifest.source.mode, "doubles");
        assert.deepEqual(manifest.annotations, saved);
        assert.deepEqual(manifest.counts, {
          total: 1,
          eligible: 1,
          ineligible: 0,
        });
        await page.screenshot({
          path: path.join(evidence, "exports.png"),
          fullPage: true,
        });
        return {
          job: job.id,
          rotation: manifest.source.rotation,
          counts: manifest.counts,
        };
      },
    );

    await check(
      "Saved truth, original predictions and source bytes survive all export work",
      async () => {
        assert.deepEqual(
          await api(`/api/videos/${rally.id}/annotations`),
          current,
        );
        for (const [id, hash] of Object.entries(rawRuns))
          assert.equal(
            sha256(
              await fs.readFile(
                path.join(
                  fixture.root,
                  "processed",
                  rally.id,
                  "runs",
                  id + ".json",
                ),
              ),
            ),
            hash,
          );
        const sources = await fixture.control("manifest", "GET");
        for (const source of sources)
          assert.equal(source.source_sha256, source.video.sha256);
        await write("fixture-manifest.json", sources);
        return {
          originalRunsUnchanged: Object.keys(rawRuns),
          sourceCount: sources.length,
          latestRallyRevision: current.revision,
        };
      },
    );
    assert.deepEqual(errors, []);
    await write("route-events.json", routeEvents);
    await write("result.json", {
      status: "passed",
      checks: checks.length,
      hashes,
      errors,
    });
    console.log(`Frontend exports passed: ${checks.length} groups`);
  } catch (error) {
    await write("result.json", {
      status: "failed",
      error: error.stack,
      errors,
    });
    if (page) {
      await page
        .screenshot({
          path: path.join(evidence, "failure.png"),
          fullPage: true,
        })
        .catch(() => {});
      await write(
        "failure-state.json",
        await page.evaluate(() => ({
          title: document.querySelector("#title")?.textContent,
          notice: document.querySelector("#notice")?.textContent,
          export: document.querySelector("#media-export-status")?.textContent,
          body: document.body.innerText,
        })),
      ).catch(() => {});
    }
    console.error(error);
    process.exitCode = 1;
  } finally {
    for (const release of releases) release();
    if (admission) await admission.stop();
    if (browser) await browser.close();
    if (fixture) await fixture.stop();
  }
}

async function runLibraryMode() {
  const assert = (await import("node:assert/strict")).default;
  const fs = await import("node:fs/promises");
  const path = (await import("node:path")).default;
  const { chromium } = await import("playwright");
  const { repository, startFixture, sha256 } =
    await import("./frontend-fixtures.mjs");
  assert.ok(
    !process.env.BASE_URL,
    "Library check refuses existing applications",
  );
  const runtime = path.join(repository, "backend/badminton/static");
  await fs.access(path.join(runtime, "build-manifest.json"));
  await fs.mkdir(path.join(repository, ".cache/evidence"), { recursive: true });
  const evidence = await fs.mkdtemp(
    path.join(repository, ".cache/evidence/frontend-delivery-library-"),
  );
  console.log(`Library evidence: ${evidence}`);
  const write = (name, value) =>
    fs.writeFile(
      path.join(evidence, name),
      JSON.stringify(value, null, 2) + "\n",
    );
  const checks = [],
    errors = [],
    requests = [],
    routeEvents = [];
  let fixture, browser, page;
  const releases = [];
  async function check(name, action) {
    const start = Date.now();
    try {
      const result = await action();
      checks.push({
        name,
        status: "passed",
        durationMs: Date.now() - start,
        result,
      });
      console.log(`PASS ${name}`);
    } catch (error) {
      checks.push({ name, status: "failed", error: error.stack });
      throw error;
    } finally {
      await write("checks.json", checks);
    }
  }
  async function api(route, options = {}) {
    const response = await fetch(fixture.base + route, options);
    assert.ok(
      response.ok,
      `${route}: ${response.status} ${await response.clone().text()}`,
    );
    return response.json();
  }
  async function until(read, condition, message, timeout = 45000) {
    const deadline = Date.now() + timeout;
    let value;
    while (Date.now() < deadline) {
      value = await read();
      if (condition(value)) return value;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw Error(`${message}: ${JSON.stringify(value)}`);
  }
  async function select(video) {
    await page
      .getByRole("button", { name: `Select ${video.name}`, exact: true })
      .focus();
    await page.keyboard.press("Enter");
    await page.waitForFunction(
      (name) =>
        document
          .querySelector('[data-testid="selected-video"]')
          ?.textContent.includes(name),
      video.name,
    );
  }
  async function hashes(folder) {
    const result = {};
    for (const row of await fs.readdir(folder, { withFileTypes: true })) {
      if (row.isFile())
        result[row.name] = sha256(
          await fs.readFile(path.join(folder, row.name)),
        );
      else if (row.isDirectory()) {
        for (const [name, hash] of Object.entries(
          await hashes(path.join(folder, row.name)),
        ))
          result[`${row.name}/${name}`] = hash;
      }
    }
    return result;
  }
  async function continueOwnedRoute(route) {
    try {
      await route.continue();
    } catch (error) {
      const expected =
        /already handled|has been closed|Target.*closed|cancelled|Invalid InterceptionId/i.test(
          error.message,
        );
      routeEvents.push({
        message: error.message,
        expectedCancellation: expected,
      });
      if (!expected) errors.push(error.message);
    }
  }
  async function expectAlert(pattern) {
    await page
      .getByRole("alert")
      .filter({ hasText: pattern })
      .first()
      .waitFor();
  }
  try {
    fixture = await startFixture(evidence);
    const productionFiles = await hashes(
      path.join(repository, "backend/badminton/static"),
    );
    const base = fixture.base;
    await write("listeners.json", {
      backend: fixture.receipt,
      application: base,
      delivery:
        "Production FastAPI serves both UI and API; no frontend listener",
    });
    browser = await chromium.launch({ channel: "chromium", headless: true });
    await write("environment.json", {
      node: process.version,
      chromium: browser.version(),
      packageLock: sha256(
        await fs.readFile(path.join(repository, "package-lock.json")),
      ),
      productionStatic: productionFiles,
      limitations: [
        "Generated media and route stubs exercise UI contracts, not annotation accuracy",
        "No external application, model, dataset, or running service is used",
      ],
      harness: sha256(await fs.readFile(new URL(import.meta.url))),
    });
    page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      const target = new URL(request.url());
      if (
        target.origin === new URL(base).origin &&
        target.pathname.startsWith("/api/")
      )
        requests.push({
          method: request.method(),
          path: target.pathname,
          time: Date.now(),
        });
    });
    await page.goto(base + "/library");
    await page.getByTestId("library").waitFor();
    await check("empty library and authenticated error retry", async () => {
      assert.deepEqual(await api("/api/videos"), []);
      await page
        .getByText(/No videos|No matches|empty library/i)
        .first()
        .waitFor();
      let denied = true;
      await page.route("**/api/videos", async (route) => {
        if (denied && route.request().method() === "GET") {
          denied = false;
          await route.fulfill({
            status: 401,
            contentType: "text/plain",
            body: "Authentication required",
          });
        } else await continueOwnedRoute(route);
      });
      await page
        .getByRole("button", { name: "Refresh library", exact: true })
        .click();
      await expectAlert(/Authentication|401|sign in/i);
      await page
        .getByRole("button", { name: "Refresh library", exact: true })
        .click();
      await page.unroute("**/api/videos");
      await page
        .getByText(/No videos|No matches|empty library/i)
        .first()
        .waitFor();
    });
    let uploaded;
    await check(
      "real upload progress, invalid media and oriented source records",
      async () => {
        await page
          .getByLabel("Video file", { exact: true })
          .setInputFiles(path.join(fixture.root, "invalid.mp4"));
        const invalid = page.waitForResponse(
          (response) =>
            response.url().endsWith("/api/upload") &&
            response.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Upload video", exact: true })
          .click();
        assert.equal((await invalid).status(), 422);
        await expectAlert(/422|valid video|decode|media/i);
        assert.deepEqual(await api("/api/videos"), []);
        await page
          .getByLabel("Video file", { exact: true })
          .setInputFiles(path.join(fixture.root, "oriented-vfr.mp4"));
        let release;
        const gate = new Promise((resolve) => {
          release = resolve;
        });
        releases.push(release);
        await page.route("**/api/upload", async (route) => {
          await gate;
          await continueOwnedRoute(route);
        });
        const uploadResponse = page.waitForResponse(
          (response) =>
            response.url().endsWith("/api/upload") &&
            response.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Upload video", exact: true })
          .click();
        await page
          .getByRole("progressbar", {
            name: "Upload transfer progress",
            exact: true,
          })
          .waitFor();
        assert.equal(
          await page
            .getByRole("button", { name: "Upload video", exact: true })
            .isDisabled(),
          true,
        );
        release();
        const acceptedUpload = await uploadResponse;
        assert.equal(acceptedUpload.status(), 202, await acceptedUpload.text());
        const uploadJob = await acceptedUpload.json();
        // The initial catalog registration may still use the temporary source
        // filename. Freeze expectations only after this exact job commits its
        // final original-name metadata, not merely when one row first appears.
        await until(
          () => api("/api/jobs"),
          (rows) => {
            const job = rows.find((row) => row.id === uploadJob.id);
            if (!job || ["queued", "running"].includes(job.status))
              return false;
            assert.equal(job.status, "completed", JSON.stringify(job));
            return true;
          },
          "uploaded video metadata finalized",
        );
        const videos = await until(
          () => api("/api/videos"),
          (rows) => rows.length === 1,
          "uploaded video catalog",
        );
        uploaded = videos[0];
        await page.unroute("**/api/upload");
        await page
          .getByRole("button", { name: `Select ${uploaded.name}`, exact: true })
          .waitFor();
        assert.deepEqual(
          [uploaded.frame_count, uploaded.width, uploaded.height],
          [4, 64, 128],
        );
        await select(uploaded);
        return {
          source: uploaded.id,
          frames: uploaded.frame_count,
          oriented: [uploaded.width, uploaded.height],
        };
      },
    );
    await check(
      "public YouTube validation, failed job recovery and selection preservation",
      async () => {
        await page
          .getByLabel("Public YouTube URL", { exact: true })
          .fill("https://127.0.0.1/private");
        await page
          .getByRole("button", { name: "Import YouTube", exact: true })
          .click();
        await expectAlert(/YouTube|URL|422|invalid/i);
        await page
          .getByLabel("Public YouTube URL", { exact: true })
          .fill("https://www.youtube.com/watch?v=errorerror1");
        await page
          .getByRole("button", { name: "Import YouTube", exact: true })
          .click();
        await until(
          () => api("/api/jobs"),
          (rows) =>
            rows.some(
              (row) =>
                row.status === "failed" && /download failure/.test(row.message),
            ),
          "generated failed YouTube import",
        );
        await page
          .getByLabel("Public YouTube URL", { exact: true })
          .fill("https://www.youtube.com/watch?v=abcdefghijk");
        await page
          .getByRole("button", { name: "Import YouTube", exact: true })
          .click();
        await until(
          () => api("/api/videos"),
          (rows) => rows.some((row) => row.source_type === "youtube"),
          "generated successful YouTube import",
        );
        assert.match(
          await page.getByTestId("selected-video").innerText(),
          new RegExp(uploaded.name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
        );
      },
    );
    const seeded = await fixture.control("seed");
    await page
      .getByRole("button", { name: "Refresh library", exact: true })
      .click();
    await page
      .getByRole("button", { name: `Select ${seeded.large.name}`, exact: true })
      .waitFor();
    const before = {
      sources: await fixture.control("manifest", "GET"),
      rally: await api(`/api/videos/${seeded.rally.id}/annotations`),
      large: await api(`/api/videos/${seeded.large.id}/annotations`),
      predictions: await hashes(
        path.join(fixture.root, "processed", seeded.rally.id, "runs"),
      ),
    };
    await write("truth-before.json", before);
    await check(
      "late metadata cannot replace a newer selected source",
      async () => {
        let release;
        const gate = new Promise((resolve) => {
          release = resolve;
        });
        releases.push(release);
        await page.route(`**/api/videos/${seeded.rally.id}`, async (route) => {
          await gate;
          await continueOwnedRoute(route);
        });
        await page
          .getByRole("button", {
            name: `Select ${seeded.rally.name}`,
            exact: true,
          })
          .click();
        await select(seeded.large);
        release();
        await page.unroute(`**/api/videos/${seeded.rally.id}`);
        await page.waitForTimeout(300);
        assert.ok(
          (await page.getByTestId("selected-video").innerText()).includes(
            seeded.large.name,
          ),
        );
      },
    );
    await check(
      "processing pause, resumable job and selection-scoped progress",
      async () => {
        const post = page.waitForResponse(
          (r) =>
            r.url().endsWith(`/api/videos/${seeded.large.id}/analysis`) &&
            r.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Start processing", exact: true })
          .click();
        const firstResponse = await post;
        assert.equal(firstResponse.status(), 202);
        const first = await firstResponse.json();
        await until(
          () => api(`/api/videos/${seeded.large.id}/analysis/${first.id}`),
          (value) => JSON.stringify(value).includes("players"),
          "running synthetic player stage",
        );
        await page
          .getByRole("button", { name: "Pause processing", exact: true })
          .click();
        await until(
          () => api("/api/jobs"),
          (rows) =>
            rows.some(
              (row) => row.id === first.id && row.status === "interrupted",
            ),
          "cooperative paused job",
        );
        await page
          .getByRole("button", { name: "Resume processing", exact: true })
          .waitFor();
        const resumedResponse = page.waitForResponse(
          (r) =>
            r.url().endsWith(`/api/videos/${seeded.large.id}/analysis`) &&
            r.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Resume processing", exact: true })
          .click();
        const resumed = await (await resumedResponse).json();
        assert.notEqual(resumed.id, first.id);
        await select(seeded.rally);
        await until(
          () => api("/api/jobs"),
          (rows) =>
            rows.some(
              (row) => row.id === resumed.id && row.status === "completed",
            ),
          "resumed synthetic match completion",
          60000,
        );
        assert.ok(
          (await page.getByTestId("selected-video").innerText()).includes(
            seeded.rally.name,
          ),
        );
        await select(seeded.large);
        await page
          .getByTestId("selected-jobs")
          .getByText(/completed/i)
          .first()
          .waitFor();
        assert.deepEqual(
          await api(`/api/videos/${seeded.large.id}/annotations`),
          before.large,
        );
        return {
          paused: first.id,
          resumed: resumed.id,
          newJob: true,
          labelsUnchanged: true,
        };
      },
    );
    await check(
      "prepared playback remains tied to its selected source",
      async () => {
        await select(uploaded);
        const started = page.waitForResponse(
          (r) =>
            r.url().endsWith(`/api/videos/${uploaded.id}/playback`) &&
            r.request().method() === "POST",
        );
        await page
          .getByRole("button", { name: "Prepare playback", exact: true })
          .click();
        const job = await (await started).json();
        await until(
          () => api("/api/jobs"),
          (rows) =>
            rows.some((row) => row.id === job.id && row.status === "completed"),
          "playback preparation",
        );
        await until(
          () => api(`/api/videos/${uploaded.id}/playback`),
          (row) => row.status === "ready",
          "playback ready",
        );
        await page.waitForFunction(
          (id) =>
            document
              .querySelector("video")
              ?.currentSrc.includes(`/api/videos/${id}/playback/media`),
          uploaded.id,
        );
        await page.waitForFunction(() => {
          const video = document.querySelector("video");
          return (
            video?.readyState >= 2 &&
            Number.isFinite(video.duration) &&
            video.duration > 0
          );
        });
        const timestamps = await api(`/api/videos/${uploaded.id}/timestamps`);
        assert.equal(timestamps.length, 4);
        return { source: uploaded.id, timestamps, nativeFrames: 4 };
      },
    );
    await check(
      "saved records, source clocks, original predictions and production UI remain intact",
      async () => {
        assert.deepEqual(
          await hashes(path.join(repository, "backend/badminton/static")),
          productionFiles,
        );
        assert.deepEqual(
          await fixture.control("manifest", "GET"),
          before.sources,
        );
        assert.deepEqual(
          await api(`/api/videos/${seeded.rally.id}/annotations`),
          before.rally,
        );
        assert.deepEqual(
          await hashes(
            path.join(fixture.root, "processed", seeded.rally.id, "runs"),
          ),
          before.predictions,
        );
        const production = await browser.newPage();
        await production.goto(fixture.base + "/library");
        await production.getByTestId("library").waitFor();
        await production.close();
      },
    );
    await page.screenshot({
      path: path.join(evidence, "library-selected-desktop.png"),
      fullPage: false,
    });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(100);
    await page.screenshot({
      path: path.join(evidence, "library-desktop.png"),
      fullPage: false,
    });
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(100);
    await page.screenshot({
      path: path.join(evidence, "library-tablet.png"),
      fullPage: false,
    });
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
      true,
    );
    await check("navigation disposes library polling", async () => {
      await page.goto(base + "/editor");
      await page
        .getByRole("heading", { name: "Review your match", exact: true })
        .waitFor();
      await page.waitForTimeout(1500);
      const count = requests.length;
      await page.waitForTimeout(1800);
      assert.equal(requests.length, count);
    });
    assert.deepEqual(errors, []);
    await write("result.json", {
      passed: true,
      checks: checks.length,
      errors,
      limitation:
        "Generated software/UI checks; external downloader and native perception are fixture stubs. No badminton accuracy established.",
    });
  } catch (error) {
    if (page && !page.isClosed()) {
      await page
        .screenshot({ path: path.join(evidence, "failure.png") })
        .catch(() => {});
    }
    await write("failure.json", { error: error.stack, errors });
    throw error;
  } finally {
    for (const release of releases) release();
    if (browser) await browser.close();
    if (fixture) await fixture.stop();
    await write("requests.json", requests);
    await write("route-events.json", routeEvents);
    await write("static-cleanup.json", {
      stopped: true,
      noExistingAppContacted: true,
    });
  }
}
