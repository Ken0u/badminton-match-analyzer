"""Bounded private revision accounting; no media, model or native-pair inference."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import sqlite3
import sys
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from badminton.shuttle_label_comparison import (
    ELIGIBILITY,
    PROTOCOL,
    compare_inventory,
    encoded,
    publish_report,
)
from badminton.shuttle_supervision import census_archive, file_hash

MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "data/manifests/shuttle_label_revision_sources_v1.json"
)
UPSTREAM = "https://api.github.com/repos/qaz812345/TrackNetV3"
RAW = "https://raw.githubusercontent.com/qaz812345/TrackNetV3/"
MAX_RESPONSE = 4 * 1024**2
MAX_NETWORK = 8 * 1024**2
MAX_REQUESTS = 48
MAX_COPIES = 8 * 1024**2


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_object(raw, kind="blob"):
    return hashlib.sha1(f"{kind} {len(raw)}\0".encode() + raw).hexdigest()


def save(path, value):
    publish_report(path, value)


def save_bytes(path, raw):
    """Reuse the comparator's no-replacement publication for arbitrary bytes."""
    # Private inputs are bounded before this call. Hard linking a flushed temporary
    # file prevents an interrupted write from publishing a partial final input.
    import tempfile

    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        pending = Path(stream.name)
        try:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            stream.close()
            pending.unlink()
            raise
    try:
        os.link(pending, path)
    finally:
        pending.unlink()


def local_path(root, path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise ValueError("Linked input/output path")
    path = path.resolve()
    if not path.is_relative_to(root.resolve() / ".cache"):
        raise ValueError("Research files must remain under the original root .cache")
    return path


def pinned(path, sha, size=None):
    before = path.stat()
    if not path.is_file() or (size is not None and before.st_size != size):
        raise ValueError("Missing or wrong-size original input")
    result = file_hash(path)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("Input changed during hashing")
    if result != sha:
        raise ValueError("Pinned input hash mismatch")
    return {"bytes": after.st_size, "sha256": result}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirects are outside the frozen acquisition protocol")


class Network:
    """Anonymous exact allowlist, no retry/cookies/auth, durable request attempts."""

    def __init__(self, output, urls, opener=None):
        self.output = Path(output)
        self.urls = set(urls)
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect()
        )
        self.requests = 0
        self.bytes = 0
        for path in sorted(self.output.glob("request-*.json")):
            entry = json.loads(path.read_bytes())
            self.requests += 1
            response = self.output / entry["response"]
            if not response.is_file():
                raise ValueError("An earlier request is incomplete; no implicit retry")
            self.bytes += response.stat().st_size

    def fetch(self, url):
        if url not in self.urls or not url.startswith("https://"):
            raise ValueError("URL outside exact frozen allowlist")
        key = digest(url.encode())
        attempt = self.output / f"request-{key}.json"
        if (
            attempt.exists()
            or self.requests >= MAX_REQUESTS
            or self.bytes >= MAX_NETWORK
        ):
            raise ValueError("Request replay or acquisition budget exhausted")
        response = self.output / f"response-{key}.bin"
        save(attempt, {"url": url, "response": response.name})
        self.requests += 1
        request = urllib.request.Request(
            url, headers={"User-Agent": "badminton-label-revision-research"}
        )
        bound = min(MAX_RESPONSE, MAX_NETWORK - self.bytes)
        with self.opener.open(request, timeout=45) as stream:
            if stream.geturl() != url or stream.status != 200:
                raise ValueError("Unexpected response origin or status")
            # Reserve one sentinel byte inside the total budget; oversized inputs
            # are retained privately and rejected before parsing.
            raw = stream.read(bound)
        self.bytes += len(raw)
        save_bytes(response, raw)
        if len(raw) >= bound:
            raise ValueError("Response/aggregate acquisition bound reached")
        return raw


