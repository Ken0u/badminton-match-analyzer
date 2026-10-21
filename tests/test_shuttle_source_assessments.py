"""Generated source-only provenance and adjudication tests; no real labels/media."""

import copy
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest
from badminton import shuttle_source_assessments as assessments

PROJECT = Path(__file__).resolve().parents[1]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else assessments.encoded(value))
    return assessments.file_hash(path)


def png(width=16, height=8):
    def chunk(name, value):
        return (
            struct.pack(">I", len(value))
            + name
            + value
            + struct.pack(">I", zlib.crc32(name + value))
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00" * width * 3) * height))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    base = tmp_path_factory.mktemp("source-only-generated")
    root = base / "packet"
    protocol = assessments.read_json(
        PROJECT / "data/manifests/shuttle_source_assessment_protocol_v1.json"
    )
    declaration = {"schema_version": 1, "sources": []}
    sources = []
    for sid, category in (
        ("generated_single", "singles"),
        ("generated_double", "doubles"),
    ):
        folder = root / "sources" / sid
        raw = ("generated source bytes " + sid).encode()
        source_sha = write(folder / "source.mp4", raw)
        metadata = {"id": sid}
        write(folder / "returned-metadata.json", metadata)
        write(
            folder / "source-seal.json",
            {"sha256": source_sha, "bytes": len(raw), "metadata": metadata},
        )
        declaration["sources"].append(
            {
                "id": sid,
                "category": category,
                "metadata_selected_bytes": len(raw),
                "eligibility": assessments.ELIGIBILITY,
            }
        )
        clock = {
            "schema_version": 1,
            "complete": True,
            "frame_count": 1024,
            "source_sha256": source_sha,
            "origin_s": 0,
            "issues": [],
            "frames": [
                {
                    "frame": i,
                    "pts": i * 40 + i // 7,
                    "time_base": "1/1000",
                    "time_s": (i * 40 + i // 7) / 1000,
                    "rotation": 0,
                    "source_size": [16, 8],
                    "display_size": [16, 8],
                    "corrupt": False,
                    "orientation_error": None,
                }
                for i in range(1024)
            ],
        }
        clock_sha = write(folder / "clock.json", clock)
        cases = []
        selected = set()
        for i in range(64):
            center = i * 1023 // 63
            context = []
            for offset in [-2, -1, 0, 1, 2]:
                frame = max(0, min(1023, center + offset))
                selected.add(frame)
                context.append(
                    {
                        "offset": offset,
                        "frame": frame,
                        "clamped": frame != center + offset,
                    }
                )
            cases.append({"case_id": i, "center_frame": center, "context": context})
        images = {}
        for frame in sorted(selected):
            rel = f"images/{sid}/{frame:09d}.png"
            raw_png = png()
            sha = write(root / rel, raw_png)
            images[str(frame)] = {
                **clock["frames"][frame],
                "available": True,
                "image": {"path": rel, "bytes": len(raw_png), "sha256": sha},
            }
        packet = {
            "schema_version": 1,
            "source_id": sid,
            "source_sha256": source_sha,
            "clock_sha256": clock_sha,
            "case_count": 64,
            "requested_context_memberships": 320,
            "cases": cases,
            "images": images,
            "eligibility": assessments.ELIGIBILITY,
        }
        sources.append(
            {
                "source_id": sid,
                "source_sha256": source_sha,
                "clock_sha256": clock_sha,
                "case_count": 64,
                "requested_context_memberships": 320,
                "unique_images": 316,
                "native_frame_count": 1024,
                "display_size": [16, 8],
                "category_metadata_assertion": category,
                "packet": packet,
            }
        )
    declaration_sha = write(
        root / "consumer/data/manifests/shuttle_review_sources_v1.json", declaration
    )
    packet_protocol_sha = write(
        root / "consumer/data/manifests/shuttle_review_packet_protocol_v1.json",
        {"schema_version": 1, "eligibility": assessments.ELIGIBILITY},
    )
    consumer_sha = write(
        root / "consumer/generated-consumer.py", b"# generated pure consumer\n"
    )
    context_sha = write(
        root / "context.json",
        {
            "schema_version": 1,
            "runtime": {"generated": True},
            "consumers": {
                "data/manifests/shuttle_review_sources_v1.json": declaration_sha,
                "data/manifests/shuttle_review_packet_protocol_v1.json": packet_protocol_sha,
                "generated-consumer.py": consumer_sha,
            },
        },
    )
    for source in sources:
        packet = source.pop("packet")
        packet["context_sha256"] = context_sha
        folder = root / "sources" / source["source_id"]
        packet_sha = write(folder / "packet.json", packet)
        template = {
            "schema_version": 1,
            "source_id": source["source_id"],
            "source_sha256": source["source_sha256"],
            "clock_sha256": source["clock_sha256"],
            "packet_sha256": packet_sha,
            "eligibility": assessments.ELIGIBILITY,
            "cases": [
                {
                    "case_id": c["case_id"],
                    "center_frame": c["center_frame"],
                    "difficulty": "unknown",
                    "reviewed": False,
                    "scene": "unknown",
                    "visibility": "unknown",
                    "x": None,
                    "y": None,
                }
                for c in packet["cases"]
            ],
        }
        source["packet_sha256"] = packet_sha
        source["unknown_template_sha256"] = write(
            folder / "review-template.json", template
        )
    protocol.update(
        {
            "sources": sources,
            "packet_context_sha256": context_sha,
            "source_declaration_sha256": declaration_sha,
            "source_packet_protocol_sha256": packet_protocol_sha,
        }
    )
    path = base / "protocol.json"
    sha = write(path, protocol)
    inputs = assessments.load_inputs(root, path, sha)
    inputs_path = base / "inputs.json"
    write(inputs_path, inputs)
    return {
        "base": base,
        "root": root,
        "protocol": protocol,
        "protocol_path": path,
        "sha": sha,
        "inputs": inputs,
        "inputs_path": inputs_path,
    }


def row_for(case, visibility="unknown"):
    center = next(m["identity"] for m in case["context"] if m["offset"] == 0)
    return {
        "key": case["key"],
        "source_id": case["source_id"],
        "case_id": case["case_id"],
        "center_frame": case["center_frame"],
        "visibility": visibility,
        "x": 7 if visibility == "visible_localizable" else None,
        "y": 4 if visibility == "visible_localizable" else None,
        "uncertainty_radius": 2 if visibility == "visible_localizable" else None,
        "scene": "unknown",
        "difficulty": ["unresolved"],
        "reason": "Generated fixture observation, no real inspection claimed.",
        "negative_evidence": "Generated affirmative absence observation."
        if visibility == "not_visible"
        else None,
        "inspected_frames": [
            {"frame": case["center_frame"], "image_sha256": center["image"]["sha256"]}
        ]
        if center["available"]
        else [],
    }


def document(generated, assessor="generated A"):
    return {
        "schema_version": 1,
        "role": "source_only_assessment",
        "assessor_id": assessor,
        "session_id": "fixture session " + assessor,
        "protocol_sha256": generated["sha"],
        "inputs_sha256": assessments.digest(assessments.encoded(generated["inputs"])),
        "eligibility": dict(assessments.ELIGIBILITY),
        "cases": [row_for(case) for case in generated["inputs"]["cases"]],
    }


def validate(generated, doc):
    return assessments.validate_assessment(
        doc,
        generated["inputs"],
        generated["protocol"],
        assessments.digest(assessments.encoded(generated["inputs"])),
    )


def documents(generated, folder, a=None, b=None, adjudicated=None):
    a = document(generated) if a is None else a
    b = document(generated, "generated B") if b is None else b
    a_path, b_path, j_path = [folder / name for name in ("a.json", "b.json", "j.json")]
    # Different whitespace is intentionally retained as part of the original seal.
    write(a_path, json.dumps(a, ensure_ascii=False).encode() + b"\n\n")
    write(b_path, b)
    adjudication = {
        "schema_version": 1,
        "role": "source_only_adjudication",
        "adjudicator_id": "generated adjudicator",
        "session_id": "fixture distinct adjudication session",
        "protocol_sha256": generated["sha"],
        "inputs_sha256": a["inputs_sha256"],
        "eligibility": dict(assessments.ELIGIBILITY),
        "assessment_sha256": [
            assessments.file_hash(a_path),
            assessments.file_hash(b_path),
        ],
        "cases": [] if adjudicated is None else adjudicated,
    }
    write(j_path, adjudication)
    return a_path, b_path, j_path


def freeze_args(generated, paths, output):
    return (
        generated["root"],
        generated["protocol_path"],
        generated["sha"],
        generated["inputs_path"],
        *paths,
        output,
    )


def ignored_output(tmp_path):
    # Exercise real Git ignore checking in a disposable generated repository.
    subprocess.run(
        ["git", "init", "--quiet", str(tmp_path)], check=True, capture_output=True
    )
    write(tmp_path / ".gitignore", b"/ignored/\n")
    return tmp_path / "ignored" / "freeze"


def test_complete_deterministic_index_and_clamped_memberships(generated):
    inputs = assessments.load_inputs(
        generated["root"], generated["protocol_path"], generated["sha"]
    )
    assert inputs == generated["inputs"]
    assert len(inputs["cases"]) == 128
    assert sum(len(c["context"]) for c in inputs["cases"]) == 640
    assert (
        len(
            {
                (c["source_id"], m["frame"])
                for c in inputs["cases"]
                for m in c["context"]
            }
        )
        == 632
    )
    assert [m["frame"] for m in inputs["cases"][0]["context"]] == [0, 0, 0, 1, 2]
    assert [m["clamped"] for m in inputs["cases"][0]["context"]] == [
        True,
        True,
        False,
        False,
        False,
    ]
    assert inputs["sources"] == generated["protocol"]["sources"]
    assert assessments.encoded(inputs) == generated["inputs_path"].read_bytes()


@pytest.mark.parametrize(
    "relative",
    [
        "context.json",
        "consumer/generated-consumer.py",
        "consumer/data/manifests/shuttle_review_sources_v1.json",
        "consumer/data/manifests/shuttle_review_packet_protocol_v1.json",
        "sources/generated_single/source.mp4",
        "sources/generated_single/clock.json",
        "sources/generated_single/packet.json",
        "sources/generated_single/review-template.json",
        "images/generated_single/000000000.png",
    ],
)
def test_tampered_input_bytes_rejected(generated, relative):
    path = generated["root"] / relative
    raw = path.read_bytes()
    try:
        path.write_bytes(raw + b" ")
        with pytest.raises(ValueError, match="changed"):
            assessments.load_inputs(
                generated["root"], generated["protocol_path"], generated["sha"]
            )
    finally:
        path.write_bytes(raw)


def test_external_protocol_seal_is_mandatory(generated):
    with pytest.raises(ValueError, match="SHA256 changed"):
        assessments.load_inputs(generated["root"], generated["protocol_path"], "0" * 64)


def test_png_native_header_checked_even_with_renewed_byte_seal(generated, tmp_path):
    image_path = generated["root"] / "images/generated_single/000000000.png"
    packet_path = generated["root"] / "sources/generated_single/packet.json"
    template_path = generated["root"] / "sources/generated_single/review-template.json"
    original_image, original_packet = image_path.read_bytes(), packet_path.read_bytes()
    original_template = template_path.read_bytes()
    try:
        altered = png(width=15)
        image_sha = write(image_path, altered)
        packet = assessments._decode_json(original_packet)
        packet["images"]["0"]["image"].update(
            {"sha256": image_sha, "bytes": len(altered)}
        )
        packet_sha = write(packet_path, packet)
        protocol = copy.deepcopy(generated["protocol"])
        protocol["sources"][0]["packet_sha256"] = packet_sha
        template = assessments._decode_json(original_template)
        template["packet_sha256"] = packet_sha
        protocol["sources"][0]["unknown_template_sha256"] = write(
            template_path, template
        )
        path = tmp_path / "renewed-protocol.json"
        sha = write(path, protocol)
        with pytest.raises(ValueError, match="PNG native geometry/header"):
            assessments.load_inputs(generated["root"], path, sha)
    finally:
        image_path.write_bytes(original_image)
        packet_path.write_bytes(original_packet)
        template_path.write_bytes(original_template)


@pytest.mark.parametrize("visibility", assessments.VISIBILITY)
def test_all_visibility_states_retained(generated, visibility):
    doc = document(generated)
    doc["cases"][0] = row_for(generated["inputs"]["cases"][0], visibility)
    assert validate(generated, doc)[doc["cases"][0]["key"]]["visibility"] == visibility


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "foreign", "center", "source", "case_bool"]
)
def test_case_identity_and_complete_membership(generated, change):
    doc = document(generated)
    if change == "missing":
        doc["cases"].pop()
    elif change == "duplicate":
        doc["cases"][-1] = copy.deepcopy(doc["cases"][0])
    elif change == "foreign":
        doc["cases"][0]["key"] = "foreign:00"
    elif change == "center":
        doc["cases"][0]["center_frame"] += 1
    elif change == "source":
        doc["cases"][0]["source_id"] = "foreign"
    else:
        doc["cases"][0]["case_id"] = False
    with pytest.raises(ValueError):
        validate(generated, doc)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("x", -1),
        ("x", 16),
        ("y", 8),
        ("x", True),
        ("y", float("nan")),
        ("x", float("inf")),
        ("uncertainty_radius", 0.99),
        ("uncertainty_radius", 100),
        ("uncertainty_radius", None),
    ],
)
def test_finite_native_coordinates_and_uncertainty(generated, field, value):
    doc = document(generated)
    doc["cases"][0] = row_for(generated["inputs"]["cases"][0], "visible_localizable")
    doc["cases"][0][field] = value
    with pytest.raises(ValueError):
        validate(generated, doc)


