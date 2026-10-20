import { spawnSync } from "node:child_process";
import { rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const workspace = fileURLToPath(new URL("../", import.meta.url));
const compiler = fileURLToPath(import.meta.resolve("typescript/bin/tsc"));
try {
  for (const args of [
    [compiler, "-p", "tsconfig.test.json"],
    [
      "--test",
      "tests/foundation.test.mjs",
      "tests/library.test.mjs",
      "tests/editor.test.mjs",
    ],
  ]) {
    const result = spawnSync(process.execPath, args, {
      cwd: workspace,
      stdio: "inherit",
    });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      process.exitCode = result.status ?? 1;
      break;
    }
  }
} finally {
  await rm(new URL("../.test-build/", import.meta.url), {
    recursive: true,
    force: true,
  });
}
