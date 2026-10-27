"""One remaining-only cached diagnostic with immutable predecessor evidence.

This consumer never loads a neural checkpoint, generates pixels, fits a model,
parses generated-test predictions or changes application annotations/defaults.
"""

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path
from uuid import uuid4

import psutil

from . import shuttle_selection_study as predecessor
from . import shuttle_validation as audit

existing = predecessor.existing
publish = predecessor.publish
PROTOCOL = json.loads(r"""
{
  "schema_version": 1,
  "name": "shuttle-selection-continuation-v1",
  "predecessor_root": ".cache/selector330-experiment-v1",
  "predecessor_delivered_source": "73dcb1799eb19b7489e0cf84c7654134c347f386",
  "predecessor_experiment_sha256": "73cb4577be8638045bafcb61a852fe2e52e29971869729898a964531e42a35d0",
  "predecessor_fits_sha256": "61a2f32f846f4916bbf32afd882aeb4ff36e142dd1fb67051066e5918a9fccaa",
  "predecessor_test_sha256": "0d1f89d51ba40d67efc72846fed0adb2f5a0090b51a2813315859fa379ea2cb2",
  "predecessor_fit_public_seal_sha256": "97ecb361eca681890493bcc06f17fc956f85425ee385748f482efdb3dc1da86e",
  "original_granted_at": 1793063655,
  "deadline": 1793106855,
  "variants": [
    "control",
    "decoder",
    "convolution"
  ],
  "fixed_thresholds": {
    "control": 0.5,
    "decoder": 0.5,
    "convolution": 0.6
  },
  "input_artifacts": {
    "parent-checkpoint": {
      "path": "models/weights/TrackNet_best.pt",
      "sha256": "df867641a02712b021f04548ff4b1208ddfdb47f629ab2094ceb978667e83b1a"
    },
    "decoder-checkpoint": {
      "path": ".cache/capacity311-experiment-v1/decoder/epoch-4.pt",
      "sha256": "1506668b947a90f2d3cff79ef23a480aa97c9aed1a802fcffec9df6e8bb42598"
    },
    "convolution-checkpoint": {
      "path": ".cache/capacity311-experiment-v1/convolution/epoch-4.pt",
      "sha256": "2c65087f1849bc0a22740aa48c252b5cfd92a175693f08f18350c639082d4833"
    },
    "decoder-selection": {
      "path": ".cache/capacity311-experiment-v1/decoder/selection.json",
      "sha256": "60dfcab0bfc3d9bb524b4ac53a5bb1b3d63bdcc835751e5b5d055149f9f08d0d"
    },
    "convolution-selection": {
      "path": ".cache/capacity311-experiment-v1/convolution/selection.json",
      "sha256": "acf50a4e63fef72310145650593e5eb136f9d6c023a944fe156499cffe0533db"
    },
    "capacity-experiment": {
      "path": ".cache/capacity311-experiment-v1/experiment.json",
      "sha256": "780374cc379534d853680bafa0159bcad7d6ee5783f942a616a9dd00a40d40f3"
    },
    "capacity-raw-index": {
      "path": ".cache/capacity313-experiment-v1/raw-index.json",
      "sha256": "a0a383d3df756f0095d0025b414385d8294aa77df5fb286d69a174d377daa4df"
    },
    "capacity-continuation-experiment": {
      "path": ".cache/capacity313-experiment-v1/experiment.json",
      "sha256": "c15ae687689784f4bd9d05bcbd3747b89286925c861298db7f09c090657c39e5"
    },
    "capacity-continuation-completion": {
      "path": ".cache/capacity313-completion-v1.json",
      "sha256": "1bfbdf4d148a6086a08bc49c175c86f5afeb2c83726f6489d5e66f3fc9b316c1"
    },
    "familiar-source-inventory": {
      "path": ".cache/shuttle65-source-inventory.json",
      "sha256": "273e0749d148e952ad1fb0534363b3971e2584702f834ad2084c59e632990822"
    },
    "familiar-source-packet": {
      "path": ".cache/shuttle139-packet-v1/packet.json",
      "sha256": "3b22c07a3592728b6aa17e7d7c28f0089a8820b1373ace1289796d2e99e5466d"
    },
    "familiar-source-labels": {
      "path": ".cache/shuttle139-labels-v1/labels.json",
      "sha256": "fd25029ae49891f544989cdbfa20e5077571c1048c960e2d77ddee1fe7abd158"
    },
    "familiar-source-baseline": {
      "path": ".cache/shuttle139-baseline-v2/baseline.json",
      "sha256": "915f678fa2b5577dff37811ba92ff9077c300eefc788fcab2873c12c2ffc6f64"
    },
    "selection-experiment": {
      "path": ".cache/selector330-experiment-v1/experiment.json",
      "sha256": "73cb4577be8638045bafcb61a852fe2e52e29971869729898a964531e42a35d0"
    },
    "selection-fits": {
      "path": ".cache/selector330-experiment-v1/fits.json",
      "sha256": "61a2f32f846f4916bbf32afd882aeb4ff36e142dd1fb67051066e5918a9fccaa"
    },
    "selection-test-completion": {
      "path": ".cache/selector330-experiment-v1/test.json",
      "sha256": "0d1f89d51ba40d67efc72846fed0adb2f5a0090b51a2813315859fa379ea2cb2"
    },
    "selection-experiment-public-seal": {
      "path": ".cache/selector330-experiment-v1/experiment-public-seal.json",
      "sha256": "f72ee02ccf184f7a9d9f8401b144dce0a716e61f15d084900ba3e33c114b6fb8"
    },
    "selection-fit-public-seal": {
      "path": ".cache/selector330-experiment-v1/fit-public-seal.json",
      "sha256": "97ecb361eca681890493bcc06f17fc956f85425ee385748f482efdb3dc1da86e"
    },
    "selection-publication-study-source": {
      "path": ".cache/worktrees/selector330-e2-publication/backend/badminton/shuttle_selection_study.py",
      "sha256": "3ba520eafd367a0e306026b7e644d840bcbb57da7251f470e2f4e4240610bce2"
    },
    "selection-preservation-proof": {
      "path": ".cache/selector330-science-verification-v1.json",
      "sha256": "7ef23098fbff2680346cda6ebc4000a3f01eb0c34378dfc5cc1e4fbf8a2cc9e9"
    },
    "selection-delivery-completion": {
      "path": ".cache/selector330-completion-v1.json",
      "sha256": "de0fc8d85980555b0d32c2075fe5ac8c54f9072fbae5d98e9903c3da4354cf12"
    },
    "selection-trainval": {
      "path": ".cache/selector330-experiment-v1/trainval.json",
      "sha256": "74b9a1d5d89bb8378a21a62749901d0e5f88dc0a5cce4210d883b5c286a2da62"
    }
  },
  "familiar": {
    "raw_output_root": ".cache/capacity313-experiment-v1",
    "views_per_method": 50,
    "rows_per_method": 13499,
    "cases": 60,
    "truth_states": {
      "visible": 25,
      "not_visible": 7,
      "unknown": 28
    },
    "localization_tolerance_diagonal": 0.005,
    "baseline_localization_tp": {
      "control": 14,
      "decoder": 16,
      "convolution": 9
    },
    "new_native_inference": false,
    "use": "development diagnostic only; retain unknown/unavailable, context and all four false eligibility flags",
    "baseline_visibility_counts": {
      "control": {
        "tp": 15,
        "fp": 3,
        "fn": 10,
        "tn": 4
      },
      "decoder": {
        "tp": 17,
        "fp": 4,
        "fn": 8,
        "tn": 3
      },
      "convolution": {
        "tp": 23,
        "fp": 6,
        "fn": 2,
        "tn": 1
      }
    },
    "baseline_localization_counts": {
      "control": {
        "tp": 14,
        "fp": 4,
        "fn": 11,
        "tn": 4
      },
      "decoder": {
        "tp": 16,
        "fp": 5,
        "fn": 9,
        "tn": 3
      },
      "convolution": {
        "tp": 9,
        "fp": 20,
        "fn": 16,
        "tn": 1
      }
    },
    "baseline_agreeing_components": {
      "control": 14,
      "decoder": 16,
      "convolution": 17
    }
  },
  "limits": {
    "cumulative_retained_bytes": 4294967296,
    "scientific_attempts": 1,
    "original_deadline": 1793106855,
    "max_runtime_hours": 2
  },
  "eligibility": {
    "training_allowed": false,
    "independent_test_allowed": false,
    "model_deployment_allowed": false,
    "dataset_redistribution_allowed": false
  },
  "limitations": [
    "The original familiar stage remains failed; this is a separately granted remaining-only diagnostic, with the same original hard deadline and cumulative budget.",
    "No generated-test rows or older consumed tests are parsed; only completion bytes/provenance and unchanged fits are consumed.",
    "No new neural inference, fitting, threshold selection, source acquisition, image transfer or promotion.",
    "All familiar views/cases and unknown/unavailable context remain in original denominators; this is development evidence, not independent accuracy.",
    "Complete independent scientific rally references remain 0/2; full-match correctness is unproven."
  ]
}
""")