@pytest.mark.parametrize(
    "change",
    [
        "unknown_point",
        "unknown_negative",
        "negative_missing",
        "negative_short",
        "missing_center",
        "foreign_context",
        "wrong_png",
        "duplicate_inspection",
        "blank_reason",
        "ordinary_mixed",
        "duplicate_difficulty",
    ],
)
def test_source_observation_and_inspection_contract(generated, change):
    doc = document(generated)
    row = doc["cases"][0]
    if change == "unknown_point":
        row["x"] = 1
    elif change == "unknown_negative":
        row["negative_evidence"] = "Not found is not an affirmative negative."
    elif change.startswith("negative_"):
        row["visibility"] = "not_visible"
        row["negative_evidence"] = None if change == "negative_missing" else "absent"
    elif change == "missing_center":
        row["inspected_frames"] = []
    elif change == "foreign_context":
        row["inspected_frames"][0]["frame"] = 20
    elif change == "wrong_png":
        row["inspected_frames"][0]["image_sha256"] = "0" * 64
    elif change == "duplicate_inspection":
        row["inspected_frames"] *= 2
    elif change == "blank_reason":
        row["reason"] = "  "
    elif change == "ordinary_mixed":
        row["difficulty"] = ["ordinary", "blur"]
    else:
        row["difficulty"] = ["blur", "blur"]
    with pytest.raises(ValueError):
        validate(generated, doc)


