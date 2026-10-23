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

// Every signal rechecks the recorded lifetime inside psutil, whose signal methods
// also guard PID reuse. Never use taskkill /T or kill an unverified process tree.
const processProbe = String.raw`
import json, os, psutil, sys
def snapshot(p):
    result={"pid":p.pid,"metadata_errors":[]}
    with p.oneshot():
        for field, read in [("started",p.create_time),("status",p.status),
                            ("ppid",p.ppid),("cwd",p.cwd),
                            ("command",p.cmdline),("exe",p.exe)]:
            try: result[field]=read()
            except (psutil.Error, OSError) as error:
                result["metadata_errors"].append({"field":field,
                    "kind":type(error).__name__,"message":str(error)[:512]})
    return result
request=json.loads(sys.argv[1]); action=request["action"]
try:
    if action == "runtime":
        result={"base":os.path.realpath(sys._base_executable)}
    else:
        p=psutil.Process(request["pid"])
        if action == "children":
            result=[]
            for child in p.children():
                try: result.append(snapshot(child))
                except psutil.NoSuchProcess: pass
        elif action == "inspect": result=snapshot(p)
        else:
            expected=request["identity"]; actual=snapshot(p)
            valid=(not actual["metadata_errors"] and
                   actual["status"] not in (psutil.STATUS_ZOMBIE,psutil.STATUS_DEAD) and
                   all(actual.get(k) == expected[k] for k in ("pid","started","cwd","command","exe")))
            result={"signalled":False,"observation":actual}
            if not valid:
                result["error"]="Process lifetime changed or unreadable; no signal sent"
            else:
                try:
                    if request["signal"] == "SIGTERM": p.terminate()
                    else:
                        assert request["signal"] == "SIGKILL"
                        p.kill()
                    result["signalled"]=True
                except psutil.ZombieProcess as error:
                    result["error"]=str(error)[:512]
                    result["error_kind"]=type(error).__name__
                except psutil.NoSuchProcess as error:
                    # psutil also raises this for PID reuse. Only a fresh
                    # absent-PID observation (outer handler) proves absence.
                    result["observation"]=snapshot(psutil.Process(request["pid"]))
                    result["error"]=str(error)[:512]
                    result["error_kind"]=type(error).__name__
                except (psutil.Error, OSError) as error:
                    result["error"]=str(error)[:512]
                    result["error_kind"]=type(error).__name__
except psutil.ZombieProcess:
    # ZombieProcess subclasses NoSuchProcess but is not proof of absence.
    raise
except psutil.NoSuchProcess:
    result=[] if action == "children" else None
print(json.dumps(result))
`;

export function fixtureProcessProbe(request) {
  return JSON.parse(
    execFileSync(python, ["-c", processProbe, JSON.stringify(request)], {
      encoding: "utf8",
      timeout: 15000,
    }),
  );
}
const probe = fixtureProcessProbe;

const samePath = (a, b) => {
  if (typeof a !== "string" || typeof b !== "string" || !a || !b) return false;
  const normalized = (value) => path.resolve(value);
  return process.platform === "win32"
    ? normalized(a).toLowerCase() === normalized(b).toLowerCase()
    : normalized(a) === normalized(b);
};
const sameLifetime = (a, b) =>
  a &&
  b &&
  a.pid === b.pid &&
  a.started === b.started &&
  samePath(a.cwd, b.cwd) &&
  samePath(a.exe, b.exe) &&
  JSON.stringify(a.command) === JSON.stringify(b.command);

const metadataErrors = (row) => row.metadata_errors || [];
const canSignal = (a, b) =>
  sameLifetime(a, b) &&
  !metadataErrors(b).length &&
  typeof b.status === "string" &&
  !["zombie", "dead"].includes(b.status);