def protocol_value():
    return PROTOCOL


def validate_protocol(value):
    if audit.encoded(value) != audit.encoded(protocol_value()):
        raise ValueError("Continuation protocol differs from the fixed remaining phase")


def runtime_snapshot():
    return existing.runtime_snapshot()


def consumers(root):
    result = predecessor.consumers(root)
    package = Path(__file__).resolve().parent
    code_root = (
        package.parents[1] if package.parent.name == "backend" else package.parent
    )
    result["scripts/continue_shuttle_selection.py"] = audit.seal(
        root, code_root / "scripts/continue_shuttle_selection.py"
    )
    return dict(sorted(result.items()))


def budget(root):
    """Charge old and new outputs together, without discarding old attempts."""
    files = set()
    cache = root / ".cache"
    for pattern in (
        "selector330*",
        "SELECTOR330*",
        "selector-plan*",
        "selector-planning*",
        "selector-preflight*",
        "selector-remaining*",
        "selector332*",
        "SELECTOR332*",
    ):
        for path in cache.glob(pattern):
            files.update(
                p.resolve()
                for p in (path.rglob("*") if path.is_dir() else [path])
                if p.is_file()
            )
    for pattern in ("selector330*", "selectorremaining*", "selector332*"):
        for path in (cache / "worktrees").glob(pattern):
            files.update(p.resolve() for p in path.rglob("*") if p.is_file())
    size = sum(path.stat().st_size for path in files)
    limit = protocol_value()["limits"]["cumulative_retained_bytes"]
    if type(limit) is not int or limit <= 0 or size >= limit:
        raise ValueError("Cumulative retained-output budget exhausted")
    return {"bytes": size, "files": len(files), "limit_bytes": limit}