def test_unavailable_center_unknown_remains_in_denominator(generated):
    inputs = copy.deepcopy(generated["inputs"])
    case = inputs["cases"][0]
    for m in case["context"]:
        if m["frame"] == 0:
            m["identity"]["available"] = False
            m["identity"]["image"] = None
    doc = document(generated)
    doc["cases"][0]["inspected_frames"] = []
    result = assessments.validate_assessment(
        doc, inputs, generated["protocol"], doc["inputs_sha256"]
    )
    assert len(result) == 128 and result[case["key"]]["visibility"] == "unknown"
    doc["cases"][0]["visibility"] = "not_visible"
    doc["cases"][0]["negative_evidence"] = "Generated affirmative absence."
    with pytest.raises(ValueError, match="Unavailable center"):
        assessments.validate_assessment(
            doc, inputs, generated["protocol"], doc["inputs_sha256"]
        )


@pytest.mark.parametrize("flag", assessments.ELIGIBILITY)
@pytest.mark.parametrize("value", [True, 0, None])
def test_all_four_eligibility_flags_strictly_false(generated, flag, value):
    doc = document(generated)
    doc["eligibility"][flag] = value
    with pytest.raises(ValueError, match="eligibility"):
        validate(generated, doc)


def test_freeze_preserves_originals_disagreements_unknowns_and_agreement(
    generated, tmp_path
):
    a, b = document(generated), document(generated, "generated B")
    a["cases"][0] = row_for(generated["inputs"]["cases"][0], "visible_localizable")
    a["cases"][1] = row_for(generated["inputs"]["cases"][1], "not_visible")
    b["cases"][1] = copy.deepcopy(a["cases"][1])
    adjudicated = [
        row_for(generated["inputs"]["cases"][0]),
        copy.deepcopy(a["cases"][1]),
    ]
    paths = documents(generated, tmp_path / "originals", a, b, adjudicated)
    output = ignored_output(tmp_path)
    before = [p.read_bytes() for p in paths]
    aggregate = assessments.freeze(*freeze_args(generated, paths, output))
    assert aggregate["case_count"] == 128
    assert aggregate["raw_label_disagreements"] == 1
    assert (
        aggregate["required_adjudications"] == aggregate["explicit_adjudications"] == 2
    )
    assert aggregate["resolved_visibility_support"]["unknown"] == 127
    assert aggregate["resolved_visibility_support"]["not_visible"] == 1
    assert aggregate["two_assessor_agreement_only"] == 126
    assert [p.read_bytes() for p in paths] == before
    assert [
        (output / name).read_bytes()
        for name in ("assessor-a.json", "assessor-b.json", "adjudication.json")
    ] == before
    differences = assessments.read_json(output / "raw-differences.json")
    assert differences[0]["fields"] == ["visibility", "x", "y", "uncertainty_radius"]
    assert differences[0]["assessor_a"] == a["cases"][0]
    assert differences[0]["assessor_b"] == b["cases"][0]
    resolved = assessments.read_json(output / "resolved.json")
    assert resolved[2]["basis"] == "two_assessor_agreement"
    assert len(resolved) == 128
    assert not list(output.rglob("*.png")) and not list(output.rglob("clock.json"))
    manifest = assessments.read_json(output / "manifest.json")
    assert manifest["assessment_sha256"] == [
        assessments.digest(raw) for raw in before[:2]
    ]
    assert (
        "consumer/backend/badminton/shuttle_source_assessments.py" in manifest["files"]
    )
    assert (
        assessments.verify_freeze(output, generated["root"], generated["sha"])
        == aggregate
    )
    with pytest.raises(ValueError, match="already exists"):
        assessments.freeze(*freeze_args(generated, paths, output))
    (output / "resolved.json").write_bytes(b"[]\n")
    with pytest.raises(ValueError, match="changed"):
        assessments.verify_freeze(output, generated["root"], generated["sha"])


