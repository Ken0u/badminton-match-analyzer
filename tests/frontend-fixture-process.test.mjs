/** Injected records plus a POSIX-only, task-generated child regression. */
import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import fs from "node:fs/promises";
import { spawn } from "node:child_process";
import { once } from "node:events";
import {
  fixtureOwnership,
  fixtureProcessProbe,
  python as fixturePython,
  repository,
  startFixture,
} from "./frontend-fixtures.mjs";

const cwd = path.resolve("generated-fixture");
const python = path.join(cwd, "venv", "python.exe");
const base = path.join(cwd, "base", "python.exe");
const root = path.join(cwd, ".cache", "fixture");
const args = ["-u", path.join(root, "launcher.py"), cwd, root, "private-nonce"];
const row = (pid = 10, extra = {}) => ({
  pid,
  started: 100 + pid,
  ppid: 1,
  status: "sleeping",
  metadata_errors: [],
  cwd,
  exe: python,
  command: [python, ...args],
  ...extra,
});
function harness(records = [row()], options = {}) {
  const processes = new Map(
    records.map((record) => [record.pid, structuredClone(record)]),
  );
  const signals = [],
    receipts = [];
  const owner = fixtureOwnership({
    pid: 10,
    expected: {
      cwd: options.cwd ?? cwd,
      root,
      token: "private-nonce",
      python,
      args,
      executables: [python, base],
    },
    waitMs: options.waitMs ?? 0,
    adapter: {
      inspect: (pid) => {
        options.beforeInspect?.(pid, processes);
        return structuredClone(processes.get(pid) || null);
      },
      children: (pid) =>
        [...processes.values()]
          .filter((p) => p.ppid === pid)
          .map((p) => structuredClone(p)),
      signal: (identity, signal) => {
        // Real adapter must check again at signal time, independently of JS.
        options.beforeSignal?.(identity.pid, processes);
        if (!processes.has(identity.pid)) return null;
        if (options.signalOutcome) return options.signalOutcome(identity);
        assert.deepEqual(
          processes.get(identity.pid),
          identity,
          "Signal-time lifetime mismatch",
        );
        const observation = structuredClone(processes.get(identity.pid));
        signals.push({ pid: identity.pid, signal });
        if (options.afterSignal) options.afterSignal(identity.pid, processes);
        else if (!options.refuseExit) processes.delete(identity.pid);
        return { signalled: true, observation };
      },
      delay: async (ms) => options.onDelay?.(ms, processes),
    },
    persist: async (value) => {
      if (options.failPersistOnce) {
        options.failPersistOnce = false;
        throw Error("Injected evidence write failure");
      }
      receipts.push(structuredClone(value));
    },
  });
  const receipt = (pid = 10) => {
    const { started, command } = processes.get(pid);
    return { pid, started, command, cwd, root, token: "private-nonce" };
  };
  return { owner, processes, signals, receipts, receipt };
}

test("direct interpreter is authenticated, stopped, terminal and idempotent", async () => {
  const h = harness();
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await h.owner.stop();
  await h.owner.stop();
  assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
  assert.equal(h.receipts.length, 1);
  assert.equal(h.receipts[0].complete, true);
  assert.equal(h.receipts[0].listener.pid, 10);
});

test("concurrent cleanup calls share one verified stop operation", async () => {
  const h = harness();
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await Promise.all([h.owner.stop(), h.owner.stop(), h.owner.stop()]);
  assert.equal(h.signals.length, 1);
  assert.equal(h.receipts.length, 1);
});

test("failed evidence write permits retry without signalling a terminal process", async () => {
  const h = harness([row()], { failPersistOnce: true });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await assert.rejects(h.owner.stop(), /evidence write failure/);
  await h.owner.stop();
  assert.equal(h.signals.length, 1);
  assert.equal(h.receipts[0].complete, true);
  assert.equal(h.receipts[0].attempts.length, 2);
});

test("venv redirector owns listener child and cleans listener before wrapper", async () => {
  const h = harness([
    row(),
    row(11, { ppid: 10, exe: base, command: [base, ...args] }),
  ]);
  h.owner.initialize();
  h.owner.bind(h.receipt(11));
  await h.owner.stop();
  assert.deepEqual(
    h.signals.map((s) => s.pid),
    [11, 10],
  );
  assert.ok(h.receipts[0].processes.every((p) => p.stopped));
  assert.equal(h.receipts[0].listener.pid, 11);
});