def verify_inputs(root, protocol):
    result = {}
    for name, entry in protocol["input_artifacts"].items():
        path = audit.sealed_path(root, entry)
        result[name] = {**entry, "bytes": path.stat().st_size}
    return result


def _entry_json(root, protocol, name):
    return audit.read_json(audit.sealed_bytes(root, protocol["input_artifacts"][name]))


def _absent_lifetime(identity):
    if (
        type(identity.get("pid")) is not int
        or identity["pid"] <= 0
        or not audit.finite(identity.get("creation_time"))
        or identity["creation_time"] <= 0
        or not isinstance(identity.get("command"), list)
        or not identity["command"]
        or any(not isinstance(item, str) or not item for item in identity["command"])
    ):
        raise ValueError("Invalid predecessor process identity")
    try:
        process = psutil.Process(identity["pid"])
        if abs(process.create_time() - identity["creation_time"]) < 0.01:
            raise ValueError("Predecessor worker lifetime is still live")
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied as exc:
        raise ValueError("Cannot establish predecessor process absence") from exc


def verify_prior(root, protocol):
    """Verify original metadata and hashes, never generated-test row contents."""
    previous = audit.inside(root, protocol["predecessor_root"])
    inputs = protocol["input_artifacts"]
    expected = protocol["predecessor_experiment_sha256"]
    if (
        audit.sealed_path(root, inputs["selection-experiment"])
        != previous / "experiment.json"
        or inputs["selection-experiment"]["sha256"] != expected
    ):
        raise ValueError("Changed predecessor experiment location or binding")
    original = _entry_json(root, protocol, "selection-experiment")
    if (
        original.get("granted_at") != protocol["original_granted_at"]
        or original.get("deadline") != protocol["deadline"]
        or audit.file_hash(previous / "protocol.json")
        != original.get("protocol_sha256")
        or runtime_snapshot() != original.get("runtime")
    ):
        raise ValueError("Changed predecessor clock, protocol or runtime")
    original_protocol = audit.read_json((previous / "protocol.json").read_bytes())
    if original_protocol.get("familiar") != protocol["familiar"]:
        raise ValueError("Changed familiar recipe or original denominators")
    if set(original.get("inputs", {})) != set(
        original_protocol.get("input_artifacts", {})
    ):
        raise ValueError("Changed predecessor input membership")
    for name, entry in original.get("inputs", {}).items():
        sealed = {key: entry[key] for key in ("path", "sha256")}
        if (
            sealed != inputs.get(name)
            or sealed != original_protocol["input_artifacts"][name]
        ):
            raise ValueError("Changed predecessor input identity")
        if audit.sealed_path(root, sealed).stat().st_size != entry.get("bytes"):
            raise ValueError("Changed predecessor input byte count")
    old_consumers = original.get("consumer_files", {})
    if not old_consumers:
        raise ValueError("Missing original frozen consumers")
    for name, entry in old_consumers.items():
        audit.sealed_path(root, entry)
        if (
            audit.file_hash(audit.inside(previous / "consumer", name))
            != entry["sha256"]
        ):
            raise ValueError("Changed predecessor frozen consumer copy")

    public = _entry_json(root, protocol, "selection-experiment-public-seal")
    if public.get("experiment_sha256") != expected or not public.get(
        "comment", ""
    ).startswith(
        "https://github.com/Ken0u/badminton-match-analyzer/issues/330#issuecomment-"
    ):
        raise ValueError("Missing original public experiment commitment")
    if (
        audit.sealed_path(root, inputs["selection-fits"]) != previous / "fits.json"
        or inputs["selection-fits"]["sha256"] != protocol["predecessor_fits_sha256"]
        or inputs["selection-fit-public-seal"]["sha256"]
        != protocol["predecessor_fit_public_seal_sha256"]
    ):
        raise ValueError("Changed original fitted-method binding")
    fits, _ = predecessor.sealed_fits(
        previous, expected, protocol["predecessor_fit_public_seal_sha256"]
    )
    if set(fits["variants"]) != set(protocol["variants"]):
        raise ValueError("Changed original fixed-method membership")
    for variant, value in fits["variants"].items():
        if (
            value["validation"].get("available") is not True
            or value["validation"].get("threshold")
            != protocol["fixed_thresholds"][variant]
        ):
            raise ValueError("Changed original validation-selected threshold")
    test_path = audit.sealed_path(root, inputs["selection-test-completion"])
    if (
        test_path != previous / "test.json"
        or inputs["selection-test-completion"]["sha256"]
        != protocol["predecessor_test_sha256"]
    ):
        raise ValueError("Changed generated-test completion binding")
    predecessor.completed_stage(previous, expected, "test", test_path, "test_sha256")

    preserved = _entry_json(root, protocol, "selection-preservation-proof")
    if (
        preserved.get("experiment_sha256") != expected
        or preserved.get("familiar_status") != "failed_before_scoring"
        or preserved.get("scientific_protocol_complete") is not False
        or preserved.get("scientific_rerun") is not False
    ):
        raise ValueError("Changed original preserved incomplete outcome")
    borrowed = preserved.get("borrowed_file_inventory", {})
    if not borrowed:
        raise ValueError("Missing borrowed-file provenance")
    for name, entry in borrowed.items():
        path = audit.inside(root, name)
        if (
            audit.file_hash(path) != entry["sha256"]
            or path.stat().st_size != entry["bytes"]
        ):
            raise ValueError("Changed inherited borrowed file")
    for entry in original.get("inputs", {}).values():
        if borrowed.get(entry["path"]) != {
            "sha256": entry["sha256"],
            "bytes": entry["bytes"],
        }:
            raise ValueError("Original input absent from borrowed ledger")
    completion = _entry_json(root, protocol, "selection-delivery-completion")
    if (
        completion.get("task") != 330
        or completion.get("source") != protocol["predecessor_delivered_source"]
        or completion.get("familiar_status") != "failed_before_scoring"
        or completion.get("scientific_success") is not False
        or completion.get("promoted") is not False
    ):
        raise ValueError("Changed original verified delivery outcome")
    if any(
        (previous / name).exists() for name in ("familiar-opened.json", "familiar.json")
    ) or list(previous.glob("familiar-selected-*.json")):
        raise ValueError("Original failed familiar stage must remain untouched")

    database = root / "data/processed/catalog.sqlite3"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        jobs = {
            value["id"]: value
            for (raw,) in db.execute("SELECT document FROM jobs")
            for value in [audit.read_json(raw)]
        }
    expected_stages = {
        "trainval": "completed",
        "fit": "completed",
        "test": "completed",
        "familiar": "failed",
    }
    recorded = {value["stage"]: value for value in preserved.get("stages", [])}
    if set(recorded) != set(expected_stages):
        raise ValueError("Changed original admitted-stage membership")
    proof, seen = [], set()
    for folder in sorted((previous / "attempts").iterdir()):
        if not folder.is_dir():
            raise ValueError("Unexpected original attempt artifact")
        admitted = audit.read_json((folder / "admission.json").read_bytes())
        terminal = audit.read_json((folder / "terminal.json").read_bytes())
        stage = admitted.get("stage")
        if stage not in expected_stages or stage in seen:
            raise ValueError("Changed original scientific attempt membership")
        seen.add(stage)
        status = expected_stages[stage]
        job = jobs.get(admitted.get("job_id"), {})
        identity = admitted.get("process", {})
        if (
            admitted.get("experiment_sha256") != expected
            or job.get("status") != status
            or terminal.get("status") != status
            or recorded[stage].get("job_id") != admitted.get("job_id")
            or recorded[stage].get("store_status") != status
            or not isinstance(identity.get("cwd"), str)
            or not identity["cwd"]
            or not Path(identity["cwd"]).is_absolute()
            or Path(identity.get("cwd", "")).resolve() != root
            or job.get("owner_pid") != identity.get("pid")
            or not audit.finite(job.get("owner_started"))
            or not audit.finite(identity.get("creation_time"))
            or abs(job["owner_started"] - identity["creation_time"]) >= 0.01
        ):
            raise ValueError(
                "Changed predecessor admission, Store or process provenance"
            )
        _absent_lifetime(identity)
        if status == "completed":
            name, result_key = {
                "trainval": ("selection-trainval", "trainval_sha256"),
                "fit": ("selection-fits", "fits_sha256"),
                "test": ("selection-test-completion", "test_sha256"),
            }[stage]
            if terminal.get("result", {}).get(result_key) != inputs[name]["sha256"]:
                raise ValueError("Changed original completed-stage result")
        elif (
            terminal.get("error_type") != "FileNotFoundError"
            or "provenance" not in terminal.get("error", "")
            or recorded[stage].get("terminal_sha256")
            != audit.file_hash(folder / "terminal.json")
        ):
            raise ValueError("Original familiar failure must remain preserved")
        proof.append(
            {
                "stage": stage,
                "job_id": admitted["job_id"],
                "status": status,
                "process": identity,
                "admission": audit.seal(root, folder / "admission.json"),
                "terminal": audit.seal(root, folder / "terminal.json"),
            }
        )
    if seen != set(expected_stages):
        raise ValueError("Every original admitted stage must remain terminal")
    return {
        "experiment_sha256": expected,
        "fits_sha256": protocol["predecessor_fits_sha256"],
        "test_sha256": protocol["predecessor_test_sha256"],
        "consumer_files": old_consumers,
        "borrowed_files": borrowed,
        "jobs": sorted(proof, key=lambda value: value["stage"]),
        "public_experiment_seal": inputs["selection-experiment-public-seal"],
        "fit_public_seal": inputs["selection-fit-public-seal"],
        "delivery_source": protocol["predecessor_delivered_source"],
    }