@pytest.mark.parametrize("kind", ["difference", "agreed_negative"])
def test_required_explicit_adjudication(generated, tmp_path, kind):
    a, b = document(generated), document(generated, "generated B")
    a["cases"][0] = row_for(
        generated["inputs"]["cases"][0],
        "not_visible" if kind == "agreed_negative" else "visible_unlocalizable",
    )
    if kind == "agreed_negative":
        b["cases"][0] = copy.deepcopy(a["cases"][0])
    paths = documents(generated, tmp_path / "originals", a, b)
    output = ignored_output(tmp_path)
    with pytest.raises(ValueError, match="Explicit adjudication required"):
        assessments.freeze(*freeze_args(generated, paths, output))
    assert not output.exists()


@pytest.mark.parametrize("field", assessments.LABEL_FIELDS)
def test_each_raw_label_difference_requires_adjudication(generated, tmp_path, field):
    a, b = document(generated), document(generated, "generated B")
    a["cases"][0] = row_for(generated["inputs"]["cases"][0], "visible_localizable")
    b["cases"][0] = copy.deepcopy(a["cases"][0])
    changes = {
        "visibility": "visible_unlocalizable",
        "x": 8,
        "y": 3,
        "uncertainty_radius": 3,
        "scene": "play_view",
        "difficulty": ["blur"],
    }
    b["cases"][0][field] = changes[field]
    if field == "visibility":
        for coordinate in ("x", "y", "uncertainty_radius"):
            b["cases"][0][coordinate] = None
    paths = documents(generated, tmp_path, a, b)
    with pytest.raises(ValueError, match="Explicit adjudication required"):
        assessments._validated_documents(
            generated["inputs"], generated["protocol"], generated["inputs_path"], *paths
        )