test("direct venv symlink retains exact command and resolved executable", async () => {
  const h = harness([row(10, { exe: base })]);
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await h.owner.stop();
  assert.equal(h.receipts[0].complete, true);
});

for (const [name, fields] of [
  ["command", { command: [python, "changed.py"] }],
  ["cwd", { cwd: path.join(cwd, "changed") }],
  ["executable", { exe: path.join(cwd, "changed.exe") }],
]) {
  test(`changed live ${name} never authorizes termination`, async () => {
    const h = harness();
    h.owner.initialize();
    h.owner.bind(h.receipt());
    Object.assign(h.processes.get(10), fields);
    await assert.rejects(h.owner.stop(), /incomplete/);
    assert.deepEqual(h.signals, []);
    assert.equal(h.receipts[0].complete, false);
  });
}

for (const [name, mutate] of [
  [
    "nonce",
    (r) => {
      r.token = "wrong";
    },
  ],
  [
    "root",
    (r) => {
      r.root = path.join(cwd, "unrelated");
    },
  ],
  [
    "cwd",
    (r) => {
      r.cwd = path.join(cwd, "elsewhere");
    },
  ],
  [
    "command",
    (r) => {
      r.command = [python, "unrelated.py"];
    },
  ],
  [
    "PID",
    (r) => {
      r.pid = 888;
    },
  ],
  [
    "creation time",
    (r) => {
      r.started += 1;
    },
  ],
]) {
  test(`bad receipt ${name} cannot authorize a stop target`, async () => {
    const h = harness([row(), row(11, { ppid: 10 })]);
    h.owner.initialize();
    const receipt = h.receipt(11);
    mutate(receipt);
    assert.throws(() => h.owner.bind(receipt));
    await h.owner.stop();
    assert.deepEqual(
      h.signals.map((s) => s.pid),
      [11, 10],
    );
    assert.equal(h.receipts[0].listener, undefined);
  });
}

for (const [name, fields] of [
  ["command", { command: [base, "unrelated.py"] }],
  ["cwd", { cwd: path.join(cwd, "elsewhere") }],
  ["executable", { exe: path.join(cwd, "other.exe") }],
  ["parent", { ppid: 999 }],
  ["creation time", { started: 1 }],
]) {
  test(`unrelated listener ${name} fails closed and is never signalled`, async () => {
    const h = harness([row(), row(11, { ppid: 10, ...fields })]);
    h.owner.initialize();
    assert.throws(() => h.owner.bind(h.receipt(11)));
    await h.owner.stop();
    assert.deepEqual(
      h.signals.map((s) => s.pid),
      [10],
    );
    assert.ok(h.processes.has(11));
  });
}

test("matching grandchild behind unrelated child cannot confer ownership", async () => {
  const h = harness([
    row(),
    row(11, { ppid: 10, command: [base, "unrelated.py"] }),
    row(12, { ppid: 11 }),
  ]);
  h.owner.initialize();
  assert.throws(() => h.owner.bind(h.receipt(12)));
  await h.owner.stop();
  assert.deepEqual(
    h.signals.map((s) => s.pid),
    [10],
  );
});

test("PID reuse after successful startup preserves failure and never signals replacement", async () => {
  const h = harness();
  h.owner.initialize();
  h.owner.bind(h.receipt());
  h.processes.get(10).started += 100;
  await assert.rejects(h.owner.stop(), /incomplete/);
  assert.deepEqual(h.signals, []);
  assert.equal(h.receipts[0].complete, false);
  assert.equal(h.receipts[0].processes[0].stopped, false);
});

