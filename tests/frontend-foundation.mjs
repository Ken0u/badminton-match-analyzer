/** Phase-95 foundation on owned generated data; no existing app is contacted. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import { once } from "node:events";
import { createServer as createViteServer } from "vite";
import { repository, startFixture, sha256 } from "./frontend-fixtures.mjs";

assert.ok(
  !process.env.BASE_URL,
  "Foundation check refuses BASE_URL/existing apps",
);
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(
  repository,
  ".cache/ms-playwright",
);
const { chromium } = await import("playwright");
const frontend = path.join(repository, "backend/frontend");
const dist = path.join(frontend, "dist");
await fs.access(path.join(dist, "index.html"));
await fs.mkdir(path.join(repository, ".cache/evidence"), { recursive: true });
const evidence = await fs.mkdtemp(
  path.join(repository, ".cache/evidence/frontend-foundation-"),
);
console.log(`Foundation evidence: ${evidence}`);
const write = (name, value) =>
  fs.writeFile(
    path.join(evidence, name),
    JSON.stringify(value, null, 2) + "\n",
  );
const checks = [];
const errors = [];
let fixture, staticServer, browser, loader;
async function check(name, run) {
  const started = Date.now();
  try {
    const result = await run();
    checks.push({
      name,
      status: "passed",
      durationMs: Date.now() - started,
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
async function legacyHashes() {
  const folder = path.join(repository, "backend/badminton/static");
  return Object.fromEntries(
    await Promise.all(
      (await fs.readdir(folder)).map(async (name) => [
        name,
        sha256(await fs.readFile(path.join(folder, name))),
      ]),
    ),
  );
}
async function fileHashes(folder) {
  const result = {};
  for (const item of await fs.readdir(folder, { withFileTypes: true })) {
    const target = path.join(folder, item.name);
    if (item.isDirectory()) {
      const children = await fileHashes(target);
      for (const [name, hash] of Object.entries(children))
        result[`${item.name}/${name}`] = hash;
    } else if (item.isFile())
      result[item.name] = sha256(await fs.readFile(target));
  }
  return result;
}
try {
  const legacy = await legacyHashes();
  fixture = await startFixture(evidence);
  const seeded = await fixture.control("seed");
  const native = await fixture.control("manifest", "GET");
  const annotations = await (
    await fetch(`${fixture.base}/api/videos/${seeded.rally.id}/annotations`)
  ).json();
  const runs = await fileHashes(
    path.join(fixture.root, "processed", seeded.rally.id, "runs"),
  );
  await write("sources-before.json", native);
  await write("annotations-before.json", annotations);
  await write("prediction-hashes-before.json", runs);
  await write("legacy-assets-before.json", legacy);

  loader = await createViteServer({
    root: frontend,
    configFile: false,
    server: { middlewareMode: true, hmr: false },
    appType: "custom",
  });
  const { createApiClient, ApiError } =
    await loader.ssrLoadModule("/src/api/client.ts");
  const api = createApiClient({ baseUrl: fixture.base });
  await check(
    "typed client reads real generated backend and preserves unknowns",
    async () => {
      const records = await api.request("get", "/api/videos", {});
      assert.ok(records.some((record) => record.id === seeded.rally.id));
      const document = await api.request(
        "get",
        "/api/videos/{video_id}/annotations",
        { path: { video_id: seeded.rally.id } },
      );
      assert.deepEqual(document, annotations);
      await assert.rejects(
        api.request("get", "/api/videos/{video_id}", {
          path: { video_id: "missing-generated-source" },
        }),
        (error) => error instanceof ApiError && error.status === 404,
      );
      const abort = new AbortController();
      abort.abort();
      await assert.rejects(
        api.request("get", "/api/videos", { signal: abort.signal }),
        { name: "AbortError" },
      );
      return {
        records: records.length,
        sourceFrames: seeded.rally.frame_count,
        revision: document.revision,
      };
    },
  );
  await loader.close();
  loader = undefined;

  // Serve only prebuilt files. This is a test listener, not a production Node service.
  staticServer = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, "http://127.0.0.1");
      if (request.method !== "GET" && request.method !== "HEAD") {
        response.writeHead(405);
        response.end();
        return;
      }
      const name = decodeURIComponent(
        url.pathname === "/" ? "/index.html" : url.pathname,
      );
      const file = path.resolve(dist, "." + name);
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
      response.end(request.method === "HEAD" ? undefined : bytes);
    } catch {
      response.writeHead(404);
      response.end();
    }
  });
  staticServer.listen(0, "127.0.0.1");
  await once(staticServer, "listening");
  const base = `http://127.0.0.1:${staticServer.address().port}`;
  await write("static-server.json", {
    base,
    pid: process.pid,
    directory: dist,
    runtime: "test-only static files; no Vite runtime",
  });
  browser = await chromium.launch({ channel: "chromium", headless: true });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base);
  await page
    .getByRole("heading", { name: "Frontend foundation", exact: true })
    .waitFor();
  await check(
    "built React assets and accessible keyboard controls",
    async () => {
      assert.match(
        await page.locator("body").innerText(),
        /existing match review application remains the default/,
      );
      await page
        .getByRole("button", { name: "Load sample B", exact: true })
        .focus();
      await page.keyboard.press("Enter");
      await page.waitForFunction(
        () =>
          document.querySelector('[data-testid="selected-sample"]')
            .textContent === "sample-b",
      );
      const field = page.getByRole("textbox", { name: "Sandbox note" });
      await field.fill("preserved local draft");
      assert.equal(
        await page
          .getByRole("button", { name: "Load sample A", exact: true })
          .isDisabled(),
        true,
      );
      await page
        .getByRole("button", { name: "Discard sample draft", exact: true })
        .click();
      assert.equal(await field.inputValue(), "");
      assert.equal(
        await field.evaluate((element) => element === document.activeElement),
        true,
      );
      return {
        keyboard: true,
        draftSwitchBlocked: true,
        discardFocusRestored: true,
      };
    },
  );
  await check(
    "late ignored-abort loads cannot replace current selection",
    async () => {
      await page
        .getByRole("button", { name: "Load sample A", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Load sample B", exact: true })
        .click();
      await page.waitForFunction(
        () =>
          document.querySelector('[data-testid="selected-sample"]')
            .textContent === "sample-b",
      );
      await page.waitForTimeout(380);
      assert.equal(
        await page.getByTestId("selected-sample").textContent(),
        "sample-b",
      );
    },
  );
  await check(
    "save snapshot retains edits made during in-flight save",
    async () => {
      const field = page.getByRole("textbox", { name: "Sandbox note" });
      await field.fill("snapshot");
      await page
        .getByRole("button", { name: "Save sample draft", exact: true })
        .click();
      await field.fill("newer edit");
      await page.waitForFunction(() =>
        document
          .querySelector('[role="status"]')
          .textContent.includes("newer edits"),
      );
      assert.equal(await field.inputValue(), "newer edit");
      await page.waitForFunction(
        () => document.activeElement?.tagName === "INPUT",
      );
      assert.match(
        await page.getByTestId("draft-state").innerText(),
        /Unsaved changes/,
      );
      assert.equal(
        await field.evaluate((element) => element === document.activeElement),
        true,
      );
      await page
        .getByRole("button", { name: "Discard sample draft", exact: true })
        .click();
      assert.equal(await field.inputValue(), "snapshot");
    },
  );
  await check("600 playback updates avoid broad React rerenders", async () => {
    const before = await page.getByTestId("app-renders").textContent();
    await page
      .getByRole("button", { name: "Publish 600 playback ticks", exact: true })
      .click();
    assert.equal(
      await page.getByLabel("Playback probe count").textContent(),
      "Playback ticks: 600",
    );
    assert.equal(await page.getByTestId("app-renders").textContent(), before);
    return { ticks: 600, appRendersBefore: before, appRendersAfter: before };
  });
  await check("accessible error retry preserves the local draft", async () => {
    await page
      .getByRole("textbox", { name: "Sandbox note" })
      .fill("keep on error");
    await page
      .getByRole("button", { name: "Show example error", exact: true })
      .click();
    await page.getByRole("alert").waitFor();
    await page.getByRole("button", { name: "Try again", exact: true }).focus();
    await page.keyboard.press("Enter");
    assert.equal(
      await page.getByRole("textbox", { name: "Sandbox note" }).inputValue(),
      "keep on error",
    );
    assert.equal(await page.getByRole("alert").count(), 0);
  });
  await page.screenshot({
    path: path.join(evidence, "foundation-desktop.png"),
    fullPage: true,
  });
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      ),
  );
  await page.screenshot({
    path: path.join(evidence, "foundation-tablet.png"),
    fullPage: false,
  });
  await page
    .locator('[aria-labelledby="feedback-heading"]')
    .scrollIntoViewIfNeeded();
  await page.screenshot({
    path: path.join(evidence, "foundation-tablet-lower.png"),
    fullPage: false,
  });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    true,
  );
  await check(
    "legacy default UI and generated source truth are preserved",
    async () => {
      assert.deepEqual(await legacyHashes(), legacy);
      const legacyPage = await browser.newPage();
      await legacyPage.goto(fixture.base);
      await legacyPage.locator("#library [data-video]").first().waitFor();
      assert.equal(
        await legacyPage
          .getByRole("heading", { name: "Frontend foundation", exact: true })
          .count(),
        0,
      );
      assert.deepEqual(await fixture.control("manifest", "GET"), native);
      assert.deepEqual(
        await (
          await fetch(
            `${fixture.base}/api/videos/${seeded.rally.id}/annotations`,
          )
        ).json(),
        annotations,
      );
      assert.deepEqual(
        await fileHashes(
          path.join(fixture.root, "processed", seeded.rally.id, "runs"),
        ),
        runs,
      );
      await legacyPage.close();
      return {
        annotationsUnchanged: true,
        nativeSourcesUnchanged: true,
        predictionsUnchanged: true,
        legacyAssetsUnchanged: true,
      };
    },
  );
  assert.deepEqual(errors, []);
  await write("result.json", {
    checks: checks.length,
    passed: true,
    errors,
    scope:
      "generated software foundation; no annotation accuracy or migration completion claim",
  });
} catch (error) {
  await write("failure.json", { error: error.stack, errors });
  throw error;
} finally {
  if (browser) await browser.close();
  if (loader) await loader.close();
  if (staticServer) {
    staticServer.closeAllConnections();
    await new Promise((resolve) => staticServer.close(resolve));
  }
  if (fixture) await fixture.stop();
  await write("static-cleanup.json", {
    stopped: true,
    noExistingAppContacted: true,
  });
}