def test_reasons_inspection_scope_and_tag_order_are_not_label_disagreements(
    generated, tmp_path
):
    a, b = document(generated), document(generated, "generated B")
    a["cases"][0]["difficulty"] = ["blur", "small_far"]
    b["cases"][0]["difficulty"] = ["small_far", "blur"]
    b["cases"][0]["reason"] = "A different generated observation."
    identity = generated["inputs"]["cases"][0]["context"][-1]["identity"]
    b["cases"][0]["inspected_frames"].append(
        {"frame": identity["frame"], "image_sha256": identity["image"]["sha256"]}
    )
    paths = documents(generated, tmp_path, a, b)
    result = assessments._validated_documents(
        generated["inputs"], generated["protocol"], generated["inputs_path"], *paths
    )
    assert result[2] == [] and result[-1]["two_assessor_agreement_only"] == 128


@pytest.mark.parametrize(
    "change",
    [
        "assessor_id",
        "assessor_session",
        "adjudicator_session",
        "ordered_seals",
        "original_bytes",
        "blind_bytes",
    ],
)
def test_independent_original_provenance(generated, tmp_path, change):
    a, b = document(generated), document(generated, "generated B")
    if change == "assessor_id":
        b["assessor_id"] = a["assessor_id"]
    if change == "assessor_session":
        b["session_id"] = a["session_id"]
    paths = documents(generated, tmp_path, a, b)
    j = assessments.read_json(paths[2])
    if change == "adjudicator_session":
        j["session_id"] = a["session_id"]
    if change == "ordered_seals":
        j["assessment_sha256"].reverse()
    write(paths[2], j)
    if change == "original_bytes":
        paths[0].write_bytes(paths[0].read_bytes() + b" ")
    inputs_path = generated["inputs_path"]
    if change == "blind_bytes":
        inputs_path = tmp_path / "different-inputs.json"
        write(inputs_path, assessments.encoded(generated["inputs"]) + b" ")
    with pytest.raises(ValueError):
        assessments._validated_documents(
            generated["inputs"], generated["protocol"], inputs_path, *paths
        )


