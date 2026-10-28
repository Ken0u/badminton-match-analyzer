"""Audit frozen context metadata without model, media, labels or Store access."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from badminton import shuttle_context_audit as audit


def verify_consumers(protocol):
    expected = protocol.get("consumer_file_sha256", {})
    if set(expected) != set(audit.CONSUMER_FILES):
        raise ValueError("Archived consumer membership changed")
    source = Path(__file__).resolve().parents[1]
    for relative, digest in expected.items():
        if audit.checksum((source / relative).read_bytes()) != digest:
            raise ValueError("Archived consumer source changed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists() or args.output.is_symlink():
        parser.error("Output must be a new private directory")
    protocol_raw = args.protocol.read_bytes()
    bindings_raw = args.bindings.read_bytes()
    if max(len(protocol_raw), len(bindings_raw)) > audit.MAX_JSON_BYTES:
        parser.error("Protocol or bindings exceed the JSON limit")
    protocol = audit.decode(protocol_raw)
    bindings = audit.decode(bindings_raw)
    implementation = {
        Path(audit.__file__): Path(audit.__file__).read_bytes(),
        Path(__file__): Path(__file__).read_bytes(),
    }
    verify_consumers(protocol)
    result, reader = audit.audit_metadata(protocol, bindings, args.root)
    result["protocol_sha256"] = audit.checksum(protocol_raw)
    result["consumer_sha256"] = audit.checksum(Path(audit.__file__).read_bytes())
    result["cli_sha256"] = audit.checksum(Path(__file__).read_bytes())
    public = {k: v for k, v in result.items() if k != "methods"}
    data = {
        "private-diagnostics.json": audit.encode(result),
        "aggregate.json": audit.encode(public),
    }
    if sum(map(len, data.values())) > min(
        protocol["limits"]["max_output_bytes"], 512 * 1024 * 1024
    ):
        raise ValueError("Metadata audit output exceeds its frozen limit")
    verify_consumers(protocol)
    if any(path.read_bytes() != raw for path, raw in implementation.items()):
        raise ValueError("Metadata audit implementation changed during audit")
    if (
        args.protocol.read_bytes() != protocol_raw
        or args.bindings.read_bytes() != bindings_raw
    ):
        raise ValueError("Protocol or input bindings changed during audit")
    reader.verify_unchanged()
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in data.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    receipt = {
        "schema_version": 1,
        "protocol_sha256": result["protocol_sha256"],
        "outputs": {name: audit.checksum(raw) for name, raw in data.items()},
        "consumer_sha256": result["consumer_sha256"],
        "cli_sha256": result["cli_sha256"],
        "completed": True,
    }
    with (output / "completion.json").open("xb") as stream:
        stream.write(audit.encode(receipt))
    # No raw case/source/view identifiers, local paths or original labels in stdout.
    print(
        json.dumps(
            {
                "completed": True,
                "protocol_sha256": result["protocol_sha256"],
                "methods": {
                    name: {k: value for k, value in summary.items() if k != "sources"}
                    for name, summary in result["aggregate"].items()
                },
                "eligibility": result["eligibility"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