def validate_manifest(spec):
    if spec["schema_version"] != 1 or spec["task"] != 220:
        raise ValueError("Unsupported source manifest")
    objects = spec["corrected_objects"]
    canonical = (
        json.dumps(objects, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    if digest(canonical) != spec["corrected_inventory_sha256"]:
        raise ValueError("Changed corrected object inventory")
    paths = [item["path"] for item in objects]
    if (
        len(paths) != 29
        or len(set(paths)) != 29
        or sum(o["bytes"] for o in objects) != 165307
    ):
        raise ValueError("Changed corrected object denominator")
    for item in objects:
        if (
            not re.fullmatch(
                r"match[123]/corrected_csv/[0-9]+_[0-9]+_[0-9]+_ball\.csv", item["path"]
            )
            or not re.fullmatch("[a-f0-9]{40}", item["git_blob_sha"])
            or type(item["bytes"]) is not int
            or not 0 < item["bytes"] < MAX_RESPONSE
        ):
            raise ValueError("Invalid pinned corrected object")
    if (
        spec["original_basis"] is not None
        or spec["revised_basis"] is not None
        or spec["alias_mapping"] is not False
        or any(spec["eligibility"][key] is not False for key in ELIGIBILITY)
        or spec["limits"]
        != {
            "requests": MAX_REQUESTS,
            "response_bytes": MAX_RESPONSE,
            "network_bytes": MAX_NETWORK,
            "label_copy_bytes": MAX_COPIES,
        }
    ):
        raise ValueError("Scientific policy differs from frozen null-basis protocol")
    up = spec["upstream"]
    if up != {
        "repository": "qaz812345/TrackNetV3",
        "commit": "6eda442ada1740573f200f836d93edc9a541ee86",
        "tree": "a428b46df8d4839dd3e20a4bbf6275efb36395c4",
        "prefix": "corrected_test_label/",
        "correction_code": "correct_label.py",
        "drop_inventory": "drop_frame.json",
    }:
        raise ValueError("Changed upstream source identity")
    return spec


def literal_inventory(members, objects):
    originals = {}
    for member in members:
        if member["kind"] == "labels" and member.get("namespace") == "test":
            key = f"{member['match']}/{member['rally']}"
            if key in originals:
                raise ValueError("Duplicate original literal identifier")
            originals[key] = member
    revised = {
        o["path"].replace("/corrected_csv/", "/").removesuffix("_ball.csv"): o
        for o in objects
    }
    return [
        {
            "case_id": key.replace("/", "."),
            "original_member": originals.get(key),
            "revised_object": revised.get(key),
        }
        for key in sorted(originals.keys() | revised.keys())
    ]


def verify_tree(response, expected):
    """Reconstruct every Git tree; do not trust only the API's claimed root SHA."""
    if response.get("truncated") is not False or response.get("sha") != expected:
        raise ValueError("Truncated or mismatched upstream tree")
    entries = response["tree"]
    lookup = {item["path"]: item for item in entries}
    if len(lookup) != len(entries):
        raise ValueError("Duplicate upstream tree path")
    for path in lookup:
        parent = str(PurePosixPath(path).parent)
        if parent != "." and (parent not in lookup or lookup[parent]["type"] != "tree"):
            raise ValueError("Unbound upstream tree descendant")
    trees = {
        "": expected,
        **{p: i["sha"] for p, i in lookup.items() if i["type"] == "tree"},
    }
    for parent, sha in trees.items():
        children = [
            i
            for p, i in lookup.items()
            if (
                ""
                if str(PurePosixPath(p).parent) == "."
                else str(PurePosixPath(p).parent)
            )
            == parent
        ]
        children.sort(
            key=lambda i: (
                PurePosixPath(i["path"]).name + ("/" if i["type"] == "tree" else "")
            ).encode()
        )
        raw = b"".join(
            (i["mode"].lstrip("0") + " " + PurePosixPath(i["path"]).name).encode()
            + b"\0"
            + bytes.fromhex(i["sha"])
            for i in children
        )
        if git_object(raw, "tree") != sha:
            raise ValueError("Upstream tree content does not match immutable identity")
    return lookup


def original_preflight(root, paths, spec):
    """No media members, mutable normalized label caches or process signalling."""
    expected = {
        "archive": spec["archive"]["sha256"],
        "declaration": spec["declaration_sha256"],
        "prior_report": spec["prior_report_sha256"],
        "terminal": spec["original_terminal_sha256"],
        "evidence_index": spec["prior_evidence_index_sha256"],
    }
    seals = {
        name: pinned(
            paths[name], sha, spec["archive"]["bytes"] if name == "archive" else None
        )
        for name, sha in expected.items()
    }
    evidence = json.loads(paths["evidence_index"].read_bytes())
    proofs = []
    import psutil

    database = root / "data/processed/catalog.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        active = [
            json.loads(row[0])
            for row in connection.execute("SELECT document FROM jobs")
        ]
        if any(job["status"] in {"queued", "running"} for job in active):
            raise ValueError(
                "Existing shared work requires its owning task; no auto-recovery"
            )
        for job in evidence["jobs"]:
            process = job["process"]
            try:
                owner = psutil.Process(process["pid"])
                if abs(owner.create_time() - process["creation_time"]) < 0.01:
                    raise ValueError("Original source job lifetime is still present")
            except psutil.NoSuchProcess:
                pass
            for name in ("admission", "terminal"):
                entry = job[name]
                pinned(local_path(root, root / entry["path"]), entry["sha256"])
            row = connection.execute(
                "SELECT document FROM jobs WHERE id=?", (job["job_id"],)
            ).fetchone()
            if row is None or digest(row[0].encode()) != job["store_document_sha256"]:
                raise ValueError("Original shared Store record changed/missing")
            current = json.loads(row[0])
            if (
                current["status"] != "completed"
                or current["owner_pid"] != process["pid"]
                or current["owner_started"] != process["creation_time"]
            ):
                raise ValueError("Original job binding is not terminal")
            admission = json.loads((root / job["admission"]["path"]).read_bytes())
            if admission["process"] != process or admission["job_id"] != job["job_id"]:
                raise ValueError("Original process/artifact binding mismatch")
            proofs.append(
                {
                    "job_id": job["job_id"],
                    "original_lifetime_absent": True,
                    "process": process,
                }
            )
    prior = json.loads(paths["prior_report"].read_bytes())
    if prior["archive_sha256"] != seals["archive"]["sha256"] or any(
        prior["eligibility"][k] is not False for k in ELIGIBILITY
    ):
        raise ValueError("Prior aggregate identity or eligibility changed")
    return {
        "seals": seals,
        "process_proofs": proofs,
        "attributed_prior": {
            key: prior[key]
            for key in (
                "native_frames",
                "published_rows_parsed",
                "incomplete_ordinal_csv_files",
                "row_issues",
                "group_counts",
            )
        },
    }


def metadata(output, spec, archive, source_manifest, network):
    """Freeze all literal identifiers before any original/revised CSV is parsed."""
    with zipfile.ZipFile(archive) as bundle:
        members = census_archive(bundle, source_manifest["limits"])
    inventory = literal_inventory(members, spec["corrected_objects"])
    if sum(c["original_member"] is not None for c in inventory) != 29:
        raise ValueError("Original Test inventory changed")
    save(output / "literal-inventory.json", inventory)
    observed = {}
    for name, source in spec["documentation"].items():
        raw = network.fetch(source["url"])
        save_bytes(output / name, raw)
        observed[name] = {
            "sha256": digest(raw),
            "bytes": len(raw),
            "matches_prior": digest(raw) == source["sha256"],
        }
        if name.startswith("tracknetv3-") and not observed[name]["matches_prior"]:
            raise ValueError("Immutable pinned documentation changed")
    up = spec["upstream"]
    commit_raw = network.fetch(f"{UPSTREAM}/git/commits/{up['commit']}")
    commit = json.loads(commit_raw)
    if commit["sha"] != up["commit"] or commit["tree"]["sha"] != up["tree"]:
        raise ValueError("Upstream commit/root binding mismatch")
    tree_raw = network.fetch(f"{UPSTREAM}/git/trees/{up['tree']}?recursive=1")
    lookup = verify_tree(json.loads(tree_raw), up["tree"])
    actual = [
        {
            "path": p.removeprefix(up["prefix"]),
            "git_blob_sha": i["sha"],
            "bytes": i["size"],
        }
        for p, i in sorted(lookup.items())
        if p.startswith(up["prefix"]) and i["type"] == "blob"
    ]
    if actual != spec["corrected_objects"]:
        raise ValueError("Immutable corrected inventory changed")
    for name in (up["correction_code"], up["drop_inventory"]):
        raw = network.fetch(RAW + up["commit"] + "/" + name)
        if git_object(raw) != lookup[name]["sha"]:
            raise ValueError("Correction metadata Git object mismatch")
        save_bytes(output / name, raw)
        observed[name] = {
            "sha256": digest(raw),
            "bytes": len(raw),
            "git_blob_sha": lookup[name]["sha"],
        }
    receipt = {
        "documents": observed,
        "literal_inventory_sha256": file_hash(output / "literal-inventory.json"),
        "commit_response_sha256": digest(commit_raw),
        "tree_response_sha256": digest(tree_raw),
        "requests": network.requests,
        "network_bytes": network.bytes,
        "label_contents_opened": False,
        "eligibility": dict(ELIGIBILITY),
    }
    save(output / "metadata.json", receipt)
    return receipt


def compare(output, spec, archive, network):
    frozen = json.loads((output / "literal-inventory.json").read_bytes())
    labels = output / "labels"
    labels.mkdir(exist_ok=False)
    cases, copied, seals = [], 0, []
    with zipfile.ZipFile(archive) as bundle:
        for case in frozen:
            item = {
                "case_id": case["case_id"],
                "original": None,
                "revised": None,
                "quarantine_reasons": [
                    "native_correspondence_unverified",
                    "inherited_quarantine_not_resolved",
                ],
            }
            for side in ("original", "revised"):
                entry = case[
                    "original_member" if side == "original" else "revised_object"
                ]
                if entry is None:
                    continue
                size = entry["bytes"]
                if size > MAX_RESPONSE or copied + size > MAX_COPIES:
                    raise ValueError("Label copy budget exceeded")
                if side == "original":
                    with bundle.open(entry["path"]) as stream:
                        raw = stream.read(size + 1)
                else:
                    raw = network.fetch(
                        RAW
                        + spec["upstream"]["commit"]
                        + "/"
                        + spec["upstream"]["prefix"]
                        + entry["path"]
                    )
                    if git_object(raw) != entry["git_blob_sha"]:
                        raise ValueError("Corrected Git blob mismatch")
                if len(raw) != size:
                    raise ValueError("Label object byte count mismatch")
                copied += len(raw)
                name = f"{case['case_id']}.{side}.csv"
                save_bytes(labels / name, raw)
                item[side] = {"path": name, "sha256": digest(raw), "basis": None}
                seals.append(
                    {
                        "case_id": case["case_id"],
                        "side": side,
                        "sha256": digest(raw),
                        "bytes": len(raw),
                    }
                )
            cases.append(item)
    inventory = {"schema_version": 1, "cases": cases}
    save(output / "comparison-inventory.json", inventory)
    save(output / "label-seals.json", seals)
    # This immutable inventory is on disk before the existing comparator parses
    # any CSV. No label-informed alias, basis, threshold or case selection occurs.
    result = compare_inventory(output / "comparison-inventory.json", labels)
    result["source_manifest_sha256"] = digest(encoded(spec))
    result["metadata_sha256"] = file_hash(output / "metadata.json")
    result["label_copy_bytes"] = copied
    result["acquisition"] = {"requests": network.requests, "bytes": network.bytes}
    save(output / "comparison.json", result)
    return result["summary"]


def urls(spec):
    up = spec["upstream"]
    return [v["url"] for v in spec["documentation"].values()] + [
        f"{UPSTREAM}/git/commits/{up['commit']}",
        f"{UPSTREAM}/git/trees/{up['tree']}?recursive=1",
        RAW + up["commit"] + "/" + up["correction_code"],
        RAW + up["commit"] + "/" + up["drop_inventory"],
        *[
            RAW + up["commit"] + "/" + up["prefix"] + o["path"]
            for o in spec["corrected_objects"]
        ],
    ]


def run(args):
    root = args.root.resolve()
    os.environ.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
    )
    import psutil
    from badminton.config import DATA, ROOT, WEIGHTS
    from badminton.jobs import run_local_job
    from badminton.storage import Store

    if (ROOT, DATA, WEIGHTS) != (
        root,
        root / "data/processed",
        root / "models/weights",
    ):
        raise ValueError("Configuration was imported before original roots were pinned")
    spec = validate_manifest(json.loads(MANIFEST.read_bytes()))
    output = local_path(root, args.output)
    paths = {
        key: local_path(root, getattr(args, key))
        for key in (
            "archive",
            "declaration",
            "prior_report",
            "terminal",
            "evidence_index",
        )
    }
    proof = original_preflight(root, paths, spec)
    sources = [
        Path(__file__).resolve(),
        MANIFEST,
        *sorted(
            (Path(__file__).resolve().parents[1] / "backend/badminton").glob("*.py")
        ),
    ]
    context = {
        "source_hashes": {p.name: file_hash(p) for p in sources},
        "inputs": proof,
        "protocol_sha256": digest(encoded(PROTOCOL)),
        "python_sha256": file_hash(Path(sys.executable)),
        "python_version": sys.version,
        "spec_hash": spec["spec_hash"],
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("psutil", "pydantic", "av", "numpy")
        },
    }
    if args.stage == "metadata":
        output.mkdir(exist_ok=False)
        save(output / "context.json", context)
    else:
        if json.loads((output / "context.json").read_bytes()) != context:
            raise ValueError("Frozen consumer/runtime/input context changed")
        meta = output / "metadata.json"
        if file_hash(meta) != args.metadata_sha256:
            raise ValueError("Metadata gate hash differs")
        if (
            file_hash(output / "literal-inventory.json")
            != json.loads(meta.read_bytes())["literal_inventory_sha256"]
        ):
            raise ValueError("Frozen literal inventory changed")
        for name, seal in json.loads(meta.read_bytes())["documents"].items():
            pinned(output / name, seal["sha256"], seal["bytes"])
        save(
            output / "usage-inspection.json",
            {
                "metadata_sha256": args.metadata_sha256,
                "decision": "bounded_private_comparison_only",
                "basis": None,
                "eligibility": dict(ELIGIBILITY),
                "limitations": "Caller inspected original and refreshed documents; no incompatible restriction observed. Unknown rights remain unknown; this is not rights-holder permission.",
            },
        )
    process = psutil.Process()
    stage = args.stage
    identifier = None

    def task(job_id, progress):
        nonlocal identifier
        identifier = job_id
        save(
            output / f"{stage}-admission.json",
            {
                "job_id": job_id,
                "context_sha256": file_hash(output / "context.json"),
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": sys.argv,
                },
            },
        )
        network = Network(output, urls(spec))
        if stage == "metadata":
            result = metadata(
                output,
                spec,
                paths["archive"],
                json.loads(
                    (
                        MANIFEST.parent / "shuttle_supervision_sources_v1.json"
                    ).read_bytes()
                ),
                network,
            )
        else:
            result = compare(output, spec, paths["archive"], network)
        if original_preflight_after(root, paths, spec, proof) is False or any(
            file_hash(p) != context["source_hashes"][p.name] for p in sources
        ):
            raise ValueError("Input or runtime changed during execution")
        progress(1)
        return result

    try:
        result = run_local_job(
            Store(DATA), "research-shuttle-label-revision-" + stage, None, task
        )
    except BaseException:
        if identifier is not None:
            save(
                output / f"{stage}-terminal.json",
                {"job_id": identifier, "status": "failed"},
            )
        raise
    save(
        output / f"{stage}-terminal.json",
        {
            "job_id": identifier,
            "status": "completed",
            "result": result,
            "context_sha256": file_hash(output / "context.json"),
        },
    )
    return {"job_id": identifier, "stage": stage, "status": "completed"}


def original_preflight_after(root, paths, spec, before):
    # The current shared job is intentionally running; repeat immutable-input
    # seals rather than treating our own admission as unrelated stale work.
    return all(
        pinned(paths[name], seal["sha256"], seal["bytes"]) == seal
        for name, seal in before["seals"].items()
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("metadata", "compare"))
    for key in (
        "root",
        "output",
        "archive",
        "declaration",
        "prior-report",
        "terminal",
        "evidence-index",
    ):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--metadata-sha256")
    args = parser.parse_args(argv)
    if args.stage == "compare" and not args.metadata_sha256:
        parser.error("Compare requires --metadata-sha256 after source/usage inspection")
    print(json.dumps(run(args)))


if __name__ == "__main__":
    main()