def test_output_must_be_ignored_and_not_overlap_inputs(generated, tmp_path):
    paths = documents(generated, tmp_path / "originals")
    output = ignored_output(tmp_path)
    with pytest.raises(ValueError, match="Git ignored"):
        assessments.freeze(*freeze_args(generated, paths, tmp_path / "public"))
    with pytest.raises(ValueError, match="overlaps"):
        assessments.freeze(
            *freeze_args(generated, paths, generated["root"] / "new-output")
        )
    assert not output.exists()


def test_frozen_extra_file_membership_and_actual_bytes(
    generated, tmp_path, monkeypatch
):
    paths = documents(generated, tmp_path / "originals")
    output = ignored_output(tmp_path)
    assessments.freeze(*freeze_args(generated, paths, output))
    extra = output / "unmanifested.bin"
    extra.write_bytes(b"unmanifested generated evidence")
    with pytest.raises(ValueError, match="Unmanifested"):
        assessments.verify_freeze(output, generated["root"], generated["sha"])
    actual_size = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    monkeypatch.setattr(assessments, "MAX_OUTPUT", actual_size - 1)
    with pytest.raises(ValueError, match="byte budget"):
        assessments.verify_freeze(output, generated["root"], generated["sha"])


def test_frozen_required_consumer_cannot_be_removed(generated, tmp_path):
    paths = documents(generated, tmp_path / "originals")
    output = ignored_output(tmp_path)
    assessments.freeze(*freeze_args(generated, paths, output))
    name = "consumer/scripts/freeze_shuttle_source_assessments.py"
    manifest = assessments.read_json(output / "manifest.json")
    del manifest["files"][name]
    write(output / "manifest.json", manifest)
    (output / name).unlink()
    with pytest.raises(ValueError, match="membership changed"):
        assessments.verify_freeze(output, generated["root"], generated["sha"])