def _clock(protocol, granted_at, deadline):
    if (
        not audit.finite(granted_at)
        or not audit.finite(deadline)
        or not audit.finite(protocol.get("original_granted_at"))
        or not audit.finite(protocol.get("deadline"))
        or deadline
        != min(
            granted_at + protocol["limits"]["max_runtime_hours"] * 3600,
            protocol["deadline"],
        )
        or protocol["deadline"] != protocol["limits"]["original_deadline"]
        or not protocol["original_granted_at"] <= granted_at <= time.time() < deadline
    ):
        raise ValueError(
            "Original hard deadline and committed continuation grant required"
        )


def _output(root, output):
    if output.parent != root / ".cache" or not output.name.startswith(
        ("selectorremaining-", "selector332-")
    ):
        raise ValueError("Separate counted continuation output namespace required")


def freeze(root, protocol_path, protocol_sha256, output, granted_at, deadline):
    root, output = root.resolve(), output.resolve()
    _output(root, output)
    raw = protocol_path.read_bytes()
    if audit.digest(raw) != protocol_sha256:
        raise ValueError("Changed public protocol bytes")
    protocol = audit.read_json(raw)
    validate_protocol(protocol)
    _clock(protocol, granted_at, deadline)
    inputs = verify_inputs(root, protocol)
    prior = verify_prior(root, protocol)
    code, runtime, used = consumers(root), runtime_snapshot(), budget(root)
    output = audit.ignored_output(root, output)
    for name, entry in code.items():
        destination = audit.inside(output / "consumer", name)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as handle:
            handle.write(audit.sealed_bytes(root, entry))
    with (output / "protocol.json").open("xb") as handle:
        handle.write(raw)
    value = {
        "schema_version": 1,
        "protocol_sha256": protocol_sha256,
        "consumer_files": code,
        "runtime": runtime,
        "inputs": inputs,
        "prior": prior,
        "original_granted_at": protocol["original_granted_at"],
        "continuation_granted_at": granted_at,
        "deadline": deadline,
        "shared_data": "data/processed",
        "borrowed_input_bytes": sum(entry["bytes"] for entry in inputs.values()),
        "budget": used,
    }
    if consumers(root) != code or protocol_path.read_bytes() != raw:
        raise ValueError("Executable/protocol bytes changed during freeze")
    if (
        verify_inputs(root, protocol) != inputs
        or verify_prior(root, protocol) != prior
        or runtime_snapshot() != runtime
    ):
        raise ValueError(
            "Inputs, predecessor evidence or runtime changed during freeze"
        )
    _clock(protocol, granted_at, deadline)
    budget(root)
    publish(output / "experiment.json", value)
    return {"experiment_sha256": audit.file_hash(output / "experiment.json")}


