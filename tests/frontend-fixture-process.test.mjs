/** Generated process records: these tests never signal an operating-system PID. */
import assert from "node:assert/strict";
import test from "node:test";
import path from "node:path";
import fs from "node:fs/promises";
import {
  fixtureOwnership,
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
      cwd,
      root,
      token: "private-nonce",
      python,
      args,
      executables: [python, base],
    },
    waitMs: 0,
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
        assert.deepEqual(
          processes.get(identity.pid),
          identity,
          "Signal-time lifetime mismatch",
        );
        signals.push({ pid: identity.pid, signal });
        if (!options.refuseExit) processes.delete(identity.pid);
      },
      delay: async () => {},
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