def test_output_budget_rejected_before_publication(generated, tmp_path, monkeypatch):
    paths = documents(generated, tmp_path / "originals")
    output = ignored_output(tmp_path)
    monkeypatch.setattr(assessments, "MAX_OUTPUT", 100)
    with pytest.raises(ValueError, match="byte budget"):
        assessments.freeze(*freeze_args(generated, paths, output))
    assert not output.exists()


def test_strict_json_rejects_duplicate_keys_and_nonfinite_numbers(tmp_path):
    path = tmp_path / "invalid.json"
    for raw in (b'{"key":1,"key":2}', b'{"value":NaN}', b'{"value":Infinity}'):
        write(path, raw)
        with pytest.raises(ValueError):
            assessments.read_json(path)


def test_cli_redacts_errors_and_does_not_import_heavy_runtime(generated, tmp_path):
    env = dict(
        os.environ,
        BADMINTON_ROOT=str(tmp_path / "isolated"),
        BADMINTON_DATA_DIR=str(tmp_path / "isolated-data"),
    )
    env.update(
        dict.fromkeys(
            ("GH_TOKEN", "GITHUB_TOKEN", "AGENT_PROJECT_TOKEN", "OPENAI_API_KEY"),
            "generated-secret-never-print",
        )
    )
    script = PROJECT / "scripts/freeze_shuttle_source_assessments.py"
    command = [
        sys.executable,
        str(script),
        "verify",
        "--packet-root",
        str(generated["root"]),
        "--protocol",
        str(generated["protocol_path"]),
        "--protocol-sha256",
        "0" * 64,
    ]
    result = subprocess.run(
        command, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 1
    assert json.loads(result.stderr) == {"error": "ValueError"}
    assert not result.stdout and "generated-secret" not in result.stderr
    # Run the CLI in-process in a fresh interpreter and assert credential isolation/import bounds.
    driver = """import importlib.util, os, sys
spec=importlib.util.spec_from_file_location('source_cli',sys.argv[1])
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
assert module.main(sys.argv[2:]) == 0
assert not any(key in os.environ for key in ('GH_TOKEN','GITHUB_TOKEN','AGENT_PROJECT_TOKEN','OPENAI_API_KEY'))
assert not {'torch','torchvision','av','badminton.config','badminton.storage'} & sys.modules.keys()
assert os.environ['BADMINTON_DATA_DIR'].endswith('.cache'+os.sep+'shuttle-assessment-cli-isolated')
"""
    command[-1] = generated["sha"]
    result = subprocess.run(
        [sys.executable, "-c", driver, *command[1:]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["case_count"] == 128