def load(root, output, expected):
    root, output = root.resolve(), output.resolve()
    _output(root, output)
    if audit.file_hash(output / "experiment.json") != expected:
        raise ValueError("Changed continuation experiment receipt")
    experiment = audit.read_json((output / "experiment.json").read_bytes())
    raw = (output / "protocol.json").read_bytes()
    if audit.digest(raw) != experiment["protocol_sha256"]:
        raise ValueError("Changed frozen continuation protocol")
    protocol = audit.read_json(raw)
    validate_protocol(protocol)
    _clock(protocol, experiment["continuation_granted_at"], experiment["deadline"])
    if experiment.get("original_granted_at") != protocol["original_granted_at"]:
        raise ValueError("Changed original predecessor grant")
    current = consumers(root)
    if {name: entry["sha256"] for name, entry in current.items()} != {
        name: entry["sha256"] for name, entry in experiment["consumer_files"].items()
    }:
        raise ValueError("Continuation executable source bytes changed")
    for name, entry in experiment["consumer_files"].items():
        audit.sealed_path(root, entry)
        if audit.file_hash(audit.inside(output / "consumer", name)) != entry["sha256"]:
            raise ValueError("Frozen continuation consumer copy changed")
    if runtime_snapshot() != experiment["runtime"]:
        raise ValueError("Continuation runtime changed")
    if verify_inputs(root, protocol) != experiment["inputs"]:
        raise ValueError("Borrowed continuation inputs changed")
    if verify_prior(root, protocol) != experiment["prior"]:
        raise ValueError("Predecessor evidence changed after continuation freeze")
    budget(root)
    return experiment, protocol