// This grants observation only. A zombie or disappearing field is never proof
// of exit and never authority to signal an incompletely identified lifetime.
function shutdownObservation(expected, current) {
  assert.equal(current.pid, expected.pid, "Observed PID changed");
  assert.equal(current.started, expected.started, "PID lifetime changed");
  const errors = metadataErrors(current);
  assert.ok(
    errors.every((error) =>
      ["ZombieProcess", "NoSuchProcess"].includes(error.kind),
    ),
    "Process metadata unreadable; no further signal authorized",
  );
  // Snapshot fields are not atomic: status may still be live while later
  // metadata reads are empty during exit. The authenticated lifetime can be
  // observed until the existing deadline; incomplete fields never grant a signal.
  for (const field of ["cwd", "exe", "command"]) {
    const value = current[field];
    const validType =
      value === undefined ||
      (field === "command"
        ? Array.isArray(value) &&
          value.every((part) => typeof part === "string")
        : typeof value === "string");
    const missing = validType && (value === undefined || value.length === 0);
    assert.ok(
      validType &&
        (missing ||
          (field === "command"
            ? JSON.stringify(value) === JSON.stringify(expected[field])
            : samePath(value, expected[field]))),
      `Process ${field} changed or unreadable; no further signal authorized`,
    );
  }
  assert.ok(
    (typeof current.status === "string" && current.status.length > 0) ||
      (current.status === undefined && errors.length > 0),
    "Process status unreadable; no further signal authorized",
  );
}

// Keep initial observations plus the latest one, with an explicit omission
// count. Limits affect receipts only, never the full identity used for a signal.
function recordObservation(result, phase, value) {
  const clip = (text) =>
    typeof text === "string" ? text.slice(0, 1024) : text;
  let observation = value;
  if (value) {
    observation = {
      ...value,
      cwd: clip(value.cwd),
      exe: clip(value.exe),
      command: Array.isArray(value.command)
        ? value.command.slice(0, 16).map(clip)
        : value.command,
      metadata_errors: metadataErrors(value)
        .slice(0, 8)
        .map((error) => ({
          field: clip(error.field),
          kind: clip(error.kind),
          message: clip(error.message),
        })),
    };
    if (JSON.stringify(observation) !== JSON.stringify(value))
      observation.receipt_truncated = true;
  }
  const entry = { phase, at: new Date().toISOString(), observation };
  result.observations ??= [];
  if (result.observations.length < 256) result.observations.push(entry);
  else result.omitted_observations = (result.omitted_observations || 0) + 1;
  result.last_observation = entry;
}

