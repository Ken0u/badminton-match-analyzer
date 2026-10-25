/** Generated-only Store admission fixture; signal authority stays in fixtureOwnership. */
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import {
  repository,
  python,
  fixtureOwnership,
  fixtureProcessProbe,
} from "./frontend-fixtures.mjs";

export const admissionProbe = String.raw`
import json,os,sys,time
from pathlib import Path
repo,root,evidence=map(Path,sys.argv[1:4]);video,token=sys.argv[4:6]
os.environ['BADMINTON_ROOT']=str(repo);os.environ['BADMINTON_DATA_DIR']=str(root/'processed')
sys.path.insert(0,str(repo/'backend'))
import psutil
from badminton.storage import Store
from badminton.jobs import run_local_job
store=Store(root/'processed');job_id=None
def publish(name,value):
 temporary=evidence/(name+'.'+token+'.tmp')
 temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(evidence/name)
def work(job,progress):
 global job_id
 job_id=job;progress(.2)
 p=psutil.Process()
 publish('admission-receipt.json',{'pid':p.pid,'started':p.create_time(),'cwd':p.cwd(),'command':p.cmdline(),'exe':p.exe(),'ppid':p.ppid(),'job_id':job,'root':str(root),'token':token})
 deadline=time.monotonic()+45
 while not (evidence/'admission-release').exists():
  if time.monotonic()>deadline: raise RuntimeError('Owned admission gate expired; do not restart')
  time.sleep(.05)
 return {'purpose':'Generated CPU admission check; no inference'}
try:
 print(json.dumps(run_local_job(store,'fixture',video,work)))
finally:
 if job_id: publish('admission-job.json',store.job(job_id))
`;

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function bounded(promise, ms) {
  let timer;
  try {
    return await Promise.race([
      promise,
      new Promise((resolve) => {
        timer = setTimeout(() => resolve(null), ms);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

// Injected records exercise the same owner and startup/cleanup controller. They
// cannot change the production probe's independent signal-time identity check.
export function admissionLifetime({
  child,
  expected,
  adapter,
  release,
  persist,
  saveSpawn = async () => {},
  readJob = async () => null,
  startupMs = 20000,
  waitMs = 10000,
}) {
  let spawnError,
    exit,
    receipt,
    accepted = false,
    initialized = false;
  let stopping, ownershipEvidence;
  const finished = new Promise((resolve) => {
    child.once("error", (error) => {
      spawnError = error;
      exit = { spawnError: error.message, code: null, signal: null };
      resolve(exit);
    });
    child.once("exit", (code, signal) => {
      exit = { code, signal };
      resolve(exit);
    });
  });
  const owner = fixtureOwnership({
    pid: child.pid,
    expected,
    adapter,
    waitMs,
    persist: async (value) => {
      ownershipEvidence = structuredClone(value);
    },
  });
  function initialize() {
    if (initialized) return;
    const identity = owner.initialize();
    initialized = true;
    return identity;
  }
  async function cleanup() {
    const errors = [];
    // Read-only discovery before release records the verified launcher child,
    // including failures before receipt acceptance. No receipt grants a signal.
    try {
      if (Number.isInteger(child.pid)) {
        initialize();
        owner.discover();
      }
    } catch (error) {
      errors.push(error);
    }
    let released = false;
    try {
      await release();
      released = true;
    } catch (error) {
      errors.push(error);
    }
    const cooperative = await bounded(finished, waitMs);
    if (Number.isInteger(child.pid)) {
      try {
        await owner.stop();
      } catch (error) {
        errors.push(error);
      }
    } else if (!spawnError) {
      errors.push(
        Error("No authenticated spawned lifetime or confirmed spawn error"),
      );
    }
    const terminal = cooperative || (await bounded(finished, waitMs));
    if (!terminal)
      errors.push(
        Error("Admission exit event not observed; preserve lifetime evidence"),
      );
    let job;
    try {
      job = await readJob();
    } catch (error) {
      errors.push(error);
    }
    const complete = Number.isInteger(child.pid)
      ? ownershipEvidence?.complete === true && Boolean(terminal)
      : Boolean(spawnError) && !child.pid;
    const result = {
      ...receipt,
      root: expected.root,
      startupAccepted: accepted,
      released,
      cooperativeExit: Boolean(cooperative),
      ...terminal,
      complete,
      ownership: ownershipEvidence,
      job,
      workerStatus: spawnError
        ? "spawn-error"
        : !terminal
          ? "unknown"
          : terminal.code === 0 && terminal.signal === null
            ? "exited-zero"
            : "failed",
      storeStatus: job?.status ?? "unavailable",
      errors: errors.map((error) => error.message),
    };
    if (
      accepted &&
      (terminal?.code !== 0 ||
        terminal?.signal !== null ||
        job?.status !== "completed" ||
        job?.id !== receipt.job_id ||
        job?.owner_pid !== receipt.pid ||
        job?.owner_started !== receipt.started ||
        job?.kind !== "fixture" ||
        (expected.videoId !== undefined && job?.video_id !== expected.videoId))
    )
      errors.push(
        Error("Owned admission worker or Store job failed; preserve log"),
      );
    result.errors = errors.map((error) => error.message);
    await persist(result);
    assert.ok(
      complete && !errors.length,
      `Admission cleanup incomplete: ${result.errors.join("; ")}`,
    );
    return result;
  }
  function stop() {
    return (stopping ??= cleanup());
  }
  const handle = {
    child,
    get receipt() {
      return receipt;
    },
    stop,
    async start(readReceipt, afterInitialize = async () => {}) {
      const deadline = Date.now() + startupMs;
      try {
        if (!Number.isInteger(child.pid)) {
          await bounded(finished, waitMs);
          throw spawnError || Error("Admission spawn has no authenticated PID");
        }
        if (spawnError) throw spawnError;
        const identity = initialize();
        owner.discover();
        await saveSpawn(identity);
        await afterInitialize();
        while (true) {
          assert.ok(
            Date.now() < deadline,
            "Owned admission startup failed; inspect durable log",
          );
          if (spawnError) throw spawnError;
          if (exit || child.exitCode !== null || child.signalCode !== null)
            throw Error("Owned admission worker exited early");
          owner.discover();
          const candidate = await readReceipt();
          if (candidate !== null) {
            assert.ok(
              Date.now() < deadline,
              "Owned admission startup deadline expired",
            );
            assert.match(candidate.job_id, /^[0-9a-f]{32}$/);
            const identity = owner.bind(candidate);
            assert.equal(
              candidate.exe,
              identity.exe,
              "Admission receipt executable mismatch",
            );
            assert.equal(
              candidate.ppid,
              identity.ppid,
              "Admission receipt parent mismatch",
            );
            receipt = candidate;
            accepted = true;
            return handle;
          }
          assert.ok(
            Date.now() < deadline,
            "Owned admission startup failed; inspect durable log",
          );
          await adapter.delay(100);
        }
      } catch (error) {
        try {
          await stop();
        } catch (cleanupError) {
          error.cleanupError = cleanupError;
        }
        throw error;
      }
    },
  };
  return handle;
}

export async function startAdmission({
  root,
  evidence,
  video,
  register,
  afterInitialize,
}) {
  assert.ok(!process.env.BASE_URL, "Admission refuses existing applications");
  const parent = path.join(repository, ".cache");
  assert.equal(
    path.dirname(root),
    parent,
    "Admission requires disposable fixture root",
  );
  assert.ok(path.basename(root).startsWith("frontend-fixture-"));
  assert.equal(path.dirname(evidence), path.join(parent, "evidence"));
  assert.ok(path.basename(evidence).startsWith("frontend-"));
  assert.equal(
    typeof register,
    "function",
    "Startup cleanup registration is required",
  );
  const token = randomUUID();
  const script = path.join(evidence, "admission-probe.py");
  const receiptPath = path.join(evidence, "admission-receipt.json");
  const releasePath = path.join(evidence, "admission-release");
  for (const file of [
    receiptPath,
    releasePath,
    path.join(evidence, "admission-job.json"),
  ]) {
    await assert.rejects(
      fs.access(file),
      { code: "ENOENT" },
      "Admission evidence must be fresh",
    );
  }
  await fs.writeFile(script, admissionProbe);
  const runtime = fixtureProcessProbe({ action: "runtime" });
  const args = ["-u", script, repository, root, evidence, video.id, token];
  const env = {
    ...process.env,
    BADMINTON_ROOT: repository,
    BADMINTON_DATA_DIR: path.join(root, "processed"),
  };
  for (const key of [
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "AGENT_PROJECT_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
  ])
    delete env[key];
  const log = await fs.open(path.join(evidence, "admission.log"), "w");
  const child = spawn(python, args, {
    cwd: repository,
    env,
    stdio: ["ignore", log.fd, log.fd],
  });
  const write = (name, value) =>
    fs.writeFile(
      path.join(evidence, name),
      JSON.stringify(value, null, 2) + "\n",
    );
  const handle = admissionLifetime({
    child,
    expected: {
      root,
      cwd: repository,
      token,
      python,
      args,
      executables: [python, runtime.base],
      videoId: video.id,
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
      delay,
    },
    release: () => fs.writeFile(releasePath, "cooperative release\n"),
    persist: (value) => write("admission-cleanup.json", value),
    saveSpawn: (value) => write("admission-spawn.json", value),
    readJob: async () => {
      try {
        return JSON.parse(
          await fs.readFile(path.join(evidence, "admission-job.json"), "utf8"),
        );
      } catch (error) {
        if (error.code === "ENOENT") return null;
        throw error;
      }
    },
  });
  // Register synchronously after spawn, before closing the log or awaiting any
  // startup evidence. The start catch also owns cleanup if registration throws.
  try {
    register(handle);
    await log.close();
    return await handle.start(async () => {
      try {
        return JSON.parse(await fs.readFile(receiptPath, "utf8"));
      } catch (error) {
        if (error.code === "ENOENT") return null;
        throw error;
      }
    }, afterInitialize);
  } catch (error) {
    try {
      await log.close();
    } catch {
      /* Already closed; the initiating error stays intact. */
    }
    try {
      await handle.stop();
    } catch (cleanupError) {
      error.cleanupError ??= cleanupError;
    }
    throw error;
  }
}