def evaluate(root, output, expected, public_seal_sha256):
    from . import config
    from .jobs import run_local_job
    from .storage import Store

    root, output = root.resolve(), output.resolve()
    _output(root, output)
    if (
        (output / "evaluate-attempt.json").exists()
        or (output / "familiar-opened.json").exists()
        or (output / "familiar.json").exists()
        or (output / "attempts").exists()
        or list(output.glob("familiar-selected-*.json"))
    ):
        raise ValueError(
            "Continuation scientific attempt already started; never repeat"
        )
    experiment, protocol = load(root, output, expected)
    seal_path = output / "public-seal.json"
    if audit.file_hash(seal_path) != public_seal_sha256:
        raise ValueError("Exact externally timestamped continuation seal required")
    public_seal = audit.read_json(seal_path.read_bytes())
    if (
        public_seal.get("experiment_sha256") != expected
        or public_seal.get("protocol_sha256") != experiment["protocol_sha256"]
        or not public_seal.get("comment", "").startswith(
            "https://github.com/Ken0u/badminton-match-analyzer/issues/332#issuecomment-"
        )
    ):
        raise ValueError("Missing bound owning-issue continuation commitment")
    shared = root / "data/processed"
    if (
        config.ROOT != root
        or config.DATA.resolve() != shared
        or config.WEIGHTS.resolve() != root / "models/weights"
        or not (shared / "catalog.sqlite3").is_file()
    ):
        raise ValueError("Pin original root, shared Store and weights before imports")
    attempt = output / "attempts" / uuid4().hex
    publish(
        output / "evaluate-attempt.json",
        {
            "experiment_sha256": expected,
            "attempt": attempt.relative_to(output).as_posix(),
            "public_seal_sha256": public_seal_sha256,
        },
    )
    attempt.mkdir(parents=True)
    started = time.perf_counter()

    def task(job_id, progress):
        process = psutil.Process()
        publish(
            attempt / "admission.json",
            {
                "job_id": job_id,
                "stage": "familiar-continuation",
                "experiment_sha256": expected,
                "process": {
                    "pid": process.pid,
                    "creation_time": process.create_time(),
                    "cwd": process.cwd(),
                    "command": list(sys.argv),
                },
            },
        )

        def bounded_progress(value):
            _clock(
                protocol, experiment["continuation_granted_at"], experiment["deadline"]
            )
            budget(root)
            verify_inputs(root, protocol)
            progress(value)

        bounded_progress(0)
        previous = audit.inside(root, protocol["predecessor_root"])
        fits, public = predecessor.sealed_fits(
            previous,
            protocol["predecessor_experiment_sha256"],
            protocol["predecessor_fit_public_seal_sha256"],
        )
        result = predecessor.familiar_diagnostic(
            root,
            output,
            expected,
            fits,
            public,
            protocol,
            bounded_progress,
            public_seal_sha256=protocol["predecessor_fit_public_seal_sha256"],
            fit_output=previous,
            fit_experiment_sha256=protocol["predecessor_experiment_sha256"],
        )
        if (
            result.get("familiar_sha256") != audit.file_hash(output / "familiar.json")
            or result.get("cases") != protocol["familiar"]["cases"]
            or result.get("unknown") != protocol["familiar"]["truth_states"]["unknown"]
        ):
            raise ValueError("Incomplete continuation result or denominator")
        load(root, output, expected)
        publish(
            attempt / "cost.json",
            {
                "elapsed_s": time.perf_counter() - started,
                "neural_model_calls": 0,
                "generated_test_rows_parsed": False,
            },
        )
        return result

    try:
        result = run_local_job(Store(shared), "feature-preparation", None, task)
    except BaseException as exc:
        publish(
            attempt / "terminal.json",
            {"status": "failed", "error_type": type(exc).__name__, "error": str(exc)},
        )
        raise
    publish(attempt / "terminal.json", {"status": "completed", "result": result})
    return {"result": result, "attempt": attempt.relative_to(output).as_posix()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("freeze", "evaluate"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--protocol-sha256")
    parser.add_argument("--granted-at", type=float)
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--experiment-sha256")
    parser.add_argument("--public-seal-sha256")
    args = parser.parse_args(argv)
    root, output = args.root.resolve(), args.output.resolve()
    if args.stage == "freeze":
        result = freeze(
            root,
            args.protocol,
            args.protocol_sha256,
            output,
            args.granted_at,
            args.deadline,
        )
    else:
        result = evaluate(root, output, args.experiment_sha256, args.public_seal_sha256)
    print(json.dumps(result, allow_nan=False))
    return 0
