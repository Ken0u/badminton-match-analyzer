import { createHash } from "node:crypto";
import {
  cp,
  lstat,
  mkdir,
  readFile,
  readdir,
  realpath,
  rm,
  writeFile,
} from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");
const slash = (value) => value.split(path.sep).join("/");

async function filesBelow(root) {
  const result = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const absolute = path.join(directory, entry.name);
      if (entry.isSymbolicLink())
        throw new Error(`Symlinks are not allowed: ${absolute}`);
      if (entry.isDirectory()) await visit(absolute);
      else if (entry.isFile())
        result.push(slash(path.relative(root, absolute)));
      else throw new Error(`Unsupported build entry: ${absolute}`);
    }
  }
  await visit(root);
  return result.sort();
}

function safeRelative(value) {
  return (
    value &&
    value === slash(value) &&
    !path.posix.isAbsolute(value) &&
    !value.split("/").some((part) => !part || part === "." || part === "..")
  );
}

async function hashes(root, names) {
  return Object.fromEntries(
    await Promise.all(
      names.map(async (name) => {
        if (!safeRelative(name))
          throw new Error(`Unsafe relative path: ${name}`);
        return [name, sha256(await readFile(path.join(root, name)))];
      }),
    ),
  );
}

async function inputNames(repoRoot) {
  const frontend = path.join(repoRoot, "backend/frontend");
  const names = [".node-version", "package-lock.json"];
  for (const name of [
    "index.html",
    "package.json",
    "tsconfig.json",
    "tsconfig.test.json",
    "vite.config.js",
  ])
    names.push(`backend/frontend/${name}`);
  for (const directory of ["scripts", "src"]) {
    for (const name of await filesBelow(path.join(frontend, directory)))
      names.push(`backend/frontend/${directory}/${name}`);
  }
  return names.sort();
}

function validateRuntimeFiles(names) {
  if (
    !names.includes("index.html") ||
    !names.includes("app.js") ||
    !names.includes("style.css")
  )
    throw new Error(
      "Production build must contain index.html, app.js and style.css",
    );
  for (const name of names) {
    if (
      !safeRelative(name) ||
      name === "build-manifest.json" ||
      /(^|\/)(src|scripts|tests|node_modules)(\/|$)/.test(name) ||
      /\.(?:map|tsx?|jsx|md|json)$/i.test(name)
    )
      throw new Error(
        `Build contains a source, tool, manifest, or unsafe file: ${name}`,
      );
  }
}

function manifestBytes(inputHashes, assetHashes) {
  const fingerprint = sha256(
    Buffer.from(
      Object.entries(inputHashes)
        .map(([name, hash]) => `${name}\0${hash}\n`)
        .join(""),
    ),
  );
  return Buffer.from(
    `${JSON.stringify(
      {
        schema_version: 1,
        input_fingerprint: `sha256:${fingerprint}`,
        inputs: inputHashes,
        assets: assetHashes,
      },
      null,
      2,
    )}\n`,
  );
}

async function assertOutput(repoRoot, output) {
  const relative = path.relative(repoRoot, output);
  if (
    !relative ||
    relative.startsWith(`..${path.sep}`) ||
    path.isAbsolute(relative)
  )
    throw new Error("Output must be a directory inside the repository");
  const relativeSlash = slash(relative);
  if (
    relativeSlash !== "backend/badminton/static" &&
    !relativeSlash.startsWith(".cache/")
  )
    throw new Error(
      "Output must be backend/badminton/static or a directory below .cache",
    );
  const parent = await realpath(path.dirname(output));
  const resolved = path.join(parent, path.basename(output));
  if (resolved !== output) throw new Error("Output path must be canonical");
  try {
    if ((await lstat(output)).isSymbolicLink())
      throw new Error("Output must not be a symlink");
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}

export async function stage({ repoRoot, output, check = false }) {
  repoRoot = path.resolve(repoRoot);
  output = path.resolve(output);
  await assertOutput(repoRoot, output);
  const frontend = path.join(repoRoot, "backend/frontend");
  const dist = path.join(frontend, "dist");
  const runtime = await filesBelow(dist);
  validateRuntimeFiles(runtime);
  const assetHashes = await hashes(dist, runtime);
  const inputHashes = await hashes(repoRoot, await inputNames(repoRoot));
  const expectedManifest = manifestBytes(inputHashes, assetHashes);
  if (check) {
    const actual = await filesBelow(output);
    const expected = [...runtime, "build-manifest.json"].sort();
    if (JSON.stringify(actual) !== JSON.stringify(expected))
      throw new Error(
        `Staged file set differs: expected ${expected.join(", ")}; received ${actual.join(", ")}`,
      );
    for (const [name, hash] of Object.entries(assetHashes))
      if (sha256(await readFile(path.join(output, name))) !== hash)
        throw new Error(`Staged asset hash differs: ${name}`);
    const presentManifest = await readFile(
      path.join(output, "build-manifest.json"),
    );
    if (!presentManifest.equals(expectedManifest))
      throw new Error("Staged manifest or frontend build inputs are stale");
    return { manifest: JSON.parse(expectedManifest), files: expected };
  }
  const temporary = `${output}.stage-${process.pid}`;
  await rm(temporary, { recursive: true, force: true });
  await mkdir(temporary, { recursive: true });
  try {
    for (const name of runtime) {
      const target = path.join(temporary, name);
      await mkdir(path.dirname(target), { recursive: true });
      await cp(path.join(dist, name), target, { errorOnExist: true });
    }
    await writeFile(
      path.join(temporary, "build-manifest.json"),
      expectedManifest,
      { flag: "wx" },
    );
    await rm(output, { recursive: true, force: true });
    await mkdir(path.dirname(output), { recursive: true });
    await cp(temporary, output, { recursive: true, errorOnExist: true });
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
  return {
    manifest: JSON.parse(expectedManifest),
    files: [...runtime, "build-manifest.json"].sort(),
  };
}

function parseArgs(args) {
  let check = false;
  let output;
  for (let index = 0; index < args.length; ++index) {
    if (args[index] === "--check") check = true;
    else if (args[index] === "--output" && args[index + 1])
      output = args[++index];
    else
      throw new Error(
        `Usage: node backend/frontend/scripts/stage.mjs [--check] [--output PATH]`,
      );
  }
  return { check, output };
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const repoRoot = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../../..",
  );
  const options = parseArgs(process.argv.slice(2));
  const output = options.output
    ? path.resolve(process.cwd(), options.output)
    : path.join(repoRoot, "backend/badminton/static");
  try {
    const result = await stage({ repoRoot, output, check: options.check });
    process.stdout.write(
      `${options.check ? "verified" : "staged"} ${result.files.length} files at ${slash(path.relative(repoRoot, output))}\n`,
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
    process.exitCode = 1;
  }
}
