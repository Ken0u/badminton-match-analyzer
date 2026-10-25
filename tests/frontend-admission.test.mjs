/** Injected identity decisions and opt-in real, generated-only process evidence. */
import assert from "node:assert/strict";
import test from "node:test";
import { EventEmitter } from "node:events";
import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";
import { admissionLifetime, startAdmission } from "./frontend-admission.mjs";
import {
  repository,
  python,
  fixtureProcessProbe,
  startFixture,
} from "./frontend-fixtures.mjs";

function harness({
  descendant = false,
  releaseFails = false,
  cooperative = true,
  startupMs = 100,
} = {}) {
  const cwd = path.resolve("generated-admission");
  const interpreter = path.join(cwd, "venv", "python.exe");
  const base = path.join(cwd, "base", "python.exe");
  const expected = {
    cwd,
    root: path.join(cwd, "fixture"),
    python: interpreter,
    token: "fresh-nonce",
    args: ["-u", "generated.py", "fresh-nonce"],
    executables: [interpreter, base],
  };
  const row = (pid, extra = {}) => ({
    pid,
    started: 100 + pid,
    ppid: 1,
    cwd,
    exe: interpreter,
    status: "sleeping",
    metadata_errors: [],
    command: [interpreter, ...expected.args],
    ...extra,
  });
  const records = new Map([[10, row(10)]]);
  if (descendant)
    records.set(
      20,
      row(20, { ppid: 10, exe: base, command: [base, ...expected.args] }),
    );
  const worker = structuredClone(records.get(descendant ? 20 : 10));
  const receipt = {
    ...worker,
    token: expected.token,
    root: expected.root,
    job_id: "a".repeat(32),
  };
  const child = Object.assign(new EventEmitter(), {
    pid: 10,
    exitCode: null,
    signalCode: null,
  });
  const signals = [],
    snapshots = [],
    actions = [];
  function exit(code = 0, signal = null) {
    records.clear();
    child.exitCode = code;
    child.signalCode = signal;
    child.emit("exit", code, signal);
  }
  const handle = admissionLifetime({
    child,
    expected,
    startupMs,
    waitMs: 0,
    adapter: {
      inspect: (pid) => structuredClone(records.get(pid) || null),
      children: (pid) =>
        [...records.values()]
          .filter((row) => row.ppid === pid)
          .map((row) => structuredClone(row)),
      signal: (identity, signal) => {
        assert.deepEqual(
          records.get(identity.pid),
          identity,
          "Independent signal-time identity check",
        );
        actions.push("signal");
        signals.push({ pid: identity.pid, signal });
        const observation = structuredClone(identity);
        records.delete(identity.pid);
        if (!records.size) exit(null, signal);
        return { signalled: true, observation };
      },
      delay: async () => new Promise((resolve) => setImmediate(resolve)),
    },
    release: async () => {
      actions.push("release");
      if (releaseFails) throw Error("Injected release failure");
      if (cooperative) exit();
    },
    readJob: async () => ({
      id: receipt.job_id,
      owner_pid: worker.pid,
      owner_started: worker.started,
      kind: "fixture",
      status: child.exitCode === 0 ? "completed" : "failed",
    }),
    persist: async (value) => snapshots.push(structuredClone(value)),
  });
  return { handle, receipt, records, signals, snapshots, child, exit, actions };
}

for (const descendant of [false, true]) {
  test(`${descendant ? "verified launcher descendant" : "direct interpreter"}: cooperative and concurrent cleanup`, async () => {
    const h = harness({ descendant });
    await h.handle.start(async () => h.receipt);
    const a = h.handle.stop(),
      b = h.handle.stop();
    assert.equal(a, b);
    const result = await a;
    assert.equal(await h.handle.stop(), result);
    assert.equal(result.startupAccepted, true);
    assert.equal(result.complete, true);
    assert.equal(result.job.status, "completed");
    assert.equal(result.ownership.processes.length, descendant ? 2 : 1);
    assert.ok(
      result.ownership.processes.every(
        (row) => row.stopped && row.last_observation.observation === null,
      ),
    );
    assert.deepEqual(h.signals, []);
    assert.deepEqual(h.actions, ["release"]);
    assert.equal(h.snapshots.length, 1);
  });
}

