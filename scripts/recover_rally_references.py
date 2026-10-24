"""Explicit recovery of a sealed source-assessment suffix on its original host.

Old failed outputs and dispatch fences remain immutable. The unchanged frozen
scientific consumer is called only after complete global metadata verification.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

sys.dont_write_bytecode = True
CHECKOUT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "recovery_metadata", CHECKOUT / "backend/badminton/rally_reference_recovery.py"
)
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)
FILES = (
    "backend/badminton/rally_reference_recovery.py",
    "scripts/recover_rally_references.py",
    "data/manifests/rally_reference_protocol_v6.json",
)
PRIOR_BYTES = 7991688001
INHERITED_DEADLINE = 1792860317
FROZEN_COMMIT = "5014296edb6b87282036b79d824fb0954470141f"
FROZEN_FILES = {
    "backend/badminton/rally_reference_continuation.py": "0ba0b282230c19323e8987ff8e71596f6435448151d42941ab78b04af9b6474f",
    "scripts/continue_rally_references.py": "974f2796f2d109398cc247dccca578d0e1376647ac6185a6311403c2ba2443d4",
    "data/manifests/rally_reference_protocol_v5.json": "715d85e1653a6ce6d529155669506c31db850cfee6757ff662c940ce80d8f75d",
}
CONTEXT_SHA = "795b230a8b6836742c9b776edb5ac30de47307c94e4960213c07ed1f4d4c63a6"
INTEGRITY_SHA = "0defa2acb1e267fcf346ff38441178a4e0495156a28688e81fd13df6c5681c7e"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(part)
    return result.hexdigest()


def read(path):
    return json.loads(Path(path).read_bytes())


def frozen(root):
    checkout = root / ".cache/worktrees/rally226-producer-v1"
    if (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
        ).strip()
        != FROZEN_COMMIT
        or subprocess.check_output(["git", "status", "--porcelain"], cwd=checkout)
        or any(digest(checkout / name) != sha for name, sha in FROZEN_FILES.items())
    ):
        raise ValueError("Frozen archived consumer changed")
    spec = importlib.util.spec_from_file_location(
        "archived226", checkout / "scripts/continue_rally_references.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def binding():
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=CHECKOUT):
        raise ValueError("Commit recovery consumers before freezing")
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True
        ).strip(),
        "files": {name: digest(CHECKOUT / name) for name in FILES},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psutil": psutil.__version__,
    }


def archive(root, old, library):
    """Reverify sources and opaque execution, including the excluded failure."""
    output = root / ".cache/rally226-source-only-v1"
    integrity = root / ".cache/rally226-final-integrity-v1.json"
    if (
        rules.opaque_inventory(output)
        != read(CHECKOUT / FILES[-1])["archived226_inventory"]
    ):
        raise ValueError("Archived attempt bytes or inventory changed")
    if (
        digest(output / "context.json") != CONTEXT_SHA
        or digest(integrity) != INTEGRITY_SHA
    ):
        raise ValueError("Archived preservation seal changed")
    context, published = old.verify_current(
        output, output / "timestamp.json", live=False
    )
    if context["deadline"] != INHERITED_DEADLINE:
        raise ValueError("Inherited deadline changed")
    old.metadata.absent(read(output / "owner.json"))
    if read(output / "STOP.json")["reason"] != "source_assessment_validation_failed":
        raise ValueError("Archived failure fence changed")
    if (output / "combined-target-index.json").exists():
        raise ValueError("Archived missing index was filled")
    plan, prefix, identities = old.predecessor(root, library)
    if prefix != context["prefix"]:
        raise ValueError("Archived original prefix changed")
    expected = {f"{old.SINGLES}-{n:03d}" for n in range(94, 152)}
    if {p.name for p in (output / "runs").iterdir() if p.is_dir()} != expected:
        raise ValueError("Archived attempt inventory changed")
    newer = []
    for chunk in context["suffix"][:58]:
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
        if chunk["index"] < 151:
            if entry != read(folder / "entry.json"):
                raise ValueError("Archived validated reference changed")
            newer.append(entry)
        elif (folder / "entry.json").exists():
            raise ValueError("Archived failed reference was promoted")
    rules.archived_suffix(context["suffix"], newer, first=94, failed=151)
    if (
        len(identities.threads) != 993
        or old.metadata.payload_total(
            old.PRIOR_BYTES, (output / "runs").glob("*/payload-reservation.json")
        )
        != PRIOR_BYTES
    ):
        raise ValueError("Archived global inventory changed")
    combined = {(e["source_id"], e["chunk"]): e for e in [*prefix, *newer]}
    chunks = old.source_chunks(plan)
    prefix = [
        combined[(c["source_id"], c["index"])]
        for c in chunks
        if (c["source_id"], c["index"]) in combined
    ]
    suffix = [c for c in chunks if (c["source_id"], c["index"]) not in combined]
    rules.partition(chunks, prefix, suffix)
    if len(prefix) != 235 or len(suffix) != 21 or suffix[0]["index"] != 151:
        raise ValueError("Recovery scope differs from frozen planning")
    return plan, prefix, suffix, identities


def retained(root, old):
    """Count the old ledger plus all new task helpers and worktrees, once."""
    import stat

    total = old.retained_bytes(root)
    parents = [
        p
        for p in (root / ".cache").iterdir()
        if p.name.lower().startswith(
            ("rally228", "rally-recovery", "prepare-rally-recovery")
        )
    ]
    parents.extend(
        p
        for p in (root / ".cache/worktrees").iterdir()
        if p.name.lower().startswith("rally228")
    )
    for parent in parents:
        if parent.is_symlink():
            raise ValueError("Recovery output root must not be a symlink")
        if parent.is_file():
            total += parent.stat().st_size
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
            total += sum((Path(folder) / name).lstat().st_size for name in files)
    if total > old.metadata.MAX_BYTES:
        raise ValueError("Cumulative retained outputs exceed their bound")
    return total


def freeze(root, output, granted_at, old, library):
    end = rules.deadline(granted_at, INHERITED_DEADLINE, now=time.time())
    consumers = binding()
    protocol = read(CHECKOUT / FILES[-1])
    if (
        protocol["frozen226_commit"] != FROZEN_COMMIT
        or protocol["frozen226_files"] != FROZEN_FILES
        or protocol["inherited_deadline"] != INHERITED_DEADLINE
        or protocol["prior_attempted_image_bytes"] != PRIOR_BYTES
    ):
        raise ValueError("Public recovery protocol differs from execution")
    _plan, prefix, suffix, _identities = archive(root, old, library)
    projected = rules.recovery_cost(PRIOR_BYTES, suffix)
    if projected != 8177560145:
        raise ValueError("Prospective recovery cost changed")
    old_context = read(root / ".cache/rally226-source-only-v1/context.json")
    if digest(old_context["cli"]["path"]) != old_context["cli"]["sha256"]:
        raise ValueError("Original CLI executable changed")
    output.mkdir(exist_ok=False)
    (output / "runs").mkdir()
    old.metadata.exclusive_json(output / "runs/schema.json", old.SCHEMA)
    context = {
        "task": 228,
        "granted_at": granted_at,
        "deadline": end,
        "inherited_deadline": INHERITED_DEADLINE,
        "frozen_at": time.time(),
        "consumers": consumers,
        "prefix": prefix,
        "suffix": suffix,
        "prior_image_bytes": PRIOR_BYTES,
        "projected_image_bytes": projected,
        "retained_output_bytes": retained(root, old),
        "cli": old_context["cli"],
        "replacement_chunk": 151,
        "scientific_labels_read": False,
        "images_dispatched": 0,
    }
    old.metadata.exclusive_json(output / "context.json", context)
    return {
        "phase": "frozen",
        "remaining_sessions": 21,
        "context_sha256": digest(output / "context.json"),
        "projected_image_bytes": projected,
    }


def current(output, timestamp, *, live):
    context = read(output / "context.json")
    if (
        context["consumers"] != binding()
        or context["inherited_deadline"] != INHERITED_DEADLINE
        or context["deadline"] != min(context["granted_at"] + 28800, INHERITED_DEADLINE)
    ):
        raise ValueError("Frozen recovery consumers or interval changed")
    if live:
        rules.deadline(context["granted_at"], INHERITED_DEADLINE, now=time.time())
    stamp = read(timestamp)
    published = datetime.fromisoformat(
        stamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    if (
        stamp["user"]["login"] != "Ken0u"
        or "/issues/228#issuecomment-" not in stamp["html_url"]
        or digest(output / "context.json") not in stamp["body"]
        or not context["frozen_at"] <= published <= time.time()
        or digest(context["cli"]["path"]) != context["cli"]["sha256"]
    ):
        raise ValueError("Prospective recovery timestamp or CLI binding changed")
    return context, published


def run(root, output, timestamp, old, library):
    context, published = current(output, timestamp, live=True)
    plan, prefix, suffix, _identities = archive(root, old, library)
    if prefix != context["prefix"] or suffix != context["suffix"]:
        raise ValueError("Immutable recovery plan changed")
    if (output / "STOP.json").exists() or list(
        (output / "runs").glob("*/payload-reservation.json")
    ):
        raise ValueError("Recovery already attempted or fenced")
    old.metadata.exclusive_json(output / "owner.json", old.owner())
    p = old.paths(root)
    packet = read(p["native"] / f"{old.SINGLES}.packet.json")
    rows = {row["frame"]: row for row in packet["frames"]}
    protocol = library.load_protocol(
        p["producer"] / "data/manifests/rally_reference_protocol_v4.json"
    )
    schema = output / "runs/schema.json"
    if read(schema) != old.SCHEMA:
        raise ValueError("Original scientific schema changed")
    earlier = next(
        e for e in prefix if e["source_id"] == old.SINGLES and e["chunk"] == 150
    )
    receipt = read(earlier["receipt_path"])
    document = read(earlier["original_path"])
    if (
        hashlib.sha256(library.encoded(document)).hexdigest()
        != receipt["segment_sha256"]
    ):
        raise ValueError("Validated same-stream continuity changed")
    previous = {
        "sha256": receipt["segment_sha256"],
        "stream": "adjudication",
        "source_id": old.SINGLES,
        "stage": "dense",
        "last_frames": earlier["frames"][-2:],
    }
    own_notes = document["continuity_notes"]
    source = next(s for s in plan["sources"] if s["source_id"] == old.SINGLES)
    region = source["chunks"][150]["region_index"]
    entries = []
    for chunk in suffix:
        current(output, timestamp, live=True)
        if retained(root, old) >= old.metadata.MAX_BYTES - 64 * 1024**2:
            raise ValueError("Insufficient retained-output headroom")
        if chunk["region_index"] != region:
            previous = None
            own_notes = (
                "A disconnected source region begins; do not assert unseen continuity. Your own earlier notes only: "
                + own_notes
            )
        region = chunk["region_index"]
        folder = output / "runs" / f"{old.SINGLES}-{chunk['index']:03d}"
        folder.mkdir(exist_ok=False)
        assigned = [
            {
                key: rows[n][key]
                for key in (
                    "frame",
                    "pts",
                    "time_base",
                    "time_s",
                    "rotation",
                    "display_size",
                )
            }
            | {"sha256": rows[n]["image"]["sha256"]}
            for n in chunk["frames"]
        ]
        images = [p["native"] / rows[n]["image"]["path"] for n in chunk["frames"]]
        if (
            len(images) > 20
            or sum(image.stat().st_size for image in images) != chunk["image_bytes"]
        ):
            raise ValueError("Original native image cost changed")
        if any(
            digest(image) != rows[n]["image"]["sha256"]
            for n, image in zip(chunk["frames"], images)
        ):
            raise ValueError("Original native PNG changed")
        session = f"codex-cli:request=recovery228:adjudication:{old.SINGLES}:{chunk['index']}:{time.time_ns()}"
        prompt = old.assessment_prompt(
            session=session,
            sid=old.SINGLES,
            previous=previous,
            own_notes=own_notes,
            assigned=assigned,
        )
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
        cost = library.transport_cost(
            [image.stat().st_size for image in images],
            context_bytes=len(
                json.dumps(
                    {"prompt": prompt, "schema": old.SCHEMA}, ensure_ascii=True
                ).encode("utf-8")
            ),
            protocol=protocol,
        )
        if cost["base64_image_bytes"] != chunk["base64_bytes"]:
            raise ValueError("Frozen encoded image cost changed")
        reservation = {
            "run_name": folder.name,
            "lane": "adjudication",
            "source_id": old.SINGLES,
            "chunk": chunk["index"],
            "image_bytes": chunk["image_bytes"],
            "images": [
                {"frame": n, "sha256": rows[n]["image"]["sha256"]}
                for n in chunk["frames"]
            ],
            "reserved_at": time.time(),
        }
        command = [
            context["cli"]["path"],
            "exec",
            "--sandbox",
            "read-only",
            "--json",
            "--ephemeral",
            "--cd",
            str(p["producer"]),
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(folder / "original-final.json"),
        ]
        for image in images:
            command.extend(("--image", str(image)))
        command.append("-")

        def launch():
            rules.deadline(context["granted_at"], INHERITED_DEADLINE, now=time.time())
            return subprocess.Popen(
                command,
                cwd=p["producer"],
                env=os.environ.copy(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )

        total, child = old.metadata.reserve_and_launch(
            output,
            reservation,
            granted_at=context["deadline"] - 28800,
            prior_bytes=PRIOR_BYTES,
            launch=launch,
        )
        try:
            observed = psutil.Process(child.pid)
            start = {
                "pid": child.pid,
                "creation_time": observed.create_time(),
                "cwd": observed.cwd(),
                "command": observed.cmdline(),
                "started_at": time.time(),
                "session_id": session,
                "images": reservation["images"],
                "image_bytes": chunk["image_bytes"],
                "transport_cost": cost,
            }
            old.metadata.exclusive_json(folder / "start.json", start)
        except BaseException:
            old.fence(output, "child_identity_or_start_persistence_failed")
            raise
        finish = {
            **start,
            **old.metadata.collect_output(
                child, prompt, folder, lambda reason: old.fence(output, reason)
            ),
        }
        final = folder / "original-final.json"
        if final.is_file() and final.stat().st_size < old.metadata.MAX_LOG_BYTES:
            finish["original_output_sha256"] = digest(final)
            try:
                document = read(final)
                finish["segment_sha256"] = hashlib.sha256(
                    library.encoded(document)
                ).hexdigest()
                finish["original_resolution_viewing"] = True
            except (ValueError, UnicodeError, RecursionError):
                finish["execution_protocol_failures"].append("malformed_original_final")
        else:
            finish["execution_protocol_failures"].append(
                "missing_or_oversized_original_final"
            )
        old.metadata.exclusive_json(folder / "finish.json", finish)
        if finish["execution_protocol_failures"]:
            old.fence(output, "execution_protocol_failed")
            raise ValueError("Recovery failed; no further replacement permitted")
        old.metadata.absent(start)
        try:
            library.validate_assessment(
                document,
                packet,
                chunk,
                finish,
                stage="dense",
                stream="adjudication",
                previous=previous,
                protocol=protocol,
            )
        except BaseException:
            old.fence(output, "source_assessment_validation_failed")
            raise
        entry = old.verify_run(
            root,
            library,
            folder,
            chunk,
            old.metadata.Identities(),
            granted_at=context["granted_at"],
            frozen_at=published,
            deadline=context["deadline"],
        )
        old.metadata.exclusive_json(folder / "entry.json", entry)
        entries.append(entry)
        previous = {
            "sha256": finish["segment_sha256"],
            "stream": "adjudication",
            "source_id": old.SINGLES,
            "stage": "dense",
            "last_frames": chunk["frames"][-2:],
        }
        own_notes = document["continuity_notes"]
        print(
            json.dumps(
                {
                    "phase": "segment_exited",
                    "chunk": chunk["index"],
                    "completed_new_sessions": len(entries),
                    "cumulative_image_bytes": total,
                }
            ),
            flush=True,
        )
        time.sleep(5)
    by_key = {(e["source_id"], e["chunk"]): e for e in [*prefix, *entries]}
    chunks = old.source_chunks(plan)
    combined = old.metadata.complete_index(
        chunks, [by_key[(c["source_id"], c["index"])] for c in chunks]
    )
    old.metadata.exclusive_json(output / "combined-target-index.json", combined)
    return {
        "phase": "execution_complete",
        "new_sessions": len(entries),
        "scientific_acceptance_performed": False,
    }


def scientific_status(root, old, library, plan, entries):
    """Same frozen validation and acceptance; caller must prove global coverage."""
    p = old.paths(root)
    by_key = {(e["source_id"], e["chunk"]): e for e in entries}
    protocol = library.load_protocol(
        p["acceptance"] / "data/manifests/rally_reference_protocol_v4.json"
    )
    results = []
    for source in plan["sources"]:
        sid = source["source_id"]
        packet = read(p["native"] / f"{sid}.packet.json")
        streams = {}
        for lane in library.STREAMS[:2]:
            original = read(p["base"] / "dense-assessment-v1" / lane / "index.json")
            streams[lane] = [
                (read(e["original_path"]), read(e["receipt_path"]))
                for e in original["segments"]
                if e["source_id"] == sid
            ]
        streams["adjudication"] = []
        previous = region = None
        for chunk in source["chunks"]:
            if chunk["region_index"] != region:
                previous = None
            entry = by_key[(sid, chunk["index"])]
            document, receipt = (
                read(entry["original_path"]),
                read(entry["receipt_path"]),
            )
            library.validate_assessment(
                document,
                packet,
                chunk,
                receipt,
                stage="dense",
                stream="adjudication",
                previous=previous,
                protocol=protocol,
            )
            streams["adjudication"].append((document, receipt))
            previous = {
                "sha256": receipt["segment_sha256"],
                "stream": "adjudication",
                "source_id": sid,
                "stage": "dense",
                "last_frames": chunk["frames"][-2:],
            }
            region = chunk["region_index"]
        status = library.targeted_reference_status(
            streams,
            native_frames=[r["frame"] for r in packet["frames"]],
            bounds=source["bounds"],
        )
        results.append(
            {"source_id": sid, "native_frames": len(packet["frames"]), **status}
        )
    return results


def audit(root, output, timestamp, old, library):
    context, published = current(output, timestamp, live=False)
    if not (output / "combined-target-index.json").exists():
        return {
            "ready": False,
            "reason": "both_complete_target_indexes_required",
            "scientific_labels_read": False,
        }
    old.metadata.absent(read(output / "owner.json"))
    plan, prefix, suffix, identities = archive(root, old, library)
    if (
        prefix != context["prefix"]
        or suffix != context["suffix"]
        or (output / "STOP.json").exists()
    ):
        raise ValueError("Recovery archive changed or execution fenced")
    expected = {f"{old.SINGLES}-{c['index']:03d}" for c in suffix}
    for name in ("start.json", "finish.json", "payload-reservation.json", "entry.json"):
        if {p.parent.name for p in (output / "runs").glob("*/" + name)} != expected:
            raise ValueError("Exact recovery execution inventory required")
    entries = [*prefix]
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
            raise ValueError("Sequential source pacing violated")
        ended = finish["ended_at"]
        entries.append(entry)
    chunks = old.source_chunks(plan)
    by_key = {(e["source_id"], e["chunk"]): e for e in entries}
    entries = [by_key[(c["source_id"], c["index"])] for c in chunks]
    combined = old.metadata.complete_index(chunks, entries)
    if combined != read(output / "combined-target-index.json"):
        raise ValueError("Complete combined index changed")
    total = old.metadata.payload_total(
        PRIOR_BYTES, (output / "runs").glob("*/payload-reservation.json")
    )
    rules.global_gate(
        chunks,
        entries,
        completed_threads=len(identities.threads),
        expected_threads=1014,
        total=total,
        projected=context["projected_image_bytes"],
    )
    retained_bytes = retained(root, old)
    # No targeted final scientific labels are read until every gate above passes.
    results = scientific_status(root, old, library, plan, entries)
    result = {
        "task": 228,
        "source_slots": 2,
        "native_frames": 1532,
        "complete_references": sum(row["complete_reference"] for row in results),
        "all_requested_labels_supported_slots": sum(
            row["all_requested_labels_supported"] for row in results
        ),
        "results": results,
        "genuine_completed_threads": len(identities.threads),
        "attempted_image_bytes": total,
        "retained_output_bytes": retained_bytes,
        "inherited_deadline": INHERITED_DEADLINE,
        "deadline": context["deadline"],
        "eligibility": dict.fromkeys(
            (
                "training_allowed",
                "independent_test_allowed",
                "model_deployment_allowed",
                "dataset_redistribution_allowed",
            ),
            False,
        ),
        "unchanged_frozen_scientific_acceptance": True,
        "source_only_development_not_expert_gold": True,
        "full_match_accuracy_established": False,
        "context_sha256": digest(output / "context.json"),
        "combined_index_sha256": digest(output / "combined-target-index.json"),
        "observed_at": time.time(),
    }
    old.metadata.exclusive_json(output / "aggregate.json", result)
    return {**result, "aggregate_sha256": digest(output / "aggregate.json")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "audit"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--granted-at", type=int)
    parser.add_argument("--timestamp", type=Path)
    args = parser.parse_args(argv)
    root, output = args.root.resolve(strict=True), args.output.resolve()
    if output.parent != root / ".cache" or not output.name.startswith("rally228-"):
        parser.error(
            "Use an exclusive rally228-* output directly inside the original cache"
        )
    for name in (
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "AGENT_PROJECT_TOKEN",
        "OPENAI_API_KEY",
        "CODEX_API_KEY",
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
    ):
        os.environ.pop(name, None)
    os.environ.update(
        BADMINTON_ROOT=str(root),
        BADMINTON_DATA_DIR=str(root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(root / "models/weights"),
        PYTHONDONTWRITEBYTECODE="1",
    )
    try:
        old = frozen(root)
        library = old.frozen_library(root, acceptance=args.phase == "audit")
        if args.phase == "freeze":
            result = freeze(root, output, args.granted_at, old, library)
        elif args.phase == "run":
            with old.metadata.dispatch_lock(output / "owner.lock"):
                result = run(root, output, args.timestamp, old, library)
        else:
            result = audit(root, output, args.timestamp, old, library)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "scientific_accuracy_established": False,
                }
            )
        )
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
