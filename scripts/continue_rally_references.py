"""Freeze, execute and audit a separately granted native-reference continuation.

Requires the original host's immutable private evidence. A clone does not
provide that evidence. This command never renews a predecessor execution grant.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

CHECKOUT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location(
    "reference_continuation_metadata",
    CHECKOUT / "backend/badminton/rally_reference_continuation.py",
)
metadata = importlib.util.module_from_spec(spec)
spec.loader.exec_module(metadata)
SCHEMA = json.loads(
    '{"additionalProperties": false, "properties": {"actors": {"items": {"additionalProperties": false, "properties": {"actor_id": {"type": "string"}, "description": {"type": "string"}, "identity_supported": {"type": "boolean"}}, "required": ["actor_id", "description", "identity_supported"], "type": "object"}, "type": "array"}, "continuity_notes": {"type": "string"}, "coverage_complete": {"type": "boolean"}, "eligibility": {"additionalProperties": false, "properties": {"dataset_redistribution_allowed": {"type": "boolean"}, "independent_test_allowed": {"type": "boolean"}, "model_deployment_allowed": {"type": "boolean"}, "training_allowed": {"type": "boolean"}}, "required": ["training_allowed", "independent_test_allowed", "model_deployment_allowed", "dataset_redistribution_allowed"], "type": "object"}, "end_censored": {"type": "boolean"}, "events": {"items": {"additionalProperties": false, "properties": {"actor_id": {"type": ["string", "null"]}, "evidence": {"enum": ["ground_contact", "net_fault", "fault", "stopped_play", "unknown", null], "type": ["string", "null"]}, "family": {"enum": ["clear", "lift", "net", "drop", "smash", "drive", "other", "unknown", null], "type": ["string", "null"]}, "interval": {"items": {"type": "integer"}, "maxItems": 2, "minItems": 2, "type": "array"}, "kind": {"enum": ["serve", "shot", "rally_end", "unresolved_contact"], "type": "string"}, "reason": {"type": "string"}, "side": {"enum": ["forehand", "backhand", "unknown"], "type": "string"}}, "required": ["kind", "interval", "actor_id", "family", "side", "evidence", "reason"], "type": "object"}, "type": "array"}, "frame_states": {"items": {"additionalProperties": false, "properties": {"camera_view": {"type": "string"}, "contact_state": {"enum": ["none_observed", "observed", "possible", "unknown"], "type": "string"}, "frame": {"type": "integer"}, "scene": {"enum": ["live", "replay", "non_play", "unknown"], "type": "string"}}, "required": ["frame", "scene", "camera_view", "contact_state"], "type": "object"}, "type": "array"}, "independent_source_only": {"type": "boolean"}, "inspected_frames": {"items": {"additionalProperties": false, "properties": {"frame": {"type": "integer"}, "sha256": {"type": "string"}}, "required": ["frame", "sha256"], "type": "object"}, "type": "array"}, "previous_segment_sha256": {"type": ["string", "null"]}, "scene": {"enum": ["live", "replay", "non_play", "unknown"], "type": "string"}, "session_id": {"type": "string"}, "source_id": {"type": "string"}, "stage": {"enum": ["dense"], "type": "string"}, "start_censored": {"type": "boolean"}, "stream": {"enum": ["independent_a", "independent_b", "adjudication"], "type": "string"}, "unresolved_gaps": {"items": {"additionalProperties": false, "properties": {"interval": {"items": {"type": "integer"}, "maxItems": 2, "minItems": 2, "type": "array"}, "reason": {"type": "string"}}, "required": ["interval", "reason"], "type": "object"}, "type": "array"}}, "required": ["stage", "stream", "source_id", "session_id", "independent_source_only", "eligibility", "inspected_frames", "previous_segment_sha256", "continuity_notes", "coverage_complete", "scene", "start_censored", "end_censored", "unresolved_gaps", "actors", "frame_states", "events"], "type": "object"}'
)
SINGLES = "go2uajSiBnE"
DOUBLES = "H1setLK1tig"
OLD_DEADLINE = 1792820409
PRIOR_BYTES = 7479083253
CONSUMER_PATHS = (
    "backend/badminton/rally_reference_continuation.py",
    "scripts/continue_rally_references.py",
    "data/manifests/rally_reference_protocol_v5.json",
)


def frozen_library(root, *, acceptance=False):
    suffix = "acceptance" if acceptance else "producer"
    checkout = root / f".cache/worktrees/rally212-{suffix}-v1"
    # This script loads its own pure metadata module by file path, so the
    # badminton package can be imported exclusively from the frozen checkout.
    sys.path.insert(0, str(checkout / "backend"))
    from badminton import rally_source_reference

    expected = (
        "6cb7e4fa13ed591322e48b9de96c139d91cb41a8"
        if acceptance
        else "eebbe210c83aefb9d467e3740dbf1a39f161ac2a"
    )
    actual = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=checkout, text=True
    ).strip()
    if actual != expected:
        raise ValueError("Frozen scientific consumer revision changed")
    return rally_source_reference


def paths(root):
    return {
        "base": root / ".cache/rally212-source-only-v1",
        "native": root / ".cache/rally208-source-only-v1/dense-v1",
        "plan": root / ".cache/rally212-targeted-plan-v1/plan.json",
        "producer": root / ".cache/worktrees/rally212-producer-v1",
        "acceptance": root / ".cache/worktrees/rally212-acceptance-v1",
    }


def source_chunks(plan):
    return [
        {**chunk, "source_id": source["source_id"]}
        for source in plan["sources"]
        for chunk in source["chunks"]
    ]


def code_binding():
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=CHECKOUT):
        raise ValueError("Commit current consumers/protocol before freezing")
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=CHECKOUT, text=True
        ).strip(),
        "files": {name: metadata.digest(CHECKOUT / name) for name in CONSUMER_PATHS},
        "python": platform.python_version(),
        "platform": platform.platform(),
        "psutil": psutil.__version__,
    }


def historical_contexts(root, library):
    for suffix, relative, expected in (
        (
            "producer",
            ".cache/rally212-context-v1.json",
            "c244dd047bfb8fdafa5d17601db8313912bee05b031d187971a3cc0e0af5d71e",
        ),
        (
            "acceptance",
            ".cache/rally212-acceptance-freeze-v1/context.json",
            "ae3641601b64faeec9dce338f76ae1dcd780f1c219d460f3085bfa9e5dc82468",
        ),
    ):
        path = root / relative
        if metadata.digest(path) != expected:
            raise ValueError("Archived context hash changed")
        saved = metadata.read(path)
        checkout = paths(root)[suffix]
        actual = library.consumer_context(
            checkout,
            checkout / saved["protocol_path"],
            saved["input_root"],
            saved["granted_at"],
        )
        metadata.archived_context(saved, actual)
        if saved["deadline"] != OLD_DEADLINE:
            raise ValueError("Predecessor deadline changed")


def original_metadata(root, library, identities):
    p = paths(root)
    plan = metadata.read(p["plan"])
    for study, stage in (
        ("rally62-source-only-v1", "assessment-v1"),
        ("rally208-source-only-v1", "assessment-v1"),
        ("rally210-source-only-v1", "dense-assessment-v1"),
    ):
        for path in sorted((root / ".cache" / study / stage).rglob("finish.json")):
            identities.add(metadata.read(path), success=False)
    if len(identities.threads) != 245:
        raise ValueError("Predecessor session inventory changed")
    for lane in library.STREAMS[:2]:
        index_path = p["base"] / "dense-assessment-v1" / lane / "index.json"
        if metadata.digest(index_path) != plan["original_index_sha256"][lane]:
            raise ValueError("Original exhaustive index changed")
        index = metadata.read(index_path)
        if len(index["segments"]) != 256:
            raise ValueError("Original exhaustive stream is incomplete")
        for entry in index["segments"]:
            for field in ("original", "receipt"):
                if metadata.digest(entry[field + "_path"]) != entry[field + "_sha256"]:
                    raise ValueError("Original exhaustive artifact changed")
            identities.add(metadata.read(entry["receipt_path"]))
    if len(identities.threads) != 757:
        raise ValueError("Original global execution identities changed")
    audit = Path(plan["original_audit_receipt"])
    if (
        metadata.digest(audit) != plan["original_audit_sha256"]
        or plan["original_audit_sha256"]
        != "d381dd9c7d39c9fa30ea1c85088b2192d24a716a5d4bc768d7022684c23cf110"
    ):
        raise ValueError("Frozen original execution audit changed")
    return plan


def verify_run(
    root, library, folder, chunk, identities, *, granted_at, frozen_at, deadline
):
    p = paths(root)
    packet = metadata.read(p["native"] / f"{chunk['source_id']}.packet.json")
    by_frame = {row["frame"]: row for row in packet["frames"]}
    entry = metadata.verify_execution(
        folder,
        chunk,
        granted_at=granted_at,
        frozen_at=frozen_at,
        deadline=deadline,
        identities=identities,
    )
    start = metadata.read(folder / "start.json")
    images = [
        {"frame": n, "sha256": by_frame[n]["image"]["sha256"]} for n in chunk["frames"]
    ]
    if start["images"] != images:
        raise ValueError("Native image identities changed")
    schema = folder.parent / "schema.json"
    if metadata.read(schema) != SCHEMA:
        raise ValueError("Source-only output schema changed")
    command = start["command"]
    expected = [
        command[0],
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
    for frame in chunk["frames"]:
        image = p["native"] / by_frame[frame]["image"]["path"]
        if metadata.digest(image) != by_frame[frame]["image"]["sha256"]:
            raise ValueError("Original PNG changed")
        expected.extend(("--image", str(image)))
    expected.append("-")
    if command != expected or Path(start["cwd"]) != p["producer"]:
        raise ValueError("Actual source-only CLI invocation changed")
    prompt = (folder / "prompt.txt").read_text(encoding="utf-8")
    context_bytes = len(
        json.dumps({"prompt": prompt, "schema": SCHEMA}, ensure_ascii=True).encode(
            "utf-8"
        )
    )
    protocol = metadata.read(
        p["producer"] / "data/manifests/rally_reference_protocol_v4.json"
    )
    cost = library.transport_cost(
        [by_frame[n]["image"]["bytes"] for n in chunk["frames"]],
        context_bytes=context_bytes,
        protocol=protocol,
    )
    if (
        cost != start["transport_cost"]
        or cost["base64_image_bytes"] != chunk["base64_bytes"]
    ):
        raise ValueError("Actual controlled transport cost changed")
    return entry


def predecessor(root, library):
    protocol = metadata.read(CHECKOUT / CONSUMER_PATHS[-1])
    p = paths(root)
    for relative, expected in protocol["predecessor_artifacts"].items():
        if metadata.digest(root / relative) != expected:
            raise ValueError("Predecessor binding changed")
    tools = metadata.read(root / ".cache/rally212-downstream-tools-freeze-v5.json")
    for name, expected in tools["files"].items():
        if metadata.digest(root / ".cache" / name) != expected:
            raise ValueError("Frozen predecessor execution tool changed")
    for number, expected in protocol["original_public_protocols"].items():
        if (
            metadata.digest(
                CHECKOUT / f"data/manifests/rally_reference_protocol_v{number}.json"
            )
            != expected
        ):
            raise ValueError("Original public protocol changed")
    historical_contexts(root, library)
    old_context = metadata.read(root / ".cache/rally212-context-v1.json")
    old_protocol = library.load_protocol(p["producer"] / old_context["protocol_path"])
    clocks = library.verify_originals(old_context["input_root"], old_protocol)
    library.verify_worker(p["native"], root)
    for source in old_protocol["sources"]:
        sid = source["source_id"]
        packet_path = p["native"] / f"{sid}.packet.json"
        if (
            metadata.digest(packet_path)
            != old_protocol["predecessor"]["dense_packets"][sid]
        ):
            raise ValueError("Native packet changed")
        packet = metadata.read(packet_path)
        library.verify_packet(packet, p["native"], clocks[sid], packet["memberships"])
    interruption = metadata.read(root / ".cache/rally212-interruption-v1/receipt.json")
    for row in interruption["recorded_lifetimes"]:
        if metadata.digest(root / row["path"]) != row["sha256"]:
            raise ValueError("Archived process evidence changed")
        metadata.absent(row)
    identities = metadata.Identities()
    plan = original_metadata(root, library, identities)
    seal = metadata.read(
        root / ".cache/rally212-targeted-plan-v1/execution-seal-v5.json"
    )
    prefix = []
    for source in plan["sources"]:
        sid = source["source_id"]
        folder = p["base"] / "targeted-assessment-v1/adjudication" / sid
        count = protocol["retained_successes"][sid]
        for chunk in source["chunks"][:count]:
            row = {**chunk, "source_id": sid}
            prefix.append(
                verify_run(
                    root,
                    library,
                    folder / f"{sid}-{chunk['index']:03d}",
                    row,
                    identities,
                    granted_at=seal["granted_at"],
                    frozen_at=seal["frozen_at"],
                    deadline=OLD_DEADLINE,
                )
            )
        if len(list(folder.glob("*/finish.json"))) != count:
            raise ValueError("Unexpected predecessor target inventory")
    charged = metadata.payload_total(
        1400881755, p["base"].rglob("payload-reservation.json")
    )
    if charged != PRIOR_BYTES or len(identities.threads) != 935:
        raise ValueError("Predecessor payload/session inventory changed")
    return plan, prefix, identities


def retained_bytes(root):
    # Never enumerate unrelated scientific studies, holdouts or input directories.
    import stat

    prefixes = (
        "rally62",
        "rally208",
        "rally210",
        "rally212",
        "rally226",
        "client223",
        "guidance213",
        "verify-guidance213",
        "rally-transport",
        "rally-successor",
        "prepare-rally-successor",
        "publish-rally-successor",
        "verify-rally-successor",
        "verify-rally208",
        "prepare-rally-continuation",
    )
    parents = [
        p for p in (root / ".cache").iterdir() if p.name.lower().startswith(prefixes)
    ]
    parents.extend(
        p
        for p in (root / ".cache/worktrees").iterdir()
        if p.name.lower().startswith(
            ("rally62", "rally208", "rally210", "rally212", "rally226", "client223")
        )
    )
    total = 0
    for parent in parents:
        if parent.is_symlink():
            raise ValueError("Research output root must not be a symlink")
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
    if total > metadata.MAX_BYTES:
        raise ValueError("Retained outputs exceed cumulative bound")
    return total


def freeze(root, output, granted_at, library):
    deadline = metadata.current_deadline(granted_at)
    binding = code_binding()
    plan, prefix, _ = predecessor(root, library)
    remaining = [
        c for c in source_chunks(plan) if c["source_id"] == SINGLES and c["index"] >= 94
    ]
    projected = PRIOR_BYTES + sum(c["image_bytes"] for c in remaining)
    if len(remaining) != 78 or projected > metadata.MAX_BYTES:
        raise ValueError("Continuation full suffix is not feasible")
    output.mkdir(exist_ok=False)
    (output / "runs").mkdir()
    metadata.exclusive_json(output / "runs/schema.json", SCHEMA)
    cli = Path(shutil.which("codex") or "").resolve(strict=True)
    context = {
        "task": 226,
        "granted_at": granted_at,
        "deadline": deadline,
        "frozen_at": time.time(),
        "consumers": binding,
        "prefix": prefix,
        "suffix": remaining,
        "prior_image_bytes": PRIOR_BYTES,
        "projected_image_bytes": projected,
        "retained_output_bytes": retained_bytes(root),
        "cli": {"path": str(cli), "sha256": metadata.digest(cli)},
        "scientific_labels_read": False,
        "images_dispatched": 0,
        "original_deadline": OLD_DEADLINE,
    }
    metadata.exclusive_json(output / "context.json", context)
    return {
        "phase": "frozen",
        "remaining_sessions": len(remaining),
        "projected_image_bytes": projected,
        "context_sha256": metadata.digest(output / "context.json"),
        "new_labels_read": False,
    }


def assessment_prompt(*, session, sid, previous, own_notes, assigned):
    lane = "adjudication"
    return f"You are a genuinely fresh independent blind source-only badminton targeted adjudication session for owner-authorized issue226, stream {lane}. Inspect EVERY attached original oriented native PNG, in attachment order. The attached contiguous native region and any two-frame joins are original source images. These targeted transport regions are not a third exhaustive source stream. No original assessor labels, model predictions, event markers or adjudication opinions are supplied. No tools, filesystem, network, shell, delegation, other images, repository files, account files, other-stream labels or PROGRESS access is authorized. All originals are already attached. Return private original JSON under the provided schema.\n\nActual fresh process/session locator: {session}. Echo exactly. stage=dense; stream={lane}; source_id={sid}; independent_source_only=true; all four eligibility flags=false. inspected_frames lists every assigned frame/hash in order. previous_segment_sha256={json.dumps(previous['sha256'] if previous else None)}. coverage_complete means every attached image was actually inspected; it does NOT mean all contacts are discernible. frame_states needs an explicit scene, stable source camera_view and contact_state on EVERY frame. Use unknown for uncertainty, possible for a plausible unresolved contact; none_observed is not a claim that an occluded contact was absent.\n\nEnumerate every visibly supported or unresolved racket contact, serve and separately evidenced rally ending, in chronological order, with inclusive native uncertainty intervals wholly inside the assigned chunk. Observed/possible contact-state rows must be covered by serve/shot/unresolved_contact events. Do not invent a point contact from nearest player, shuttle disappearance or a last stroke. Serve kind has family=null. Shots use only clear/lift/net/drop/smash/drive/other/unknown; exclude half smash. Forehand/backhand requires supported source mechanics and handedness; preserve unknown. Terminal kind rally_end needs source ground_contact/net_fault/fault/stopped_play/unknown evidence separately from last racket contact. No event when no source event is observed; preserve uncertainty in frame states and unresolved_gaps instead. Include actual relevant uncertainty intervals, never force opening/ending events into every chunk.\n\nDefine SOURCE actors independently of tracker IDs, court end and screen position, with concrete visual descriptions and identity_supported=false when unresolved. Keep your own actor IDs and descriptions EXACTLY stable across this same-source stream while evidence supports continuity. Same-view source camera_view should remain stable; unknown or scene/camera transitions remain explicit. Censoring refers to a cut/occlusion truncating relevant source event evidence, not merely this arbitrary transport chunk boundary. Include unresolved_gaps for source visibility, identity, contact or scene uncertainty. Preserve all uncertainties in continuity_notes, including your stable actor definitions, camera naming, source context and any contact/terminal uncertainty crossing the transport join; do not silently reconcile conflicting overlap evidence.\n\nSame-stream prior source-only continuity (no other stream): {own_notes}\n\nOrdered exact assigned originals (native PTS/timebase/orientation/hash preserved):\n{json.dumps(assigned, ensure_ascii=True)}\n\nReturn only schema JSON. This is development source assessment, not expert gold truth or automatic annotation accuracy. Do not infer a whole-rally completeness result from this chunk."


def verify_current(output, timestamp, *, live):
    context = metadata.read(output / "context.json")
    if context["consumers"] != code_binding():
        raise ValueError("Frozen continuation consumers/runtime changed")
    if context["deadline"] != context["granted_at"] + 8 * 3600:
        raise ValueError("Successor deadline changed")
    if live:
        metadata.current_deadline(context["granted_at"])
    stamp = metadata.read(timestamp)
    published = datetime.fromisoformat(
        stamp["created_at"].replace("Z", "+00:00")
    ).timestamp()
    if (
        stamp["user"]["login"] != "Ken0u"
        or "/issues/226#issuecomment-" not in stamp["html_url"]
        or metadata.digest(output / "context.json") not in stamp["body"]
        or not context["frozen_at"] <= published <= time.time()
    ):
        raise ValueError("Prospective owning-issue timestamp is missing or mismatched")
    cli = context["cli"]
    if metadata.digest(cli["path"]) != cli["sha256"]:
        raise ValueError("Frozen CLI executable changed")
    return context, published


def fence(output, reason):
    with metadata.dispatch_lock(output / "dispatch.lock"):
        try:
            metadata.exclusive_json(
                output / "STOP.json",
                {"reason": reason, "at": time.time(), "signals_sent": 0},
            )
        except FileExistsError:
            pass


def owner():
    process = psutil.Process()
    return {
        "pid": process.pid,
        "creation_time": process.create_time(),
        "cwd": process.cwd(),
        "command": process.cmdline(),
        "started_at": time.time(),
    }


def run(root, output, timestamp, library):
    context, published = verify_current(output, timestamp, live=True)
    plan, prefix, _ = predecessor(root, library)
    if prefix != context["prefix"] or list(
        (output / "runs").glob("*/payload-reservation.json")
    ):
        raise ValueError("Immutable prefix changed or execution already attempted")
    if (output / "STOP.json").exists():
        raise ValueError("Successor dispatch is fenced")
    p = paths(root)
    metadata.exclusive_json(output / "owner.json", owner())
    schema = output / "runs/schema.json"
    if metadata.read(schema) != SCHEMA:
        raise ValueError("Frozen output schema changed")
    packet = metadata.read(p["native"] / f"{SINGLES}.packet.json")
    rows = {row["frame"]: row for row in packet["frames"]}
    protocol = library.load_protocol(
        p["producer"] / "data/manifests/rally_reference_protocol_v4.json"
    )
    # Narrow execution exception: only the validated same-stream predecessor
    # notes seed continuity. Other targeted labels remain sealed until audit.
    earlier = next(
        entry
        for entry in prefix
        if entry["source_id"] == SINGLES and entry["chunk"] == 93
    )
    document = metadata.read(earlier["original_path"])
    receipt = metadata.read(earlier["receipt_path"])
    if (
        hashlib.sha256(library.encoded(document)).hexdigest()
        != receipt["segment_sha256"]
    ):
        raise ValueError("Same-stream predecessor content changed")
    previous = {
        "sha256": receipt["segment_sha256"],
        "stream": "adjudication",
        "source_id": SINGLES,
        "stage": "dense",
        "last_frames": earlier["frames"][-2:],
    }
    own_notes = document["continuity_notes"]
    previous_region = next(
        source for source in plan["sources"] if source["source_id"] == SINGLES
    )["chunks"][93]["region_index"]
    new_entries = []
    for chunk in context["suffix"]:
        verify_current(output, timestamp, live=True)
        if retained_bytes(root) >= metadata.MAX_BYTES - 64 * 1024**2:
            raise ValueError("Insufficient retained-output headroom")
        if chunk["region_index"] != previous_region:
            previous = None
            own_notes = (
                "A disconnected source region begins; intervening images are not attached. Do not assert unseen continuity. Your own earlier source notes only: "
                + own_notes
            )
        previous_region = chunk["region_index"]
        name = f"{SINGLES}-{chunk['index']:03d}"
        folder = output / "runs" / name
        folder.mkdir(exist_ok=False)
        assigned = [
            {
                "frame": n,
                "pts": rows[n]["pts"],
                "time_base": rows[n]["time_base"],
                "time_s": rows[n]["time_s"],
                "rotation": rows[n]["rotation"],
                "display_size": rows[n]["display_size"],
                "sha256": rows[n]["image"]["sha256"],
            }
            for n in chunk["frames"]
        ]
        images = [p["native"] / rows[n]["image"]["path"] for n in chunk["frames"]]
        if (
            len(images) > 20
            or sum(image.stat().st_size for image in images) != chunk["image_bytes"]
        ):
            raise ValueError("Assigned native image cost changed")
        for n, image in zip(chunk["frames"], images):
            if metadata.digest(image) != rows[n]["image"]["sha256"]:
                raise ValueError("Original PNG changed before dispatch")
        session = f"codex-cli:request=continuation226:adjudication:{SINGLES}:{chunk['index']}:{time.time_ns()}"
        prompt = assessment_prompt(
            session=session,
            sid=SINGLES,
            previous=previous,
            own_notes=own_notes,
            assigned=assigned,
        )
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8", newline="\n")
        cost = library.transport_cost(
            [image.stat().st_size for image in images],
            context_bytes=len(
                json.dumps(
                    {"prompt": prompt, "schema": SCHEMA}, ensure_ascii=True
                ).encode("utf-8")
            ),
            protocol=protocol,
        )
        if cost["base64_image_bytes"] != chunk["base64_bytes"]:
            raise ValueError("Frozen controlled transport cost changed")
        reservation = {
            "run_name": name,
            "lane": "adjudication",
            "source_id": SINGLES,
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
        total, child = metadata.reserve_and_launch(
            output,
            reservation,
            granted_at=context["granted_at"],
            prior_bytes=PRIOR_BYTES,
            launch=lambda: subprocess.Popen(
                command,
                cwd=p["producer"],
                env=os.environ.copy(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            ),
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
            metadata.exclusive_json(folder / "start.json", start)
        except BaseException:
            fence(output, "child_identity_or_start_persistence_failed")
            # Preserve the child; never invent exit or signal it on observer error.
            raise
        finish = {
            **start,
            **metadata.collect_output(
                child, prompt, folder, lambda reason: fence(output, reason)
            ),
        }
        final = folder / "original-final.json"
        if final.exists():
            finish["original_output_sha256"] = metadata.digest(final)
            if final.stat().st_size < metadata.MAX_LOG_BYTES:
                try:
                    document = metadata.read(final)
                    finish["segment_sha256"] = hashlib.sha256(
                        library.encoded(document)
                    ).hexdigest()
                    finish["original_resolution_viewing"] = True
                except (ValueError, UnicodeError, RecursionError):
                    finish["execution_protocol_failures"].append(
                        "malformed_original_final"
                    )
            else:
                finish["execution_protocol_failures"].append(
                    "original_final_size_limit"
                )
        else:
            finish["execution_protocol_failures"].append("missing_original_final")
        metadata.exclusive_json(folder / "finish.json", finish)
        if finish["execution_protocol_failures"]:
            fence(output, "execution_protocol_failed")
            raise ValueError("Original execution failed; no implicit replacement")
        metadata.absent(start)
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
            fence(output, "source_assessment_validation_failed")
            raise
        entry = verify_run(
            root,
            library,
            folder,
            chunk,
            metadata.Identities(),
            granted_at=context["granted_at"],
            frozen_at=published,
            deadline=context["deadline"],
        )
        new_entries.append(entry)
        metadata.exclusive_json(folder / "entry.json", entry)
        previous = {
            "sha256": finish["segment_sha256"],
            "stream": "adjudication",
            "source_id": SINGLES,
            "stage": "dense",
            "last_frames": chunk["frames"][-2:],
        }
        own_notes = document["continuity_notes"]
        print(
            json.dumps(
                {
                    "phase": "segment_exited",
                    "chunk": chunk["index"],
                    "completed_new_sessions": len(new_entries),
                    "cumulative_image_bytes": total,
                }
            ),
            flush=True,
        )
        time.sleep(5)
    index_by_chunk = {
        (entry["source_id"], entry["chunk"]): entry for entry in [*prefix, *new_entries]
    }
    chunks = source_chunks(plan)
    combined = metadata.complete_index(
        chunks, [index_by_chunk[(c["source_id"], c["index"])] for c in chunks]
    )
    metadata.exclusive_json(output / "combined-target-index.json", combined)
    return {
        "phase": "execution_complete",
        "new_sessions": len(new_entries),
        "targeted_sessions": len(combined["segments"]),
        "scientific_acceptance_performed": False,
    }


def audit(root, output, timestamp, library):
    context, published = verify_current(output, timestamp, live=False)
    if not (output / "combined-target-index.json").exists():
        return {
            "ready": False,
            "reason": "both_complete_target_indexes_required",
            "scientific_labels_read": False,
        }
    metadata.absent(metadata.read(output / "owner.json"))
    plan, prefix, identities = predecessor(root, library)
    if prefix != context["prefix"] or (output / "STOP.json").exists():
        raise ValueError("Predecessor metadata changed or execution fenced")
    chunks = source_chunks(plan)
    entries = {(e["source_id"], e["chunk"]): e for e in prefix}
    expected = {f"{SINGLES}-{chunk['index']:03d}" for chunk in context["suffix"]}
    for filename in (
        "start.json",
        "finish.json",
        "payload-reservation.json",
        "entry.json",
    ):
        if {p.parent.name for p in (output / "runs").glob("*/" + filename)} != expected:
            raise ValueError("Successor execution inventory differs from frozen suffix")
    previous_end = None
    for chunk in context["suffix"]:
        folder = output / "runs" / f"{SINGLES}-{chunk['index']:03d}"
        entry = verify_run(
            root,
            library,
            folder,
            chunk,
            identities,
            granted_at=context["granted_at"],
            frozen_at=published,
            deadline=context["deadline"],
        )
        if entry != metadata.read(folder / "entry.json"):
            raise ValueError("Successor index differs from actual execution")
        start, finish = (
            metadata.read(folder / "start.json"),
            metadata.read(folder / "finish.json"),
        )
        if previous_end is not None and start["started_at"] < previous_end + 5:
            raise ValueError("Sequential source pacing violated")
        previous_end = finish["ended_at"]
        entries[(entry["source_id"], entry["chunk"])] = entry
    combined = metadata.complete_index(
        chunks, [entries[(c["source_id"], c["index"])] for c in chunks]
    )
    if combined != metadata.read(output / "combined-target-index.json"):
        raise ValueError("Combined target index changed")
    total = metadata.payload_total(
        PRIOR_BYTES, (output / "runs").glob("*/payload-reservation.json")
    )
    if total != context["projected_image_bytes"] or len(identities.threads) != 1013:
        raise ValueError("Complete global payload/session census differs")
    retained = retained_bytes(root)
    # No targeted comparison happens above this point. Both complete indexes,
    # every genuine global identity and old/new execution clocks now verify.
    p = paths(root)
    results = []
    for source in plan["sources"]:
        sid = source["source_id"]
        packet = metadata.read(p["native"] / f"{sid}.packet.json")
        streams = {}
        for lane in library.STREAMS[:2]:
            original = metadata.read(
                p["base"] / "dense-assessment-v1" / lane / "index.json"
            )
            streams[lane] = [
                (metadata.read(e["original_path"]), metadata.read(e["receipt_path"]))
                for e in original["segments"]
                if e["source_id"] == sid
            ]
        streams["adjudication"] = []
        previous = region = None
        protocol = library.load_protocol(
            p["acceptance"] / "data/manifests/rally_reference_protocol_v4.json"
        )
        for chunk in source["chunks"]:
            if chunk["region_index"] != region:
                previous = None
            entry = entries[(sid, chunk["index"])]
            document, receipt = (
                metadata.read(entry["original_path"]),
                metadata.read(entry["receipt_path"]),
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
    result = {
        "task": 226,
        "source_slots": 2,
        "native_frames": 1532,
        "complete_references": sum(row["complete_reference"] for row in results),
        "all_requested_labels_supported_slots": sum(
            row["all_requested_labels_supported"] for row in results
        ),
        "results": results,
        "genuine_completed_threads": len(identities.threads),
        "attempted_image_bytes": total,
        "retained_output_bytes": retained,
        "original_deadline": OLD_DEADLINE,
        "successor_deadline": context["deadline"],
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
        "context_sha256": metadata.digest(output / "context.json"),
        "combined_index_sha256": metadata.digest(output / "combined-target-index.json"),
        "observed_at": time.time(),
    }
    metadata.exclusive_json(output / "aggregate.json", result)
    return {**result, "aggregate_sha256": metadata.digest(output / "aggregate.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run", "audit"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--granted-at", type=int)
    parser.add_argument("--timestamp", type=Path)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    output = args.output.resolve()
    if output.parent != root / ".cache" or not output.name.startswith("rally226-"):
        parser.error(
            "Use an exclusive rally226-* output directly inside the original root cache"
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
        library = frozen_library(root, acceptance=args.phase == "audit")
        if args.phase == "freeze":
            result = freeze(root, output, args.granted_at, library)
        elif args.phase == "run":
            with metadata.dispatch_lock(output / "owner.lock"):
                result = run(root, output, args.timestamp, library)
        else:
            result = audit(root, output, args.timestamp, library)
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