for (const [name, mutate] of [
  [
    "nonce",
    (r) => {
      r.token = "stale";
    },
  ],
  [
    "root",
    (r) => {
      r.root += "-other";
    },
  ],
  [
    "cwd",
    (r) => {
      r.cwd += "-other";
    },
  ],
  [
    "lifetime",
    (r) => {
      r.started += 1;
    },
  ],
  [
    "argv",
    (r) => {
      r.command.push("unrelated");
    },
  ],
  [
    "executable",
    (r) => {
      r.exe += "-other";
    },
  ],
  [
    "parent",
    (r) => {
      r.ppid += 1;
    },
  ],
  [
    "unrelated PID",
    (r) => {
      r.pid = 999;
    },
  ],
  [
    "job ID",
    (r) => {
      r.job_id = "../other";
    },
  ],
]) {
  test(`reject ${name} receipt and clean only the independently owned tree`, async () => {
    const h = harness({ descendant: true });
    mutate(h.receipt);
    await assert.rejects(h.handle.start(async () => h.receipt));
    assert.equal(h.snapshots[0].startupAccepted, false);
    assert.equal(h.snapshots[0].complete, true);
    assert.equal(h.snapshots[0].ownership.processes.length, 2);
    assert.deepEqual(h.signals, []);
  });
}

for (const [name, read] of [
  ["missing", async () => null],
  ["malformed", async () => JSON.parse("{")],
]) {
  test(`${name} startup receipt retains cleanup responsibility`, async () => {
    const h = harness();
    await assert.rejects(
      h.handle.start(read),
      name === "missing" ? /startup failed/ : SyntaxError,
    );
    assert.equal(h.snapshots[0].startupAccepted, false);
    assert.equal(h.snapshots[0].complete, true);
  });
}

test("failure before receipt acceptance keeps the initiating error", async () => {
  const h = harness({ descendant: true });
  const original = Error("Injected startup failure");
  await assert.rejects(
    h.handle.start(
      async () => h.receipt,
      async () => {
        throw original;
      },
    ),
    (error) => error === original,
  );
  assert.equal(h.snapshots[0].startupAccepted, false);
  assert.equal(h.snapshots[0].ownership.processes.length, 2);
});

test("cleanup failure is attached without replacing the startup error; no changed lifetime is signalled", async () => {
  const h = harness({ cooperative: false });
  const original = Error("Initiating failure");
  await assert.rejects(
    h.handle.start(
      async () => h.receipt,
      async () => {
        h.records.get(10).started += 1;
        // The unrelated replacement process is deliberately left in the fake map.
        throw original;
      },
    ),
    (error) =>
      error === original &&
      /cleanup incomplete/.test(error.cleanupError.message),
  );
  assert.equal(h.snapshots[0].complete, false);
  assert.deepEqual(h.signals, []);
  await assert.rejects(h.handle.stop());
  assert.equal(h.snapshots.length, 1);
});

test("fallback uses existing owner after bounded cooperative attempt", async () => {
  const h = harness({ descendant: true, cooperative: false });
  const original = Error("Failed startup");
  await assert.rejects(
    h.handle.start(
      async () => h.receipt,
      async () => {
        throw original;
      },
    ),
    (error) => error === original,
  );
  assert.deepEqual(h.actions, ["release", "signal", "signal"]);
  assert.equal(h.snapshots[0].complete, true);
  assert.equal(h.snapshots[0].cooperativeExit, false);
  assert.equal(h.snapshots[0].job.status, "failed");
});

test("release failure is retained even when fallback proves terminal", async () => {
  const h = harness({ releaseFails: true });
  await assert.rejects(
    h.handle.start(async () => null),
    /startup failed/,
  );
  assert.equal(h.snapshots[0].released, false);
  assert.equal(h.snapshots[0].complete, true);
  assert.match(h.snapshots[0].errors.join(), /release failure/);
});

test("early exit cannot be accepted as a startup receipt", async () => {
  const h = harness();
  await assert.rejects(
    h.handle.start(
      async () => h.receipt,
      async () => h.exit(2),
    ),
    /exited early/,
  );
  assert.equal(h.snapshots[0].code, 2);
  assert.equal(h.snapshots[0].startupAccepted, false);
});

test("a valid receipt arriving after the unchanged startup deadline is rejected", async () => {
  const h = harness({ startupMs: 1 });
  await assert.rejects(
    h.handle.start(
      async () => h.receipt,
      async () => {
        await new Promise((resolve) => setTimeout(resolve, 5));
      },
    ),
    /startup failed/,
  );
  assert.equal(h.snapshots[0].startupAccepted, false);
  assert.equal(h.snapshots[0].complete, true);
});

test("confirmed spawn error needs no signal and preserves original error", async () => {
  const child = Object.assign(new EventEmitter(), {
    pid: undefined,
    exitCode: null,
    signalCode: null,
  });
  const original = Object.assign(Error("Generated ENOENT"), { code: "ENOENT" });
  const snapshots = [];
  const h = admissionLifetime({
    child,
    expected: { root: "generated" },
    waitMs: 10,
    adapter: {},
    release: async () => {},
    persist: async (v) => snapshots.push(v),
  });
  queueMicrotask(() => child.emit("error", original));
  await assert.rejects(
    h.start(async () => null),
    (error) => error === original,
  );
  assert.equal(snapshots[0].complete, true);
  assert.match(snapshots[0].spawnError, /ENOENT/);
});

const actual = process.env.FRONTEND_ADMISSION_PROCESS_TEST === "1";
const adapter = {
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
};

