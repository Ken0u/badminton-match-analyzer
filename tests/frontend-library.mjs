/** Phase-96 integration: generated media, owned listeners, no existing app. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import { once } from "node:events";
import { repository, startFixture, sha256 } from "./frontend-fixtures.mjs";

assert.ok(!process.env.BASE_URL, "Library check refuses existing applications");
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(
  repository,
  ".cache/ms-playwright",
);
const { chromium } = await import("playwright");
const dist = path.join(repository, "backend/frontend/dist");
await fs.access(path.join(dist, "index.html"));
await fs.mkdir(path.join(repository, ".cache/evidence"), { recursive: true });
const evidence = await fs.mkdtemp(
  path.join(repository, ".cache/evidence/frontend-library-"),
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
let fixture, server, browser, page;
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
      result[row.name] = sha256(await fs.readFile(path.join(folder, row.name)));
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
  await page.getByRole("alert").filter({ hasText: pattern }).first().waitFor();
}
try {
  fixture = await startFixture(evidence);
  const legacyFiles = await hashes(
    path.join(repository, "backend/badminton/static"),
  );
  server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, "http://127.0.0.1");
      if (url.pathname.startsWith("/api/")) {
        const target = new URL(request.url, fixture.base);
        requests.push({
          method: request.method,
          path: target.pathname,
          time: Date.now(),
        });
        const upstream = http.request(
          target,
          {
            method: request.method,
            headers: { ...request.headers },
          },
          (incoming) => {
            response.writeHead(incoming.statusCode, incoming.headers);
            incoming.pipe(response);
          },
        );
        upstream.on("error", () => {
          if (!response.headersSent) response.writeHead(502);
          response.end();
        });
        request.on("aborted", () => upstream.destroy());
        response.on("close", () => {
          if (!response.writableFinished) upstream.destroy();
        });
        request.pipe(upstream);
        return;
      }
      if (url.pathname === "/legacy") {
        response.writeHead(302, { Location: fixture.base });
        response.end();
        return;
      }
      let name = url.pathname;
      if (["/", "/library", "/library/"].includes(name)) name = "/index.html";
      const file = path.resolve(dist, "." + decodeURIComponent(name));
      if (!file.startsWith(dist + path.sep)) {
        response.writeHead(403);
        response.end();
        return;
      }
      const bytes = await fs.readFile(file);
      const types = {
        ".html": "text/html; charset=utf-8",
        ".js": "text/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
      };
      response.writeHead(200, {
        "Content-Type": types[path.extname(file)] || "application/octet-stream",
      });
      response.end(bytes);
    } catch {
      if (!response.headersSent) response.writeHead(404);
      response.end();
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const base = `http://127.0.0.1:${server.address().port}`;
  await write("listeners.json", {
    static: base,
    backend: fixture.receipt,
    staticPid: process.pid,
    proxy: "only owned fixture /api; /legacy redirect",
  });
  browser = await chromium.launch({ channel: "chromium", headless: true });
  await write("environment.json", {
    node: process.version,
    chromium: browser.version(),
    packageLock: sha256(
      await fs.readFile(path.join(repository, "package-lock.json")),
    ),
    frontendSource: await hashes(path.join(repository, "backend/frontend/src")),
    builtAssets: await hashes(dist),
    harness: sha256(await fs.readFile(new URL(import.meta.url))),
  });
  page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
  page.on("pageerror", (error) => errors.push(error.message));
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
    "saved records, source clocks, original predictions and legacy UI remain intact",
    async () => {
      assert.deepEqual(
        await hashes(path.join(repository, "backend/badminton/static")),
        legacyFiles,
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
      const legacy = await browser.newPage();
      await legacy.goto(fixture.base);
      await legacy.locator("#library [data-video]").first().waitFor();
      await legacy.close();
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
    await page.goto(base + "/");
    await page
      .getByRole("heading", { name: "Frontend foundation", exact: true })
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
  if (server) {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
  if (fixture) await fixture.stop();
  await write("requests.json", requests);
  await write("route-events.json", routeEvents);
  await write("static-cleanup.json", {
    stopped: true,
    noExistingAppContacted: true,
  });
}
