import test from "node:test";
import assert from "node:assert/strict";
import {
  appendFile,
  mkdir,
  readFile,
  rm,
  unlink,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { stage } from "../scripts/stage.mjs";

const repoRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const output = path.join(repoRoot, ".cache/frontend-stage-test");
const main = path.join(repoRoot, "backend/frontend/src/main.tsx");
// A clean checkout has no ignored cache directory before its first check.
await mkdir(path.dirname(output), { recursive: true });

test("production entry and staged runtime exclude foundation, source, and tools", async () => {
  await rm(output, { recursive: true, force: true });
  const result = await stage({ repoRoot, output });
  assert.deepEqual(result.files.sort(), [
    "THIRD_PARTY_NOTICES.txt",
    "app.js",
    "build-manifest.json",
    "index.html",
    "style.css",
  ]);
  const index = await readFile(path.join(output, "index.html"), "utf8");
  assert.match(index, /src="\/app\.js"/);
  assert.match(index, /href="\/style\.css"/);
  const app = await readFile(path.join(output, "app.js"), "utf8");
  assert.doesNotMatch(
    app,
    /Frontend foundation|Synthetic sample|legacy editor|opt-in/i,
  );
  assert.match(app, /Match library/);
  const notices = await readFile(
    path.join(output, "THIRD_PARTY_NOTICES.txt"),
    "utf8",
  );
  for (const dependency of [
    "react - 19.3.1",
    "react-dom - 19.3.1",
    "scheduler",
  ])
    assert.ok(
      notices.includes(dependency),
      `Missing runtime license: ${dependency}`,
    );
  assert.match(notices, /Permission is hereby granted/);
  assert.match(notices, /Meta Platforms/);
  const manifest = JSON.parse(
    await readFile(path.join(output, "build-manifest.json"), "utf8"),
  );
  assert.equal(manifest.schema_version, 1);
  assert.match(manifest.input_fingerprint, /^sha256:[a-f0-9]{64}$/);
  assert.deepEqual(Object.keys(manifest.assets).sort(), [
    "THIRD_PARTY_NOTICES.txt",
    "app.js",
    "index.html",
    "style.css",
  ]);
  assert.ok(manifest.inputs["package-lock.json"]);
  assert.ok(manifest.inputs[".node-version"]);
  assert.ok(manifest.inputs["backend/frontend/src/main.tsx"]);
  assert.equal(
    Object.keys(manifest.inputs).some((name) =>
      /(^|\/)(tests|node_modules|dist|\.cache)(\/|$)/.test(name),
    ),
    false,
  );
  await stage({ repoRoot, output, check: true });
});

test("check refuses altered, missing, extra, and stale-input output", async () => {
  await stage({ repoRoot, output });
  await appendFile(path.join(output, "app.js"), "\n// tampered\n");
  await assert.rejects(
    stage({ repoRoot, output, check: true }),
    /hash differs/,
  );
  await stage({ repoRoot, output });
  await unlink(path.join(output, "style.css"));
  await assert.rejects(
    stage({ repoRoot, output, check: true }),
    /file set differs/,
  );
  await stage({ repoRoot, output });
  await writeFile(path.join(output, "private-source.ts"), "secret");
  await assert.rejects(
    stage({ repoRoot, output, check: true }),
    /file set differs/,
  );
  await stage({ repoRoot, output });
  const original = await readFile(main);
  try {
    await appendFile(main, "\n");
    await assert.rejects(
      stage({ repoRoot, output, check: true }),
      /inputs are stale/,
    );
  } finally {
    await writeFile(main, original);
  }
});

test("staging refuses paths outside the repository", async () => {
  await assert.rejects(
    stage({
      repoRoot,
      output: path.join(path.dirname(repoRoot), "unsafe-stage"),
    }),
    /inside the repository/,
  );
  await assert.rejects(
    stage({ repoRoot, output: path.join(repoRoot, "backend/frontend/src") }),
    /backend\/badminton\/static|below \.cache/,
  );
});

test.after(async () => {
  await rm(output, { recursive: true, force: true });
});