test(
  "actual spawn error is retained without inventing a process lifetime",
  { skip: !actual },
  async () => {
    const evidence = await fs.mkdtemp(
      path.join(repository, ".cache/evidence/frontend-admission-spawn-"),
    );
    const child = spawn(path.join(evidence, "nonexistent-python.exe"), [], {
      cwd: repository,
    });
    const handle = admissionLifetime({
      child,
      expected: { root: evidence },
      adapter,
      release: async () => {},
      persist: (value) =>
        fs.writeFile(
          path.join(evidence, "cleanup.json"),
          JSON.stringify(value, null, 2),
        ),
    });
    await assert.rejects(
      handle.start(async () => null),
      (error) => error.code === "ENOENT" && !error.cleanupError,
    );
    const result = await handle.stop();
    assert.equal(result.workerStatus, "spawn-error");
    assert.equal(result.complete, true);
  },
);

test(
  "actual generated direct base-interpreter lifetime (controller only, no Store)",
  { skip: !actual },
  async () => {
    const evidence = await fs.mkdtemp(
      path.join(repository, ".cache/evidence/frontend-admission-direct-"),
    );
    const script = path.join(evidence, "direct.py"),
      release = path.join(evidence, "release");
    await fs.writeFile(
      script,
      "import pathlib,sys,time\np=pathlib.Path(sys.argv[1])\nwhile not p.exists(): time.sleep(.05)\n",
    );
    const base = fixtureProcessProbe({ action: "runtime" }).base;
    const args = ["-u", script, release];
    const child = spawn(base, args, { cwd: repository, stdio: "ignore" });
    const handle = admissionLifetime({
      child,
      expected: {
        cwd: repository,
        root: evidence,
        token: "direct-generated",
        python: base,
        args,
        executables: [base],
      },
      adapter,
      release: () => fs.writeFile(release, "release\n"),
      // This standalone process tests OS ownership only; no Store result is claimed.
      readJob: async () => ({
        id: "b".repeat(32),
        owner_pid: child.pid,
        owner_started: handle.receipt.started,
        kind: "fixture",
        status: "completed",
        generatedControllerDouble: true,
      }),
      persist: (v) =>
        fs.writeFile(
          path.join(evidence, "cleanup.json"),
          JSON.stringify(v, null, 2),
        ),
    });
    try {
      await handle.start(async () => ({
        ...adapter.inspect(child.pid),
        root: evidence,
        token: "direct-generated",
        job_id: "b".repeat(32),
      }));
    } finally {
      await handle.stop();
    }
    assert.equal(adapter.inspect(child.pid), null);
  },
);

test(
  "actual normal project venv Store admission and failure before receipt acceptance",
  { skip: !actual },
  async () => {
    assert.equal(process.env.__PYVENV_LAUNCHER__, undefined);
    if (process.platform === "win32")
      assert.match(python, /[\\/]\.venv[\\/]Scripts[\\/]python.exe$/i);
    const parent = path.join(repository, ".cache/evidence");
    await fs.mkdir(parent, { recursive: true });
    const evidence = await fs.mkdtemp(
      path.join(parent, "frontend-admission-fixture-"),
    );
    const fixture = await startFixture(evidence);
    const receipts = [];
    try {
      const seeded = await fixture.control("seed");
      for (const failing of [false, true]) {
        const folder = await fs.mkdtemp(
          path.join(parent, "frontend-admission-"),
        );
        let owned;
        const original = Error(
          "Actual injected startup failure before receipt acceptance",
        );
        const run = startAdmission({
          root: fixture.root,
          evidence: folder,
          video: seeded.rally,
          register: (handle) => {
            owned = handle;
          },
          afterInitialize: failing
            ? async () => {
                throw original;
              }
            : undefined,
        });
        try {
          if (failing)
            await assert.rejects(
              run,
              (error) => error === original && !error.cleanupError,
            );
          else await run;
        } finally {
          if (owned) await owned.stop();
        }
        const result = JSON.parse(
          await fs.readFile(
            path.join(folder, "admission-cleanup.json"),
            "utf8",
          ),
        );
        assert.equal(result.complete, true);
        assert.equal(result.code, 0);
        assert.equal(result.job.status, "completed");
        assert.equal(result.startupAccepted, !failing);
        if (process.platform === "win32")
          assert.ok(result.ownership.processes.length >= 2);
        for (const row of result.ownership.processes) {
          assert.equal(adapter.inspect(row.identity.pid), null);
          assert.deepEqual(row.signals, []);
        }
        receipts.push({
          folder,
          startupAccepted: !failing,
          processes: result.ownership.processes.length,
        });
      }
      await fs.writeFile(
        path.join(evidence, "admission-tests.json"),
        JSON.stringify(receipts, null, 2),
      );
    } finally {
      await fixture.stop();
    }
  },
);