// Dependency injection exercises ownership decisions without touching OS PIDs.
export function fixtureOwnership({
  pid,
  expected,
  adapter,
  persist,
  waitMs = 10000,
}) {
  const owned = new Map();
  const evidence = { root: expected.root, processes: [], attempts: [] };
  let identity,
    listener,
    complete = false,
    stopping;
  function expectedProcess(row, spawn = false) {
    assert.ok(row && Number.isInteger(row.pid) && row.pid > 0);
    assert.ok(Number.isFinite(row.started) && row.started > 0);
    assert.ok(
      canSignal(row, row),
      "Fixture identity incomplete or shutting down",
    );
    assert.ok(samePath(row.cwd, expected.cwd), "Fixture cwd mismatch");
    assert.deepEqual(
      row.command.slice(1),
      expected.args,
      "Fixture command mismatch",
    );
    // POSIX venv python may be a symlink to the base executable. Its argv[0]
    // must still be the exact interpreter we spawned; descendants may use base.
    const executables = expected.executables;
    assert.ok(
      executables.some((exe) => samePath(exe, row.exe)),
      "Unexpected executable",
    );
    assert.ok(
      (spawn ? [expected.python] : executables).some((exe) =>
        samePath(exe, row.command[0]),
      ),
      "Unexpected command executable",
    );
    return row;
  }
  function initialize() {
    identity = expectedProcess(adapter.inspect(pid), true);
    assert.equal(identity.pid, pid);
    owned.set(pid, identity);
    evidence.spawn = identity;
    return identity;
  }
  function discover({ cleanup = false, observe } = {}) {
    assert.ok(identity, "No verified spawned lifetime");
    // Walk only verified expected-launcher descendants. An unrelated child can
    // never confer ownership on itself or on any of its descendants.
    for (const parent of owned.values()) {
      const current = observe ? observe(parent) : adapter.inspect(parent.pid);
      if (!current) continue;
      if (!canSignal(parent, current)) {
        assert.ok(cleanup, "Owned process lifetime changed or unreadable");
        shutdownObservation(parent, current);
        continue;
      }
      for (const row of adapter.children(parent.pid)) {
        if (owned.has(row.pid)) continue;
        try {
          expectedProcess(row);
          assert.equal(row.ppid, parent.pid, "Unexpected process parent");
          assert.ok(row.started >= parent.started, "Child predates launcher");
        } catch {
          continue;
        }
        assert.ok(owned.size < 8, "Unexpected launcher descendant depth");
        owned.set(row.pid, row);
      }
    }
  }
  function bind(receipt) {
    assert.equal(receipt.token, expected.token, "Fixture nonce mismatch");
    assert.ok(samePath(receipt.root, expected.root), "Fixture root mismatch");
    assert.ok(
      samePath(receipt.cwd, expected.cwd),
      "Fixture receipt cwd mismatch",
    );
    discover();
    const row = owned.get(receipt.pid);
    assert.ok(row, "Receipt is not an owned listener");
    assert.equal(receipt.started, row.started, "Listener lifetime mismatch");
    assert.deepEqual(receipt.command, row.command, "Listener command mismatch");
    assert.ok(
      canSignal(row, adapter.inspect(row.pid)),
      "Listener exited or changed",
    );
    listener = row;
    evidence.listener = row;
    return row;
  }
  function observe(row, result, phase) {
    try {
      const current = adapter.inspect(row.pid);
      recordObservation(result, phase, current);
      return current;
    } catch (error) {
      recordObservation(result, phase, {
        pid: row.pid,
        probe_error: {
          name: error.name,
          message: error.message.slice(0, 1024),
        },
      });
      throw error;
    }
  }
  async function terminal(row, result) {
    const until = Date.now() + waitMs;
    while (true) {
      const current = observe(row, result, "await-terminal");
      if (!current) return true;
      shutdownObservation(row, current);
      if (Date.now() >= until) return false;
      await adapter.delay(50);
    }
  }
  async function cleanup() {
    if (complete) return;
    const attempt = { processes: [], errors: [], discovery: {} };
    evidence.attempts.push(attempt);
    try {
      discover({
        cleanup: true,
        observe: (row) =>
          observe(row, attempt.discovery, `discover-${row.pid}`),
      });
    } catch (error) {
      attempt.errors.push(error.message);
    }
    // Snapshot independently verified descendants before touching the wrapper.
    // Even partial startup with a missing/bad receipt can then clean its server.
    const order = [...owned.values()].reverse();
    for (const row of order) {
      const result = { identity: row, stopped: false, signals: [] };
      attempt.processes.push(result);
      try {
        for (const signal of ["SIGTERM", "SIGKILL"]) {
          const current = observe(row, result, `before-${signal}`);
          if (!current) {
            result.stopped = true;
            break;
          }
          shutdownObservation(row, current);
          if (canSignal(row, current)) {
            // The real adapter performs its own fresh, full identity check
            // inside the same Python process that sends the signal.
            const outcome = adapter.signal(row, signal);
            recordObservation(
              result,
              `signal-${signal}`,
              outcome?.observation ?? null,
            );
            result.signal_outcomes ??= [];
            result.signal_outcomes.push({
              signal,
              signalled: outcome?.signalled === true,
              absent: outcome === null,
              error: outcome?.error,
              error_kind: outcome?.error_kind,
            });
            if (outcome === null) {
              result.stopped = true;
              break;
            }
            assert.ok(
              outcome?.signalled === true,
              outcome?.error || "Signal not confirmed",
            );
            result.signals.push(signal);
            // Synchronous probes must not starve Node's child exit/reaping
            // callbacks. Yield before the first shutdown observation.
            await adapter.delay(0);
          }
          if (await terminal(row, result)) {
            result.stopped = true;
            break;
          }
        }
        if (!result.stopped) result.stopped = await terminal(row, result);
        assert.ok(
          result.stopped,
          "Owned process failed to stop before deadline",
        );
      } catch (error) {
        result.error = error.message;
        attempt.errors.push(error.message);
      }
    }
    evidence.processes = attempt.processes;
    const terminalComplete =
      Boolean(identity) &&
      !attempt.errors.length &&
      attempt.processes.every((row) => row.stopped) &&
      (!listener ||
        attempt.processes.some(
          (row) => row.identity.pid === listener.pid && row.stopped,
        ));
    evidence.complete = terminalComplete;
    evidence.retained = terminalComplete
      ? "Generated artifacts retained; every owned lifetime verified terminal"
      : "Partial cleanup evidence retained; terminal state not established";
    await persist(evidence);
    complete = terminalComplete;
    assert.ok(
      complete,
      `Fixture cleanup incomplete: ${attempt.errors.join("; ")}`,
    );
  }
  function stop() {
    stopping ??= cleanup().finally(() => {
      stopping = undefined;
    });
    return stopping;
  }
  return { initialize, discover, bind, stop };
}

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
  const runtime = probe({ action: "runtime" });
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
  let spawnError;
  child.once("error", (error) => {
    spawnError = error;
  });
  await log.close();
  let receipt;
  const ownership = fixtureOwnership({
    pid: child.pid,
    expected: {
      cwd: repository,
      root,
      token,
      python,
      args: ["-u", script, repository, root, token],
      executables: [python, runtime.base],
    },
    adapter: {
      inspect: (pid) => probe({ action: "inspect", pid }),
      children: (pid) => probe({ action: "children", pid }),
      signal: (identity, signal) =>
        probe({ action: "signal", pid: identity.pid, identity, signal }),
      delay: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
    },
    persist: (value) =>
      fs.writeFile(
        path.join(evidence, "cleanup.json"),
        JSON.stringify(value, null, 2),
      ),
  });
  const stop = () => ownership.stop();
  try {
    if (spawnError) throw spawnError;
    const identity = ownership.initialize();
    await fs.writeFile(
      path.join(evidence, "spawn-identity.json"),
      JSON.stringify(identity, null, 2),
    );
    const deadline = Date.now() + 60000;
    while (Date.now() < deadline) {
      ownership.discover();
      if (child.exitCode !== null || child.signalCode !== null)
        throw Error(`Fixture exited: ${child.exitCode ?? child.signalCode}`);
      try {
        receipt = JSON.parse(
          await fs.readFile(path.join(root, "receipt.json"), "utf8"),
        );
        // Validate ownership and loopback address before contacting a receipt's URL.
        ownership.bind(receipt);
        const url = new URL(receipt.base);
        assert.equal(url.protocol, "http:");
        assert.equal(url.hostname, "127.0.0.1");
        assert.ok(
          url.port &&
            !url.username &&
            !url.password &&
            url.pathname === "/" &&
            !url.search &&
            !url.hash,
        );
        const response = await fetch(receipt.base + "/__fixture/receipt", {
          headers: { "x-fixture-token": token },
          signal: AbortSignal.timeout(2000),
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
    ownership.bind(receipt);
    await fs.writeFile(
      path.join(evidence, "process-receipt.json"),
      JSON.stringify(receipt, null, 2),
    );
    await fs.writeFile(path.join(evidence, "launcher.py"), launcher);
  } catch (error) {
    try {
      await stop();
    } catch (cleanup) {
      error.message += `; cleanup failed: ${cleanup.message}`;
    }
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
