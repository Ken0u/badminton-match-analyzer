"""Freeze and run a read-only census of sealed original-host rally evidence.

No image assessment, decoder, model, network transport or process signaling.
The original private evidence and frozen checkouts are required; a clone cannot
substitute generated records for that evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
PROTOCOL = "data/manifests/rally_reference_diagnostics_v1.json"
CONSUMERS = (
    "backend/badminton/rally_reference_diagnostics.py",
    "scripts/diagnose_rally_references.py",
    "tests/test_rally_reference_diagnostics.py",
    PROTOCOL,
)
CREDENTIALS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "AGENT_PROJECT_TOKEN",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
    "CODEX_THREAD_ID",
    "CODEX_SESSION_ID",
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def exclusive(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(
            json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def git(checkout, *args):
    return subprocess.check_output(["git", *args], cwd=checkout, text=True).strip()


def binding():
    if git(CHECKOUT, "status", "--porcelain"):
        raise ValueError("Commit and test consumers before freezing")
    return {
        "commit": git(CHECKOUT, "rev-parse", "HEAD"),
        "files": {name: digest(CHECKOUT / name) for name in CONSUMERS},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psutil": psutil.__version__,
    }


def frozen(root, protocol):
    for row in protocol["frozen_checkouts"]:
        path = root / row["path"]
        if git(path, "rev-parse", "HEAD") != row["commit"] or git(
            path, "status", "--porcelain"
        ):
            raise ValueError("Frozen checkout revision or cleanliness changed")
        if any(digest(path / name) != sha for name, sha in row["files"].items()):
            raise ValueError("Frozen consumer bytes changed")
    recovery_root = root / protocol["frozen_checkouts"][0]["path"]
    recovery = module(
        recovery_root / "scripts/recover_rally_references.py", "diagnostic_archived228"
    )
    old = recovery.frozen(root)
    # Do not let an earlier import silently select the current acceptance code.
    if any(n == "badminton" or n.startswith("badminton.") for n in sys.modules):
        raise ValueError("Use a clean process before loading frozen acceptance")
    library = old.frozen_library(root, acceptance=True)
    acceptance = protocol["frozen_checkouts"][1]
    origin = root / acceptance["path"] / "backend/badminton/rally_source_reference.py"
    if (
        Path(library.__file__).resolve() != origin.resolve()
        or digest(origin)
        != acceptance["files"]["backend/badminton/rally_source_reference.py"]
    ):
        raise ValueError("Actual acceptance module origin/hash changed")
    return recovery, old, library


def metadata_gate(root, recovery, old, library, protocol):
    """Replay original metadata gates only; never invoke the writing audit."""
    for relative, sha in protocol["sealed_inputs"].items():
        if digest(root / relative) != sha:
            raise ValueError("Sealed scientific input changed")
    output = root / ".cache/rally228-source-only-v1"
    context, published = recovery.current(output, output / "timestamp.json", live=False)
    if not (output / "combined-target-index.json").is_file():
        raise ValueError("Complete target index required before scientific labels")
    old.metadata.absent(read(output / "owner.json"))
    plan, prefix, suffix, identities = recovery.archive(root, old, library)
    if (
        prefix != context["prefix"]
        or suffix != context["suffix"]
        or (output / "STOP.json").exists()
    ):
        raise ValueError("Recovery archive or fence changed")
    expected = {f"{old.SINGLES}-{c['index']:03d}" for c in suffix}
    for name in ("start.json", "finish.json", "payload-reservation.json", "entry.json"):
        if {p.parent.name for p in (output / "runs").glob("*/" + name)} != expected:
            raise ValueError("Exact recovery execution inventory required")
    entries = list(prefix)
    ended = None
    for chunk in suffix:
        folder = output / "runs" / f"{old.SINGLES}-{chunk['index']:03d}"
        entry = old.verify_run(
            root,
            library,
            folder,
            chunk,
            identities,
            granted_at=context["granted_at"],
            frozen_at=published,
            deadline=context["deadline"],
        )
        if entry != read(folder / "entry.json"):
            raise ValueError("Recovery indexed entry changed")
        start, finish = read(folder / "start.json"), read(folder / "finish.json")
        if ended is not None and start["started_at"] < ended + 5:
            raise ValueError("Original sequential pacing violated")
        ended = finish["ended_at"]
        entries.append(entry)
    chunks = old.source_chunks(plan)
    by_key = {(e["source_id"], e["chunk"]): e for e in entries}
    entries = [by_key[(c["source_id"], c["index"])] for c in chunks]
    if old.metadata.complete_index(chunks, entries) != read(
        output / "combined-target-index.json"
    ):
        raise ValueError("Complete combined index changed")
    total = old.metadata.payload_total(
        recovery.PRIOR_BYTES, (output / "runs").glob("*/payload-reservation.json")
    )
    recovery.rules.global_gate(
        chunks,
        entries,
        completed_threads=len(identities.threads),
        expected_threads=1014,
        total=total,
        projected=context["projected_image_bytes"],
    )
    if total != protocol["prior_attempted_image_bytes"] or len(entries) != 256:
        raise ValueError("Original global provenance denominator changed")
    return (
        plan,
        entries,
        {
            "completed_global_execution_identities": len(identities.threads),
            "validated_target_references": len(entries),
            "prior_attempted_image_bytes": total,
            "prior_retained_output_bytes": recovery.retained(root, old),
            "scientific_labels_read": False,
        },
    )


def load_streams(root, old, library, source, entries):
    """A separate reader; unchanged acceptance is called without monkeypatches."""
    paths = old.paths(root)
    packet = read(paths["native"] / f"{source['source_id']}.packet.json")
    protocol = library.load_protocol(
        paths["acceptance"] / "data/manifests/rally_reference_protocol_v4.json"
    )
    streams, provenance = {}, {}
    for lane in library.STREAMS:
        if lane == "adjudication":
            selected = {(e["source_id"], e["chunk"]): e for e in entries}
            assigned = [
                (chunk, selected[(source["source_id"], chunk["index"])])
                for chunk in source["chunks"]
            ]
        else:
            original = read(paths["base"] / "dense-assessment-v1" / lane / "index.json")
            selected = [
                e for e in original["segments"] if e["source_id"] == source["source_id"]
            ]
            chunks = library.plan_chunks(packet, dense=True, protocol=protocol)
            if len(selected) != len(chunks):
                raise ValueError("Original exhaustive chunk denominator changed")
            assigned = list(zip(chunks, selected, strict=True))
        streams[lane], provenance[lane] = [], []
        previous = region = None
        for chunk, entry in assigned:
            if lane == "adjudication" and chunk["region_index"] != region:
                previous = None
            document, receipt = (
                read(entry["original_path"]),
                read(entry["receipt_path"]),
            )
            if (
                digest(entry["original_path"]) != entry["original_sha256"]
                or digest(entry["receipt_path"]) != entry["receipt_sha256"]
            ):
                raise ValueError("Validated input changed before scientific read")
            library.validate_assessment(
                document,
                packet,
                chunk,
                receipt,
                stage="dense",
                stream=lane,
                previous=previous,
                protocol=protocol,
            )
            streams[lane].append((document, receipt))
            provenance[lane].append(
                {
                    k: entry[k]
                    for k in (
                        "original_path",
                        "original_sha256",
                        "receipt_path",
                        "receipt_sha256",
                    )
                }
            )
            previous = {
                "sha256": receipt["segment_sha256"],
                "stream": lane,
                "source_id": source["source_id"],
                "stage": "dense",
                "last_frames": chunk["frames"][-2:],
            }
            region = chunk.get("region_index")
    return packet, streams, provenance


def new_bytes(root):
    """Task-specific outputs only; never enumerate unrelated studies/holdouts."""
    parents = [
        p
        for p in (root / ".cache").iterdir()
        if p.name.startswith(("rally238", "rally-diagnostics"))
    ]
    parents.extend(
        p
        for p in (root / ".cache/worktrees").iterdir()
        if p.name.startswith("rally238")
    )
    total = 0
    for parent in parents:
        info = parent.lstat()
        if parent.is_symlink() or getattr(info, "st_file_attributes", 0) & 1024:
            raise ValueError("Task output roots must not traverse links")
        if parent.is_file():
            total += info.st_size
            continue
        for folder, directories, files in os.walk(parent, followlinks=False):
            for name in list(directories):
                node = Path(folder) / name
                info = node.lstat()
                if (
                    stat.S_ISLNK(info.st_mode)
                    or getattr(info, "st_file_attributes", 0) & 1024
                ):
                    total += info.st_size
                    directories.remove(name)
            # Count link metadata, never target bytes; pytest's "current"
            # directory links must not be followed or double-counted.
            total += sum((Path(folder) / name).lstat().st_size for name in files)
    return total


def require_budget(root, protocol, *, prior=0):
    value = new_bytes(root)
    if (
        value > protocol["limits"]["new_output_bytes"] - 1024**2
        or value + prior > protocol["limits"]["cumulative_retained_bytes"] - 1024**2
    ):
        raise ValueError("Diagnostic output budget exhausted")
    return value


def freeze(root, output, grant, protocol):
    claim = grant["task"]["claim"]
    now = time.time()
    if (
        platform.node() != "MSI"
        or grant["task"]["status"] != "running"
        or claim["actor"] != "Ken0u"
        or claim["host_id"] != "MSI"
        or claim["spec_hash"] != protocol["spec_hash"]
        or claim["epoch"] != grant["task"]["epoch"]
        or not claim["granted_at"] <= now < claim["expires_at"]
    ):
        raise ValueError("Current original-host committed grant required")
    context = {
        "task": 238,
        "consumers": binding(),
        "grant": grant,
        "frozen_at": now,
        "deadline": claim["granted_at"] + 4 * 3600,
        "scientific_labels_read": False,
        "new_image_payload_bytes": 0,
    }
    if now >= context["deadline"]:
        raise ValueError("Fresh metadata runtime expired")
    require_budget(root, protocol)
    output.mkdir(exist_ok=False)
    exclusive(output / "context.json", context)
    return {
        "context_sha256": digest(output / "context.json"),
        "deadline": context["deadline"],
        "scientific_labels_read": False,
    }


def current(output, stamp):
    context = read(output / "context.json")
    timestamp = read(stamp)
    published = datetime.fromisoformat(
        timestamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    if (
        context["consumers"] != binding()
        or timestamp["user"]["login"] != "Ken0u"
        or not timestamp["html_url"].startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/238#issuecomment-"
        )
        or digest(output / "context.json") not in timestamp["body"]
        or not context["frozen_at"] <= published <= time.time() < context["deadline"]
    ):
        raise ValueError("Prospective issue seal or consumer/runtime binding changed")
    return context


def admitted_run(root, output, context, calculate):
    from badminton import config
    from badminton.jobs import run_local_job
    from badminton.storage import Store

    if (
        config.ROOT != root
        or config.DATA.resolve() != root / "data/processed"
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (config.DATA / "catalog.sqlite3").is_file()
    ):
        raise ValueError("Pin original roots and real existing Store before imports")
    if any(os.environ.get(k) for k in CREDENTIALS):
        raise ValueError("Clear account credentials before diagnostic execution")
    if any(
        (output / n).exists()
        for n in (
            "admission.json",
            "aggregate.json",
            "ledger.json",
            "terminal.json",
            "failure.json",
        )
    ):
        raise ValueError("Diagnostic execution already attempted; preserve outputs")
    process, job_id = psutil.Process(), None
    result = None

    def task(identifier, progress):
        nonlocal job_id, result
        job_id = identifier
        exclusive(
            output / "admission.json",
            {
                "job_id": identifier,
                "context_sha256": digest(output / "context.json"),
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": process.cmdline(),
                },
            },
        )
        if time.time() >= context["deadline"]:
            raise ValueError("Diagnostic metadata runtime expired")
        result = calculate(progress)
        if time.time() >= context["deadline"]:
            raise ValueError("Diagnostic metadata runtime expired")
        return result

    try:
        run_local_job(
            Store(config.DATA), "rally_reference_diagnostics", "sealed-rally238", task
        )
    except BaseException as error:
        exclusive(
            output / "failure.json",
            {
                "job_id": job_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "scientific_acceptance_changed": False,
            },
        )
        raise
    exclusive(
        output / "terminal.json",
        {
            "job_id": job_id,
            "status": "completed",
            "admission_sha256": digest(output / "admission.json"),
            "artifacts": {
                n: digest(output / n) for n in ("aggregate.json", "ledger.json")
            },
            "summary": result,
        },
    )
    return result


def execute(root, output, stamp, protocol):
    context = current(output, stamp)
    recovery, old, library = frozen(root, protocol)
    diagnostics = module(CHECKOUT / CONSUMERS[0], "diagnostic_census")

    def calculate(progress):
        plan, entries, audit = metadata_gate(root, recovery, old, library, protocol)
        prior = audit["prior_retained_output_bytes"]
        require_budget(root, protocol, prior=prior)
        exclusive(output / "metadata-gate.json", audit)
        results, ledgers = [], {}
        for index, source in enumerate(plan["sources"]):
            if time.time() >= context["deadline"]:
                raise ValueError("Diagnostic metadata runtime expired")
            packet, streams, provenance = load_streams(
                root, old, library, source, entries
            )
            result, ledger = diagnostics.diagnose_source(
                streams,
                native_frames=[r["frame"] for r in packet["frames"]],
                bounds=source["bounds"],
                acceptance=library.targeted_reference_status,
            )
            results.append(result)
            ledgers[source["source_id"]] = {"provenance": provenance, "streams": ledger}
            progress((index + 1) / len(plan["sources"]))
        original = read(root / ".cache/rally228-source-only-v1/aggregate.json")
        diagnostics.require_unchanged(results, original)
        if time.time() >= context["deadline"]:
            raise ValueError("Diagnostic metadata runtime expired")
        for relative, sha in protocol["sealed_inputs"].items():
            if digest(root / relative) != sha:
                raise ValueError("Sealed input changed during census")
        require_budget(root, protocol, prior=prior)
        exclusive(output / "ledger.json", ledgers)
        require_budget(root, protocol, prior=prior)
        aggregate = {
            "task": 238,
            "source_slots": len(results),
            "native_frames": sum(r["native_frames"] for r in results),
            "complete_references": original["complete_references"],
            "all_requested_labels_supported_slots": original[
                "all_requested_labels_supported_slots"
            ],
            "eligibility": original["eligibility"],
            "unchanged_frozen_scientific_acceptance": True,
            "new_image_payload_bytes": 0,
            "new_scientific_sessions": 0,
            "source_only_development_not_expert_gold": True,
            "full_match_accuracy_established": False,
            "results": results,
            "ledger_sha256": digest(output / "ledger.json"),
            "metadata_gate_sha256": digest(output / "metadata-gate.json"),
            "context_sha256": digest(output / "context.json"),
            "sealed_inputs": protocol["sealed_inputs"],
            "protocol_sha256": digest(CHECKOUT / PROTOCOL),
        }
        exclusive(output / "aggregate.json", aggregate)
        return {
            "source_slots": len(results),
            "native_frames": aggregate["native_frames"],
            "complete_references": aggregate["complete_references"],
            "aggregate_sha256": digest(output / "aggregate.json"),
            "full_match_accuracy_established": False,
        }

    return admitted_run(root, output, context, calculate)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--grant", type=Path)
    parser.add_argument("--timestamp", type=Path)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(strict=True), args.output.resolve()
    if output.parent != root / ".cache" or not output.name.startswith("rally238-"):
        parser.error(
            "Use an exclusive rally238-* output directly in the original cache"
        )
    for name in CREDENTIALS:
        os.environ.pop(name, None)
    os.environ.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    protocol = read(CHECKOUT / PROTOCOL)
    try:
        result = (
            freeze(root, output, read(args.grant), protocol)
            if args.phase == "freeze"
            else execute(root, output, args.timestamp, protocol)
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "scientific_acceptance_changed": False,
                }
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
