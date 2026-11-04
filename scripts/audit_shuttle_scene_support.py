"""Census sealed scene JSON without images, models, Store or assessor execution."""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from badminton import shuttle_scene_support as support


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("root", "protocol", "bindings", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args(argv)
    source = Path(__file__).resolve().parents[1]
    protocol_raw, bindings_raw = args.protocol.read_bytes(), args.bindings.read_bytes()
    support.require(
        max(len(protocol_raw), len(bindings_raw)) <= support.MAX_INPUT_BYTES,
        "Oversized protocol/bindings",
    )
    protocol, bindings = support.decode(protocol_raw), support.decode(bindings_raw)
    support.require(
        protocol["schema_version"] == 1
        and protocol["task"] == 376
        and protocol["eligibility"] == support.ELIGIBILITY,
        "Wrong scene-support protocol",
    )
    support.require(
        protocol["limits"]["image_bytes"]
        == protocol["limits"]["assessor_sessions"]
        == 0,
        "No scientific transfer authority",
    )
    support.require(
        type(protocol["limits"]["max_output_bytes"]) is int
        and 0 < protocol["limits"]["max_output_bytes"] <= 1024**3,
        "Invalid output limit",
    )
    support.verify_consumers(source, protocol)
    support.verify_public_inventory(protocol, bindings)
    output = args.output.absolute()
    support.require(
        output.is_relative_to(args.root.absolute()), "Output escapes namespace"
    )
    output = support.preparation.safe_path(
        args.root.absolute(),
        output.relative_to(args.root.absolute()).as_posix(),
        must_exist=False,
    )
    support.require(not output.exists(), "Output must be a new private directory")
    for namespace in bindings["roots"].values():
        protected = args.root.absolute() / namespace
        support.require(
            not output.is_relative_to(protected)
            and not protected.is_relative_to(output),
            "Output intersects preserved evidence",
        )
    reader = support.EvidenceReader(args.root, bindings, protocol["inventory_sha256"])
    public, private = support.audit_bound(reader, protocol)
    public["protocol_sha256"] = support.digest(protocol_raw)
    payloads = {
        "aggregate.json": support.encode(public),
        "private-ledger.json": support.encode(private),
    }
    receipt = {
        "schema_version": 1,
        "protocol_sha256": support.digest(protocol_raw),
        "inventory_sha256": protocol["inventory_sha256"],
        "outputs": {k: support.digest(v) for k, v in payloads.items()},
        "consumer_sha256": protocol["consumer_sha256"],
        "completed": True,
        "image_bytes_read": 0,
        "source_judgments_created": 0,
    }
    payloads["completion.json"] = support.encode(receipt)
    support.require(
        sum(map(len, payloads.values())) <= protocol["limits"]["max_output_bytes"],
        "Census output budget exceeded",
    )

    def stable():
        support.verify_consumers(source, protocol)
        support.require(
            args.protocol.read_bytes() == protocol_raw
            and args.bindings.read_bytes() == bindings_raw,
            "Protocol or bindings changed during census",
        )
        reader.verify_unchanged()

    stable()
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        if name == "completion.json":
            stable()
        with (output / name).open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    print(
        json.dumps(
            {
                "completed": True,
                "protocol_sha256": public["protocol_sha256"],
                "denominators": public["denominators"],
                "views": public["views"],
                "eligibility": public["eligibility"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