test("last-moment lifetime swap is rejected inside signal adapter", async () => {
  const h = harness([row()], {
    beforeSignal: (pid, map) => {
      map.get(pid).started++;
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await assert.rejects(h.owner.stop(), /incomplete/);
  assert.deepEqual(h.signals, []);
  assert.equal(h.receipts[0].complete, false);
});

test("early listener exit does not leak wrapper or invent a signal", async () => {
  const h = harness([row(), row(11, { ppid: 10 })]);
  h.owner.initialize();
  h.owner.bind(h.receipt(11));
  h.processes.delete(11);
  await h.owner.stop();
  assert.deepEqual(
    h.signals.map((s) => s.pid),
    [10],
  );
  assert.ok(h.receipts[0].processes.every((p) => p.stopped));
});

test("wrapper exit alone cannot establish listener termination", async () => {
  const h = harness([row(), row(11, { ppid: 10 })]);
  h.owner.initialize();
  h.owner.bind(h.receipt(11));
  h.processes.delete(10);
  await h.owner.stop();
  assert.deepEqual(
    h.signals.map((s) => s.pid),
    [11],
  );
});

test("partial startup without receipt discovers only verified children", async () => {
  const h = harness([
    row(),
    row(11, { ppid: 10 }),
    row(12, { ppid: 10, command: [base, "unrelated"] }),
  ]);
  h.owner.initialize();
  await h.owner.stop();
  assert.deepEqual(
    h.signals.map((s) => s.pid),
    [11, 10],
  );
  assert.ok(h.processes.has(12));
});

test("cleanup timeout retains attempts and can be retried after verified exit", async () => {
  const h = harness([row()], { refuseExit: true });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await assert.rejects(h.owner.stop(), /incomplete/);
  assert.deepEqual(
    h.signals.map((s) => s.signal),
    ["SIGTERM", "SIGKILL"],
  );
  assert.equal(h.receipts[0].complete, false);
  h.processes.delete(10);
  await h.owner.stop();
  assert.equal(h.receipts[1].complete, true);
  assert.equal(h.receipts[1].attempts.length, 2);
});

test("failed initial identity never authorizes even the spawned PID", async () => {
  const h = harness([row(10, { command: [python, "unexpected.py"] })]);
  assert.throws(() => h.owner.initialize());
  await assert.rejects(h.owner.stop(), /incomplete/);
  assert.deepEqual(h.signals, []);
  assert.equal(h.receipts[0].complete, false);
});

const zombie = (record) => ({
  ...record,
  status: "zombie",
  cwd: "",
  command: [],
  exe: "",
});

test("shutdown metadata loss is observed through a yield to actual absence", async () => {
  const delays = [];
  const h = harness([row()], {
    waitMs: 1000,
    afterSignal: (pid, map) => map.set(pid, zombie(map.get(pid))),
    onDelay: (ms, map) => {
      delays.push(ms);
      if (ms === 50) map.delete(10);
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await h.owner.stop();
  assert.deepEqual(delays, [0, 50]);
  assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
  const result = h.receipts[0].processes[0];
  assert.ok(
    result.observations.some((entry) => entry.observation?.status === "zombie"),
  );
  assert.equal(result.last_observation.observation, null);
  assert.equal(h.receipts[0].complete, true);
});

test("persistent zombie is unknown, not terminal, and receives no second signal", async () => {
  const h = harness([row()], {
    afterSignal: (pid, map) => map.set(pid, zombie(map.get(pid))),
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await assert.rejects(h.owner.stop(), /failed to stop before deadline/);
  assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
  assert.equal(h.receipts[0].complete, false);
  assert.equal(h.receipts[0].processes[0].stopped, false);
  assert.equal(
    h.receipts[0].processes[0].last_observation.observation.status,
    "zombie",
  );
});

test("known teardown field errors permit observation but never another signal", async () => {
  const h = harness([row()], {
    waitMs: 1000,
    afterSignal: (pid, map) => {
      const record = map.get(pid);
      delete record.command;
      record.metadata_errors = [
        {
          field: "command",
          kind: "ZombieProcess",
          message: "generated teardown",
        },
      ];
    },
    onDelay: (ms, map) => {
      if (ms === 50) map.delete(10);
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await h.owner.stop();
  assert.equal(h.signals.length, 1);
  const result = h.receipts[0].processes[0];
  assert.ok(
    result.observations.some(
      (entry) =>
        entry.observation?.metadata_errors?.[0]?.kind === "ZombieProcess",
    ),
  );
  assert.equal(result.last_observation.observation, null);
});

const incomplete = [
  ["reported running status", { status: "running", command: [], exe: "" }],
  ["empty command", { command: [] }],
  ["empty executable", { exe: "" }],
  ["missing cwd", { cwd: undefined }],
  ["empty cwd", { cwd: "" }],
  [
    "all missing fields",
    { cwd: undefined, command: undefined, exe: undefined },
  ],
];
for (const [name, fields] of incomplete) {
  test(`${name} remains observable until independently absent`, async () => {
    const delays = [];
    const h = harness([row()], {
      waitMs: 1000,
      afterSignal: (pid, map) => Object.assign(map.get(pid), fields),
      onDelay: (ms, map) => {
        delays.push(ms);
        if (ms === 50) map.delete(10);
      },
    });
    h.owner.initialize();
    h.owner.bind(h.receipt());
    await h.owner.stop();
    assert.deepEqual(delays, [0, 50]);
    assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
    const receipt = h.receipts[0];
    assert.equal(receipt.complete, true);
    assert.equal(receipt.processes[0].last_observation.observation, null);
    assert.ok(
      receipt.processes[0].observations.some(
        (entry) =>
          entry.observation?.status === (fields.status || "sleeping") &&
          Object.entries(fields).every(
            ([key, value]) =>
              JSON.stringify(entry.observation[key]) === JSON.stringify(value),
          ),
      ),
    );
  });

  test(`${name} cannot extend the deadline or authorize escalation`, async (t) => {
    t.mock.timers.enable({ apis: ["Date"], now: 0 });
    const h = harness([row()], {
      waitMs: 100,
      afterSignal: (pid, map) => Object.assign(map.get(pid), fields),
      onDelay: (ms) => t.mock.timers.tick(Math.max(1, ms)),
    });
    h.owner.initialize();
    h.owner.bind(h.receipt());
    await assert.rejects(h.owner.stop(), /failed to stop before deadline/);
    // Existing cleanup has TERM, KILL and final observation windows, even
    // when incomplete identity prevents sending the escalation signal.
    assert.equal(Date.now(), 3 * 100 + 1);
    assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
    assert.equal(h.receipts[0].complete, false);
    assert.equal(h.receipts[0].processes[0].stopped, false);
    assert.notEqual(
      h.receipts[0].processes[0].last_observation.observation,
      null,
    );
  });
}

test("metadata loss before cleanup permits observation but never the first signal", async () => {
  const h = harness([row()], {
    waitMs: 1000,
    onDelay: (ms, map) => {
      if (ms === 50) map.delete(10);
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  h.processes.get(10).command = [];
  await h.owner.stop();
  assert.deepEqual(h.signals, []);
  assert.equal(h.receipts[0].complete, true);
  assert.equal(h.receipts[0].processes[0].last_observation.observation, null);
});

test("empty cwd cannot resolve to the observer cwd to authorize escalation", async () => {
  const h = harness([row(10, { cwd: process.cwd() })], {
    cwd: process.cwd(),
    afterSignal: (pid, map) => {
      map.get(pid).cwd = "";
    },
  });
  h.owner.initialize();
  // No receipt is needed to clean a verified spawned lifetime.
  await assert.rejects(h.owner.stop(), /failed to stop before deadline/);
  assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
  assert.equal(h.receipts[0].complete, false);
});

for (const [name, fields] of [
  ["live command", { command: [python, "changed.py"] }],
  ["live cwd", { cwd: path.join(cwd, "changed") }],
  ["live executable", { exe: path.join(cwd, "changed.exe") }],
  ["zombie command", { status: "zombie", command: [python, "changed.py"] }],
  ["zombie cwd", { status: "zombie", cwd: path.join(cwd, "changed") }],
  [
    "zombie executable",
    { status: "zombie", exe: path.join(cwd, "changed.exe") },
  ],
  ["creation time", { started: 999 }],
  ["missing creation time", { started: undefined, status: "zombie" }],
  ["changed PID with missing metadata", { pid: 11, command: [], exe: "" }],
  ["changed creation with missing metadata", { started: 999, command: [] }],
  [
    "conflicting cwd with missing metadata",
    { cwd: path.join(cwd, "changed"), command: [] },
  ],
  [
    "conflicting executable with missing metadata",
    { exe: path.join(cwd, "changed.exe"), command: [] },
  ],
  [
    "conflicting command with missing metadata",
    { command: [python, "changed.py"], exe: "" },
  ],
  ["unknown status", { status: undefined, command: [] }],
  ["empty status", { status: "", command: [] }],
  ["malformed cwd", { cwd: [], command: [] }],
  ["null cwd", { cwd: null, command: [] }],
  ["malformed executable", { exe: [], command: [] }],
  ["malformed command", { command: "", exe: "" }],
  ["malformed command elements", { command: [42], exe: "" }],
  [
    "permission denied",
    {
      status: "zombie",
      metadata_errors: [
        { field: "cwd", kind: "AccessDenied", message: "generated denial" },
      ],
    },
  ],
]) {
  test(`after first signal ${name} preserves evidence and fails closed`, async () => {
    const h = harness([row()], {
      afterSignal: (pid, map) => Object.assign(map.get(pid), fields),
    });
    h.owner.initialize();
    h.owner.bind(h.receipt());
    await assert.rejects(h.owner.stop(), /incomplete/);
    assert.deepEqual(h.signals, [{ pid: 10, signal: "SIGTERM" }]);
    const receipt = h.receipts[0];
    assert.equal(receipt.complete, false);
    assert.equal(receipt.processes[0].stopped, false);
    for (const [field, value] of Object.entries(fields))
      assert.deepEqual(
        receipt.processes[0].last_observation.observation[field],
        value,
      );
  });
}

test("signal-time disappearance is terminal evidence and never recorded as a signal", async () => {
  const h = harness([row()], {
    beforeSignal: (pid, map) => map.delete(pid),
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await h.owner.stop();
  assert.deepEqual(h.signals, []);
  assert.deepEqual(h.receipts[0].processes[0].signals, []);
  assert.deepEqual(h.receipts[0].processes[0].signal_outcomes, [
    {
      signal: "SIGTERM",
      signalled: false,
      absent: true,
      error: undefined,
      error_kind: undefined,
    },
  ]);
  assert.equal(h.receipts[0].complete, true);
});

test("signal-time zombie error is not absence or a confirmed signal", async () => {
  const h = harness([row()], {
    signalOutcome: (identity) => ({
      signalled: false,
      observation: { ...identity, status: "zombie" },
      error: "Generated process became a zombie at signal boundary",
      error_kind: "ZombieProcess",
    }),
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await assert.rejects(h.owner.stop(), /became a zombie/);
  assert.deepEqual(h.signals, []);
  const receipt = h.receipts[0];
  assert.equal(receipt.complete, false);
  assert.equal(receipt.processes[0].stopped, false);
  assert.equal(receipt.processes[0].signal_outcomes[0].absent, false);
  assert.equal(
    receipt.processes[0].signal_outcomes[0].error_kind,
    "ZombieProcess",
  );
  assert.equal(
    receipt.processes[0].last_observation.observation.status,
    "zombie",
  );
});

test("production probe distinguishes signal exceptions from freshly verified absence", async () => {
  const parent = path.join(repository, ".cache/evidence");
  await fs.mkdir(parent, { recursive: true });
  const evidence = await fs.mkdtemp(
    path.join(parent, "fixture-probe-outcomes-"),
  );
  // A generated psutil double exercises the actual Python exception handlers.
  // PID zero makes an accidentally loaded real psutil refuse any signal.
  await fs.writeFile(
    path.join(evidence, "psutil.py"),
    String.raw`
import contextlib, json, os, sys
class Error(Exception): pass
class NoSuchProcess(Error): pass
class ZombieProcess(NoSuchProcess): pass
STATUS_ZOMBIE="zombie"
STATUS_DEAD="dead"
identity=json.loads(sys.argv[1])["identity"]
scenario=os.environ["FRONTEND_PROBE_SCENARIO"]
class Process:
    count=0
    def __init__(self,pid):
        Process.count+=1
        self.ordinal=Process.count
        self.pid=pid
        if self.ordinal>1 and scenario=="absent": raise NoSuchProcess("generated absent")
    def oneshot(self): return contextlib.nullcontext()
    def create_time(self): return identity["started"]+(1 if self.ordinal>1 else 0)
    def status(self): return "running" if scenario=="incomplete" else "sleeping"
    def ppid(self): return 1
    def cwd(self): return identity["cwd"]
    def cmdline(self): return [] if scenario=="incomplete" else identity["command"]
    def exe(self): return "" if scenario=="incomplete" else identity["exe"]
    def terminate(self):
        if scenario=="incomplete": raise AssertionError("Incomplete metadata must never grant a signal")
        if scenario=="zombie": raise ZombieProcess("generated zombie")
        raise NoSuchProcess("generated absent or reused")
    def kill(self): raise AssertionError("No escalation expected")
`,
  );
  const originalPath = process.env.PYTHONPATH;
  const originalScenario = process.env.FRONTEND_PROBE_SCENARIO;
  const results = {};
  try {
    process.env.PYTHONPATH = evidence;
    for (const scenario of ["absent", "reused", "zombie", "incomplete"]) {
      process.env.FRONTEND_PROBE_SCENARIO = scenario;
      results[scenario] = fixtureProcessProbe({
        action: "signal",
        pid: 0,
        identity: row(0),
        signal: "SIGTERM",
      });
      if (scenario === "incomplete")
        results.incompleteSnapshot = fixtureProcessProbe({
          action: "inspect",
          pid: 0,
          identity: row(0),
        });
    }
  } finally {
    if (originalPath === undefined) delete process.env.PYTHONPATH;
    else process.env.PYTHONPATH = originalPath;
    if (originalScenario === undefined)
      delete process.env.FRONTEND_PROBE_SCENARIO;
    else process.env.FRONTEND_PROBE_SCENARIO = originalScenario;
  }
  await fs.writeFile(
    path.join(evidence, "outcomes.json"),
    JSON.stringify(results, null, 2),
  );
  assert.equal(results.absent, null);
  assert.equal(results.reused.signalled, false);
  assert.equal(results.reused.observation.started, row(0).started + 1);
  assert.equal(results.reused.error_kind, "NoSuchProcess");
  assert.equal(results.zombie.signalled, false);
  assert.equal(results.zombie.error_kind, "ZombieProcess");
  assert.equal(results.incomplete.signalled, false);
  assert.match(results.incomplete.error, /no signal sent/);
  assert.deepEqual(results.incomplete.observation, results.incompleteSnapshot);
  assert.equal(results.incompleteSnapshot.status, "running");
  assert.deepEqual(results.incompleteSnapshot.command, []);
  assert.equal(results.incompleteSnapshot.exe, "");
  assert.deepEqual(results.incompleteSnapshot.metadata_errors, []);
});

test("shutdown probe failure is retained without authorizing another signal", async () => {
  let inaccessible = false;
  const h = harness([row()], {
    afterSignal: () => {
      inaccessible = true;
    },
    beforeInspect: () => {
      if (inaccessible) throw Error("generated probe inaccessible");
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await assert.rejects(h.owner.stop(), /generated probe inaccessible/);
  const receipt = h.receipts[0];
  assert.equal(receipt.complete, false);
  assert.equal(h.signals.length, 1);
  assert.equal(
    receipt.processes[0].last_observation.observation.probe_error.message,
    "generated probe inaccessible",
  );
});

test("discovery probe error is retained as structured partial evidence", async () => {
  let inaccessible = false;
  const h = harness([row()], {
    beforeInspect: () => {
      if (inaccessible) throw Error("generated discovery denied");
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  inaccessible = true;
  await assert.rejects(h.owner.stop(), /generated discovery denied/);
  assert.deepEqual(h.signals, []);
  assert.equal(h.receipts[0].complete, false);
  assert.equal(
    h.receipts[0].attempts[0].discovery.last_observation.observation.probe_error
      .message,
    "generated discovery denied",
  );
});

test("observation receipt is capped, counts omissions and retains latest absence", async () => {
  let polls = 0;
  const h = harness([row()], {
    waitMs: 1000,
    afterSignal: (pid, map) => map.set(pid, zombie(map.get(pid))),
    onDelay: (ms, map) => {
      if (ms === 50 && ++polls === 400) map.delete(10);
    },
  });
  h.owner.initialize();
  h.owner.bind(h.receipt());
  await h.owner.stop();
  const result = h.receipts[0].processes[0];
  assert.equal(result.observations.length, 256);
  assert.ok(result.omitted_observations > 0);
  assert.equal(result.last_observation.observation, null);
  assert.equal(result.stopped, true);
  assert.equal(h.signals.length, 1);
});

test(
  "actual POSIX generated child exits and is reaped before cleanup completes",
  {
    skip:
      process.platform === "win32"
        ? "POSIX exit/reaping regression; Windows uses generated fixture coverage"
        : false,
  },
  async () => {
    const parent = path.join(repository, ".cache/evidence");
    await fs.mkdir(parent, { recursive: true });
    const evidence = await fs.mkdtemp(path.join(parent, "fixture-posix-exit-"));
    const token = "generated-posix-exit";
    const childArgs = [
      "-u",
      "-c",
      "import time; time.sleep(10)",
      evidence,
      token,
    ];
    const child = spawn(fixturePython, childArgs, {
      cwd: repository,
      stdio: "ignore",
      env: {
        ...process.env,
        BADMINTON_ROOT: repository,
        BADMINTON_DATA_DIR: path.join(evidence, "processed"),
      },
    });
    await once(child, "spawn");
    const runtime = fixtureProcessProbe({ action: "runtime" });
    const owner = fixtureOwnership({
      pid: child.pid,
      expected: {
        cwd: repository,
        root: evidence,
        token,
        python: fixturePython,
        args: childArgs,
        executables: [fixturePython, runtime.base],
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
      persist: (value) =>
        fs.writeFile(
          path.join(evidence, "cleanup.json"),
          JSON.stringify(value, null, 2),
        ),
    });
    let identity;
    try {
      identity = owner.initialize();
      await fs.writeFile(
        path.join(evidence, "spawn-identity.json"),
        JSON.stringify(identity, null, 2),
      );
      await owner.stop();
      const cleanup = JSON.parse(
        await fs.readFile(path.join(evidence, "cleanup.json"), "utf8"),
      );
      assert.equal(cleanup.complete, true);
      assert.equal(cleanup.processes[0].last_observation.observation, null);
      assert.ok(
        child.exitCode !== null || child.signalCode !== null,
        "Original child must be reaped",
      );
    } finally {
      // The pure generated child self-expires after ten seconds. Even a failed
      // identity check never permits an unverified fallback kill.
      if (child.exitCode === null && child.signalCode === null)
        await once(child, "exit");
      await fs.writeFile(
        path.join(evidence, "child-exit.json"),
        JSON.stringify(
          {
            pid: child.pid,
            started: identity?.started,
            code: child.exitCode,
            signal: child.signalCode,
          },
          null,
          2,
        ),
      );
    }
  },
);

test(
  "actual generated listener cleans up after normal and failed startup",
  {
    skip: process.env.FRONTEND_FIXTURE_LIVE !== "1",
  },
  async () => {
    const parent = path.join(repository, ".cache/evidence");
    await fs.mkdir(parent, { recursive: true });
    for (const fail of [false, true]) {
      const evidence = await fs.mkdtemp(
        path.join(
          parent,
          fail ? "fixture-live-failure-" : "fixture-live-normal-",
        ),
      );
      const originalFetch = globalThis.fetch;
      if (fail)
        globalThis.fetch = async (...args) => {
          const response = await originalFetch(...args);
          const body = await response.json();
          return {
            ok: true,
            json: async () => ({
              ...body,
              token: "injected-response-mismatch",
            }),
          };
        };
      let fixture;
      try {
        if (fail) {
          let expectedError;
          await assert.rejects(startFixture(evidence), (error) => {
            assert.match(error.message, /injected-response-mismatch/);
            expectedError = { name: error.name, message: error.message };
            return true;
          });
          await fs.writeFile(
            path.join(evidence, "expected-startup-error.json"),
            JSON.stringify(expectedError, null, 2),
          );
        } else fixture = await startFixture(evidence);
      } finally {
        globalThis.fetch = originalFetch;
        if (fixture) {
          await fixture.stop();
          await fixture.stop();
        }
      }
      const cleanup = JSON.parse(
        await fs.readFile(path.join(evidence, "cleanup.json"), "utf8"),
      );
      assert.equal(cleanup.complete, true);
      assert.ok(
        cleanup.processes.length && cleanup.processes.every((p) => p.stopped),
      );
    }
  },
);
