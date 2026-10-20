/** Owned, generated-only app process for the frontend migration baseline. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, execFileSync } from "node:child_process";
import { randomUUID, createHash } from "node:crypto";

export const repository = path.resolve(
  fileURLToPath(new URL("../", import.meta.url)),
);
export const python =
  process.env.FRONTEND_PYTHON ||
  path.join(
    repository,
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python",
  );
export const protocol = Object.freeze({
  version: 1,
  viewport: { width: 1440, height: 1080 },
  samples: 20,
  warmupSeeks: 3,
  seekFrames: [2, 28, 4, 80, 14, 60, 8, 95, 20, 40],
  timelineEvents: 1000,
  playbackSamples: 3,
  playbackDurationMs: 2500,
  // Absolute ceilings are frozen before measurement; failures stay failures.
  ceilingsMs: {
    seekP95: 2000,
    timelineP95: 500,
    playbackStartP95: 1000,
    rafP95: 100,
  },
  comparison: { relativeIncrease: 0.25, noiseFloorMs: 20 },
});
export const sha256 = (bytes) =>
  createHash("sha256").update(bytes).digest("hex");

// Python remains here because this task owns no Python source path. This exact
// launcher is saved with every receipt and imports trusted generated helpers.
const launcher = String.raw`
import asyncio
import hashlib
import io
import json
import os
import socket
import shutil
import sys
import time
from pathlib import Path

repo, root, token = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
os.environ["BADMINTON_ROOT"] = str(repo)
os.environ["BADMINTON_DATA_DIR"] = str(root / "processed")
sys.path[:0] = [str(repo / "backend"), str(repo / "tests"), str(repo / "scripts")]
# Native inference is stubbed by the trusted pipeline helper, never initialized.
import psutil
import uvicorn
from fastapi import FastAPI, Request, HTTPException
from badminton import media_import
from badminton.api import create_app
from badminton.ingest import inspect_video
from badminton.jobs import run_local_job, JobCancelled
from badminton.schemas import Annotations
from badminton.storage import Store, ConflictError
from media_fixtures import write_rotated_video, write_lossless_vfr_video

root.mkdir(parents=True, exist_ok=True)
recipes = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
           for name in ["tests/media_fixtures.py", "tests/rally_fixture.py", "scripts/pipeline_ui_test_server.py"]}
bundle = os.environ.get("FRONTEND_SOURCE_BUNDLE")
if bundle:
    bundle = Path(bundle).resolve()
    assert bundle.is_relative_to(repo / ".cache"), "Source bundle must remain inside this worktree cache"
    frozen = json.loads((bundle / "manifest.json").read_text())
    assert frozen["recipes"] == recipes, "Frozen source helper bytes changed"
    assert set(frozen["sources"]) == {"oriented-vfr.mp4", "youtube-vfr.mp4", "long-gap-vfr.mkv", "rally-qa.mp4", "pipeline-qa.mp4"}
    for name, expected in frozen["sources"].items():
        assert hashlib.sha256((bundle / name).read_bytes()).hexdigest() == expected, "Frozen source bytes changed"

def use_frozen(path):
    if bundle:
        shutil.copyfile(bundle / path.name, path)
    return path

use_frozen(write_rotated_video(root / "oriented-vfr.mp4", 90))
use_frozen(write_rotated_video(root / "youtube-vfr.mp4", 0))
use_frozen(write_lossless_vfr_video(root / "long-gap-vfr.mkv"))
(root / "invalid.mp4").write_text("Generated invalid media", encoding="utf-8")

def download(url, media_root, max_bytes, progress):
    canonical = media_import.canonical_youtube_url(url)
    for i in range(10):
        progress(i / 10)
        time.sleep(0.15)
    if canonical.endswith("errorerror1"):
        raise ValueError("Generated external download failure")
    source = root / "youtube-vfr.mp4"
    result = media_import.save_upload(io.BytesIO(source.read_bytes()), source.name,
                                      media_root, max_bytes=max_bytes)
    return result, {"source_type": "youtube", "url": canonical,
                    "id": canonical.rsplit("=", 1)[1], "title": "Generated YouTube doubles"}
media_import.download_youtube = download
inner = create_app(root, root / "processed", username="", password="")
store = inner.state.store
app = FastAPI(lifespan=inner.router.lifespan_context)
receipt = {"token": token, "pid": os.getpid(), "started": psutil.Process().create_time(),
           "cwd": os.getcwd(), "command": psutil.Process().cmdline(), "root": str(root)}
seeded = None

def authorize(request):
    if request.headers.get("x-fixture-token") != token:
        raise HTTPException(403, "Fixture ownership required")

@app.get("/__fixture/receipt")
def owned(request: Request):
    authorize(request)
    return receipt

@app.post("/__fixture/seed")
def seed(request: Request):
    global seeded
    authorize(request)
    if seeded is not None:
        return seeded
    import rally_fixture
    import pipeline_ui_test_server
    original_inspect = inspect_video
    def frozen_inspect(path, *args, **kwargs):
        use_frozen(path)
        return original_inspect(path, *args, **kwargs)
    rally_fixture.inspect_video = frozen_inspect
    pipeline_ui_test_server.inspect_video = frozen_inspect
    catalog, prepare = rally_fixture.catalog, pipeline_ui_test_server.prepare
    rally_root = root / "rally"
    rally_root.mkdir()
    _, rally = catalog(rally_root, root / "processed")
    # catalog used a nested root; normalize the source relative to the app root.
    rally["path"] = "rally/rally-qa.mp4"
    store.register(rally)
    pipeline_root = root / "pipeline"
    pipeline_root.mkdir()
    _, large = prepare(pipeline_root, root / "processed")
    large["path"] = "pipeline/pipeline-qa.mp4"
    store.register(large)
    output_bundle = root / "source-bundle"
    output_bundle.mkdir()
    sources = [root / "oriented-vfr.mp4", root / "youtube-vfr.mp4", root / "long-gap-vfr.mkv",
               rally_root / "rally-qa.mp4", pipeline_root / "pipeline-qa.mp4"]
    frozen_manifest = {"recipes": recipes, "sources": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
    for source in sources:
        shutil.copyfile(source, output_bundle / source.name)
    (output_bundle / "manifest.json").write_text(json.dumps(frozen_manifest, indent=2))
    seeded = {"rally": rally, "large": large, "source_bundle": str(output_bundle), "source_manifest": frozen_manifest}
    return seeded

@app.post("/__fixture/classification")
def classification(request: Request):
    authorize(request)
    video = seeded["rally"]
    doc = store.annotations(video["id"])
    event = next(e for e in doc.events if e.kind == "shot")
    run = {"stage": "recognition", "video_id": video["id"], "video_sha256": video["sha256"],
           "start_frame": 0, "end_frame": 100, "player_run_id": "qa-players", "shuttle_run_id": "qa-shuttle",
           "annotation_revision": doc.revision, "candidate_count": 1, "predicted_count": 1,
           "camera_review_signature": [], "model": "synthetic_qa", "candidates": [
               {"id": "qa-classification", "event_id": event.id, "frame": event.frame,
                "time_s": event.time_s, "kind": "shot", "family": "clear", "family_score": 0.7,
                "side": "unknown", "status": "predicted", "reason": "Synthetic UI fixture, not inference"}]}
    from badminton.video import write_json
    target = root / "processed" / video["id"] / "runs" / "qa-classification.json"
    write_json(target, run)
    store.put_job({"id": "qa-classification", "video_id": video["id"], "kind": "recognition",
                   "status": "completed", "progress": 1, "summary": {k:v for k,v in run.items() if k != "candidates"}})
    return {"run": run, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}

@app.post("/__fixture/automatic")
def automatic(request: Request):
    authorize(request)
    video = seeded["rally"]
    doc = store.annotations(video["id"])
    original = doc.model_dump()
    target = root / "processed" / video["id"] / "runs" / "qa-players.json"
    run = json.loads(target.read_text())
    run.update(court_context_version=1, automatic_calibrations=original["calibrations"])
    from badminton.video import write_json
    write_json(target.with_name("qa-auto-players.json"), run)
    store.put_job({"id": "qa-auto-players", "video_id": video["id"], "kind": "players", "status": "completed",
                   "progress": 1, "summary": {k:v for k,v in run.items() if k != "frames"}})
    doc.calibrations = []
    saved = store.save_annotations(video["id"], doc)
    return {"original_calibrations": original["calibrations"], "revision": saved.revision}

@app.post("/__fixture/density")
def density(request: Request):
    authorize(request)
    if seeded is None:
        raise HTTPException(409, "Seed first")
    video = seeded["large"]
    doc = store.annotations(video["id"]).model_dump()
    doc["events"] = [{"id": f"density-{i:04}", "rally_id": f"R{i // 10}",
                      "kind": "shot", "frame": i, "family": "unknown",
                      "side": "unknown", "notes": "Generated density fixture"}
                     for i in range(1000)]
    return store.save_annotations(video["id"], Annotations.model_validate(doc))

@app.post("/__fixture/recovery")
def recovery(request: Request):
    authorize(request)
    video_id = seeded["rally"]["id"]
    # A genuine admitted CPU-only job tests cooperative interruption. Admission
    # across two Store instances of THIS app uses the real SQLite transaction.
    competing_rejected = False
    def work(job_id, progress):
        nonlocal competing_rejected
        progress(0.4)
        try:
            run_local_job(Store(root / "processed"), "fixture", video_id, lambda *_: {})
        except ConflictError:
            competing_rejected = True
        raise JobCancelled("Generated cooperative interruption")
    try:
        run_local_job(store, "fixture", video_id, work)
    except JobCancelled:
        pass
    # PID reuse/lifetime recovery without terminating any unrelated process.
    stale = {"id": "fixture-stale-lifetime", "video_id": video_id,
             "kind": "fixture", "status": "running", "progress": 0.2,
             "owner_pid": os.getpid(), "owner_started": receipt["started"] - 100}
    store.put_job(stale)
    store.recover_jobs()
    return {"competing_rejected": competing_rejected,
            "recovered": store.job(stale["id"]), "jobs": store.jobs(video_id)}

@app.get("/__fixture/manifest")
def manifest(request: Request):
    authorize(request)
    result = []
    for video in store.videos():
        source = root / video["path"]
        result.append({"video": video, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                       "timestamps": json.loads((root / "processed" / video["id"] / "timestamps.json").read_text())})
    return result

app.mount("/", inner)
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen(128)
receipt["base"] = f"http://127.0.0.1:{sock.getsockname()[1]}"
(root / "receipt.json").write_text(json.dumps(receipt, indent=2), encoding="utf-8")
uvicorn.Server(uvicorn.Config(app, log_level="warning")).run(sockets=[sock])
`;

export async function startFixture(evidence) {
  assert.equal(
    process.env.BASE_URL,
    undefined,
    "An existing app cannot be used as a fixture",
  );
  await fs.access(python);
  const root = await fs.mkdtemp(
    path.join(repository, ".cache/frontend-fixture-"),
  );
  const script = path.join(root, "launcher.py");
  await fs.writeFile(script, launcher);
  const token = randomUUID();
  const log = await fs.open(path.join(evidence, "fixture-server.log"), "w");
  const child = spawn(python, ["-u", script, repository, root, token], {
    cwd: repository,
    env: {
      ...process.env,
      BADMINTON_ROOT: repository,
      BADMINTON_DATA_DIR: path.join(root, "processed"),
    },
    stdio: ["ignore", log.fd, log.fd],
  });
  await log.close();
  let receipt, identity;
  const identify = String.raw`import json,psutil,sys
p=psutil.Process(int(sys.argv[1])); expected=json.loads(sys.argv[2])
assert p.cwd() == expected["cwd"] and p.cmdline()[1:] == expected["args"]
print(json.dumps({"pid":p.pid,"started":p.create_time(),"cwd":p.cwd(),"command":p.cmdline()}))`;
  const verify = String.raw`import json,psutil,sys
r=json.loads(sys.argv[1]);p=psutil.Process(r["pid"])
assert abs(p.create_time()-r["started"]) < .01
assert p.cwd() == r["cwd"] and p.cmdline() == r["command"]
print("verified")`;
  async function stop() {
    if (child.exitCode === null && child.signalCode === null) {
      assert.ok(identity, "Refuse to stop an unverified process");
      const validate = () =>
        assert.equal(
          execFileSync(python, ["-c", verify, JSON.stringify(identity)], {
            encoding: "utf8",
          }).trim(),
          "verified",
        );
      validate();
      child.kill("SIGTERM");
      await Promise.race([
        new Promise((resolve) => child.once("exit", resolve)),
        new Promise((resolve) => setTimeout(resolve, 10000)),
      ]);
      if (child.exitCode === null && child.signalCode === null) {
        validate();
        child.kill("SIGKILL");
        await new Promise((resolve) => child.once("exit", resolve));
      }
    }
    await fs.writeFile(
      path.join(evidence, "cleanup.json"),
      JSON.stringify(
        {
          pid: child.pid,
          exitCode: child.exitCode,
          signal: child.signalCode,
          root,
          identity,
          retained: "Generated artifacts retained; owned listener stopped",
        },
        null,
        2,
      ),
    );
  }
  try {
    identity = JSON.parse(
      execFileSync(
        python,
        [
          "-c",
          identify,
          String(child.pid),
          JSON.stringify({
            cwd: repository,
            args: ["-u", script, repository, root, token],
          }),
        ],
        { encoding: "utf8" },
      ),
    );
    await fs.writeFile(
      path.join(evidence, "spawn-identity.json"),
      JSON.stringify(identity, null, 2),
    );
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      if (child.exitCode !== null)
        throw Error(`Fixture exited: ${child.exitCode}`);
      try {
        receipt = JSON.parse(
          await fs.readFile(path.join(root, "receipt.json"), "utf8"),
        );
        const response = await fetch(receipt.base + "/__fixture/receipt", {
          headers: { "x-fixture-token": token },
        });
        if (response.ok) {
          assert.deepEqual(await response.json(), receipt);
          break;
        }
      } catch (error) {
        if (error.code === "ERR_ASSERTION") throw error;
      }
      receipt = undefined;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(receipt, "Fixture startup timed out; inspect owned server log");
    assert.equal(receipt.pid, child.pid);
    assert.equal(receipt.token, token);
    assert.equal(receipt.cwd, repository);
    await fs.writeFile(
      path.join(evidence, "process-receipt.json"),
      JSON.stringify(receipt, null, 2),
    );
    await fs.writeFile(path.join(evidence, "launcher.py"), launcher);
  } catch (error) {
    await stop();
    error.message += `; preserved fixture ${root}, pid ${child.pid}`;
    throw error;
  }
  async function control(action, method = "POST") {
    const response = await fetch(`${receipt.base}/__fixture/${action}`, {
      method,
      headers: { "x-fixture-token": token },
    });
    if (!response.ok) throw Error(await response.text());
    return response.json();
  }
  return { base: receipt.base, root, receipt, control, stop };
}
