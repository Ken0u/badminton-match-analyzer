/** Reviewed-media export UI integration against an owned generated production app. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import os from "node:os";
import { once } from "node:events";
import { randomUUID } from "node:crypto";
import { spawn, execFileSync } from "node:child_process";
import {
  repository,
  python,
  protocol,
  sha256,
  startFixture,
  fixtureOwnership,
  fixtureProcessProbe,
} from "./frontend-fixtures.mjs";

assert.equal(process.env.BASE_URL, undefined, "Refuse an existing application");
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(
  repository,
  ".cache/ms-playwright",
);
const { chromium } = await import("playwright");
const dist = path.join(repository, "backend/frontend/dist");
await fs.access(path.join(dist, "index.html"));
await fs.mkdir(path.join(repository, ".cache/evidence"), { recursive: true });
const evidence = await fs.mkdtemp(
  path.join(repository, ".cache/evidence/frontend-exports-"),
);
console.log(`Frontend exports evidence: ${evidence}`);
// Pin the disposable export root before the fixture imports backend config.
const exportRoot = path.join(evidence, "exports");
process.env.BADMINTON_EXPORT_DIR = exportRoot;
const write = (name, data) =>
  fs.writeFile(path.join(evidence, name), JSON.stringify(data, null, 2) + "\n");
const checks = [],
  errors = [],
  routeEvents = [],
  releases = [];
let fixture, server, browser, page, frontendBase, admission;
const hashes = {};
for (const name of [
  "tests/frontend-fixtures.mjs",
  "tests/frontend-exports.mjs",
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
for (const folder of [
  "backend/frontend/src",
  "backend/frontend/scripts",
  "backend/frontend/dist",
])
  await sourceHashes(folder);
await write("protocol.json", {
  purpose: "Generated functional export checks; no accuracy evaluation",
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
              new Error("Owned route did not enter; inspect preserved fixture"),
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
      if (!found || ["queued", "running"].includes(found.status)) return false;
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
    (r) => r.url().endsWith(endpoint(video)) && r.request().method() === "POST",
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
async function serve() {
  server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url, "http://127.0.0.1");
      if (url.pathname.startsWith("/api/")) {
        const upstream = http.request(
          new URL(request.url, fixture.base),
          { method: request.method, headers: { ...request.headers } },
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
      const name = ["/", "/editor", "/editor/", "/library"].includes(
        url.pathname,
      )
        ? "/index.html"
        : url.pathname;
      const file = path.resolve(dist, "." + decodeURIComponent(name));
      if (!file.startsWith(dist + path.sep)) {
        response.writeHead(403);
        response.end();
        return;
      }
      const bytes = await fs.readFile(file);
      response.writeHead(200, {
        "Content-Type":
          {
            ".html": "text/html",
            ".js": "text/javascript",
            ".css": "text/css",
          }[path.extname(file)] ?? "application/octet-stream",
      });
      response.end(bytes);
    } catch {
      if (!response.headersSent) response.writeHead(404);
      response.end();
    }
  });
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  frontendBase = `http://127.0.0.1:${server.address().port}`;
  await write("listeners.json", {
    static: frontendBase,
    staticPid: process.pid,
    backend: fixture.receipt,
    proxy:
      "Owned generated production fixture only; original browser Host retained",
  });
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
repo,root,evidence=map(Path,sys.argv[1:4]);video,token=sys.argv[4:6]
os.environ['BADMINTON_ROOT']=str(repo);os.environ['BADMINTON_DATA_DIR']=str(root/'processed')
sys.path.insert(0,str(repo/'backend'))
import psutil
from badminton.storage import Store
from badminton.jobs import run_local_job
def work(job,progress):
 progress(.2)
 p=psutil.Process()
 (evidence/'admission-receipt.json').write_text(json.dumps({'pid':p.pid,'started':p.create_time(),'cwd':p.cwd(),'command':p.cmdline(),'job_id':job,'root':str(root),'token':token}))
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
  const token = randomUUID();
  const args = [
    "-u",
    script,
    repository,
    fixture.root,
    evidence,
    video.id,
    token,
  ];
  const runtime = fixtureProcessProbe({ action: "runtime" });
  const child = spawn(python, args, {
    cwd: repository,
    env: {
      ...process.env,
      BADMINTON_ROOT: repository,
      BADMINTON_DATA_DIR: path.join(fixture.root, "processed"),
    },
    stdio: ["ignore", log.fd, log.fd],
  });
  await log.close();
  const finished = once(child, "exit");
  const ownership = fixtureOwnership({
    pid: child.pid,
    expected: {
      cwd: repository,
      root: fixture.root,
      token,
      python,
      args,
      executables: [python, runtime.base],
    },
    adapter: {
      inspect: (pid) => fixtureProcessProbe({ action: "inspect", pid }),
      children: (pid) => fixtureProcessProbe({ action: "children", pid }),
      signal: (identity, signal) =>
        fixtureProcessProbe({
          action: "signal",
          pid: identity.pid,
          identity,
          signal,
        }),
      delay: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    },
    persist: (value) => write("admission-ownership.json", value),
  });
  let receipt, stopping;
  const stop = () => {
    stopping ??= (async () => {
      await fs.writeFile(
        path.join(evidence, "admission-release"),
        "cooperative release\n",
      );
      const [code, signal] = await finished;
      await ownership.stop();
      await write("admission-cleanup.json", {
        ...receipt,
        code,
        signal,
        released: true,
      });
      admission = null;
      assert.equal(code, 0, "Owned admission worker failed; preserve log");
      assert.equal(signal, null);
    })();
    return stopping;
  };
  try {
    const identity = ownership.initialize();
    await write("admission-spawn-identity.json", identity);
    receipt = await waitFor(async () => {
      ownership.discover();
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
    ownership.bind(receipt);
    admission = { child, receipt, stop };
    return admission;
  } catch (error) {
    try {
      await stop();
    } catch (cleanup) {
      error.message += `; admission cleanup failed: ${cleanup.message}`;
    }
    throw error;
  }
}

try {
  fixture = await startFixture(evidence);
  await serve();
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
        buffer: await fs.readFile(path.join(fixture.root, "oriented-vfr.mp4")),
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
      assert.equal(await page.locator("#media-export-start").isEnabled(), true);
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
        await page.locator("#media-export-mode").selectOption("plain-rallies");
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
          manifest.annotations.events.find((e) => e.id === "prediction").status,
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
      const file = path.join(exportRoot, historical.job.id, "rally-000001.mp4");
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
        await page.locator("#media-export-mode").selectOption("plain-rallies");
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
      assert.equal(await card(job.id).locator("[data-export-file]").count(), 0);
      assert.equal((await api(endpoint(rally, job.id))).available, false);
      assert.deepEqual(
        await api(`/api/videos/${rally.id}/annotations`),
        current,
      );
      assert.equal(sha256(await fs.readFile(file)), rally.sha256);
      return { job: job.id, actualBackendFailure: true, sourceRestored: true };
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
  await write("result.json", { status: "failed", error: error.stack, errors });
  if (page) {
    await page
      .screenshot({ path: path.join(evidence, "failure.png"), fullPage: true })
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
  if (server) {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
  if (fixture) await fixture.stop();
}
