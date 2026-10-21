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
            (
                "GH_TOKEN",
                "GITHUB_TOKEN",
                "AGENT_PROJECT_TOKEN",
                "OPENAI_API_KEY",
                "CODEX_API_KEY",
            ),
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
assert not any(key in os.environ for key in ('GH_TOKEN','GITHUB_TOKEN','AGENT_PROJECT_TOKEN','OPENAI_API_KEY','CODEX_API_KEY'))
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


@pytest.fixture(scope="module")
def generated_v2(generated):
    """Reuse generated media identities, binding a separate prospective protocol."""
    protocol = assessments.read_json(
        PROJECT / "data/manifests/shuttle_source_assessment_protocol_v2.json"
    )
    for key in (
        "sources",
        "packet_context_sha256",
        "source_declaration_sha256",
        "source_packet_protocol_sha256",
    ):
        protocol[key] = copy.deepcopy(generated["protocol"][key])
    path = generated["base"] / "protocol-v2.json"
    sha = write(path, protocol)
    inputs = assessments.load_inputs(generated["root"], path, sha)
    inputs_path = generated["base"] / "inputs-v2.json"
    write(inputs_path, inputs)
    return {
        **generated,
        "protocol": protocol,
        "protocol_path": path,
        "sha": sha,
        "inputs": inputs,
        "inputs_path": inputs_path,
    }


def stream_documents(generated, folder, a=None, b=None, adjudicated=None):
    """Generate many synthetic sessions; no real inspection or independence claimed."""
    paths = [folder / name for name in assessments.ORIGINAL_NAMES]
    for sid, path, cases in zip(
        ("a", "b", "adjudication"),
        paths,
        (
            document(generated)["cases"] if a is None else a,
            document(generated)["cases"] if b is None else b,
            [] if adjudicated is None else adjudicated,
        ),
    ):
        index = {
            "schema_version": 2,
            "role": "source_only_adjudication_stream"
            if sid == "adjudication"
            else "source_only_assessment_stream",
            "stream_id": sid,
            "protocol_sha256": generated["sha"],
            "inputs_sha256": assessments.file_hash(generated["inputs_path"]),
            "eligibility": dict(assessments.ELIGIBILITY),
            "segments": [],
        }
        if sid == "adjudication":
            index["assessment_sha256"] = [assessments.file_hash(p) for p in paths[:2]]
        for number, offset in enumerate(range(0, len(cases), 4)):
            segment = document(generated, sid)
            segment["cases"] = copy.deepcopy(cases[offset : offset + 4])
            segment["session_id"] = f"generated {sid} session {number}"
            if sid == "adjudication":
                del segment["assessor_id"]
                segment["role"] = "source_only_adjudication"
                segment["adjudicator_id"] = sid
                segment["assessment_sha256"] = index["assessment_sha256"]
            name = f"segments/{sid}/{number:03d}.json"
            # Deliberate whitespace proves exact original segment bytes survive freezing.
            raw = json.dumps(segment, ensure_ascii=False).encode() + b"\n\n"
            sha = write(folder / name, raw)
            index["segments"].append(
                {
                    "path": name,
                    "sha256": sha,
                    "bytes": len(raw),
                    "session_id": segment["session_id"],
                    "case_keys": [row["key"] for row in segment["cases"]],
                }
            )
        write(path, index)
    return paths


def validated_streams(generated, paths):
    return assessments._validated_documents(
        generated["inputs"], generated["protocol"], generated["inputs_path"], *paths
    )


def edit_segment(index_path, number, edit):
    index = assessments.read_json(index_path)
    entry = index["segments"][number]
    path = index_path.parent / entry["path"]
    segment = assessments.read_json(path)
    edit(segment)
    entry["sha256"] = write(path, segment)
    entry["bytes"] = path.stat().st_size
    write(index_path, index)
    return segment


def test_v2_freeze_retains_every_original_and_actual_case_session(
    generated_v2, tmp_path
):
    a, b = document(generated_v2)["cases"], document(generated_v2)["cases"]
    a[0] = row_for(generated_v2["inputs"]["cases"][0], "visible_localizable")
    a[1] = row_for(generated_v2["inputs"]["cases"][1], "not_visible")
    b[1] = copy.deepcopy(a[1])
    adjudicated = [row_for(generated_v2["inputs"]["cases"][0]), copy.deepcopy(a[1])]
    paths = stream_documents(generated_v2, tmp_path / "originals", a, b, adjudicated)
    originals = {
        p.relative_to(paths[0].parent).as_posix(): p.read_bytes()
        for p in paths[0].parent.rglob("*")
        if p.is_file()
    }
    output = ignored_output(tmp_path)
    aggregate = assessments.freeze(*freeze_args(generated_v2, paths, output))
    assert aggregate["raw_label_disagreements"] == 1
    assert (
        aggregate["explicit_adjudications"] == aggregate["required_adjudications"] == 2
    )
    assert aggregate["resolved_visibility_support"]["unknown"] == 127
    assert aggregate["resolved_visibility_support"]["not_visible"] == 1
    assert aggregate["two_assessor_agreement_only"] == 126
    assert all((output / name).read_bytes() == raw for name, raw in originals.items())
    resolved = assessments.read_json(output / "resolved.json")
    assert resolved[0]["inspection_sessions"] == {
        "assessor_a": "generated a session 0",
        "assessor_b": "generated b session 0",
        "adjudication": "generated adjudication session 0",
    }
    assert resolved[4]["inspection_sessions"] == {
        "assessor_a": "generated a session 1",
        "assessor_b": "generated b session 1",
    }
    differences = assessments.read_json(output / "raw-differences.json")
    assert differences[0]["inspection_sessions"] == resolved[0]["inspection_sessions"]
    manifest = assessments.read_json(output / "manifest.json")
    assert (
        len([name for name in manifest["files"] if name.startswith("segments/")]) == 65
    )
    assert all("session" not in key for key in aggregate)
    assert (
        assessments.verify_freeze(output, generated_v2["root"], generated_v2["sha"])
        == aggregate
    )
    # Renewing a copied metadata seal cannot disguise divergence from packet originals.
    name = "packet/sources/generated_single/returned-metadata.json"
    original_metadata = (output / name).read_bytes()
    original_manifest = (output / "manifest.json").read_bytes()
    altered_metadata = original_metadata + b" "
    write(output / name, altered_metadata)
    manifest["files"][name] = {
        "sha256": assessments.digest(altered_metadata),
        "bytes": len(altered_metadata),
    }
    write(output / "manifest.json", manifest)
    with pytest.raises(ValueError, match="Frozen packet original changed"):
        assessments.verify_freeze(output, generated_v2["root"], generated_v2["sha"])
    write(output / name, original_metadata)
    write(output / "manifest.json", original_manifest)
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "scripts/freeze_shuttle_source_assessments.py"),
            "verify-freeze",
            "--packet-root",
            str(generated_v2["root"]),
            "--protocol-sha256",
            generated_v2["sha"],
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == aggregate
    assert "generated a session" not in result.stdout
    assert generated_v2["inputs"]["cases"][0]["key"] not in result.stdout
    extra = output / "segments/a/extra.json"
    extra.write_bytes(b"{}")
    with pytest.raises(ValueError, match="Unmanifested"):
        assessments.verify_freeze(output, generated_v2["root"], generated_v2["sha"])


def test_v2_empty_adjudication_only_for_no_required_cases(generated_v2, tmp_path):
    paths = stream_documents(generated_v2, tmp_path / "originals")
    result = validated_streams(generated_v2, paths)
    assert result[-1]["explicit_adjudications"] == 0
    assert result[-1]["resolved_visibility_support"]["unknown"] == 128
    assert result[-1]["two_assessor_agreement_only"] == 128
    assert len(result[0]) == 67  # Three indexes plus 32 segments per assessor.


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "missing_entry",
        "missing_file",
        "duplicate_path",
        "duplicate_case",
        "case_keys_order",
        "foreign_case",
        "changed_bytes",
        "wrong_size",
        "empty_segment",
        "too_many_cases",
        "unsafe_path",
        "other_stream_path",
        "noncanonical_path",
        "extra_adjudication_file",
        "missing_case",
        "extra_segment_field",
    ],
)
def test_v2_segment_inventory_is_exact(generated_v2, tmp_path, change):
    paths = stream_documents(generated_v2, tmp_path / "originals")
    index = assessments.read_json(paths[0])
    entry = index["segments"][0]
    segment_path = paths[0].parent / entry["path"]
    if change == "extra":
        write(segment_path.parent / "extra.json", b"{}")
    elif change == "missing_entry":
        index["segments"].pop()
    elif change == "missing_file":
        segment_path.unlink()
    elif change == "duplicate_path":
        index["segments"].append(copy.deepcopy(entry))
    elif change == "duplicate_case":
        previous = assessments.read_json(segment_path)["cases"][0]
        edit_segment(paths[0], 1, lambda d: d["cases"].__setitem__(0, previous))
        index = assessments.read_json(paths[0])
        index["segments"][1]["case_keys"][0] = previous["key"]
    elif change == "case_keys_order":
        entry["case_keys"].reverse()
    elif change == "foreign_case":
        edit_segment(paths[0], 0, lambda d: d["cases"][0].update(key="foreign:00"))
        index = assessments.read_json(paths[0])
    elif change == "changed_bytes":
        segment_path.write_bytes(segment_path.read_bytes() + b" ")
    elif change == "wrong_size":
        entry["bytes"] += 1
    elif change == "empty_segment":
        edit_segment(paths[0], 0, lambda d: d.update(cases=[]))
        index = assessments.read_json(paths[0])
        index["segments"][0]["case_keys"] = []
    elif change == "too_many_cases":
        row = row_for(generated_v2["inputs"]["cases"][4])
        edit_segment(paths[0], 0, lambda d: d["cases"].append(row))
        index = assessments.read_json(paths[0])
        index["segments"][0]["case_keys"].append(row["key"])
    elif change == "unsafe_path":
        entry["path"] = "segments/a/../../../outside.json"
    elif change == "other_stream_path":
        entry["path"] = "segments/b/000.json"
    elif change == "noncanonical_path":
        entry["path"] = "segments/a//000.json"
    elif change == "extra_adjudication_file":
        write(paths[0].parent / "segments/adjudication/extra.json", b"{}")
    elif change == "missing_case":
        removed = index["segments"].pop()
        (paths[0].parent / removed["path"]).unlink()
    else:
        edit_segment(paths[0], 0, lambda d: d.update(unexpected=True))
        index = assessments.read_json(paths[0])
    write(paths[0], index)
    with pytest.raises(ValueError):
        validated_streams(generated_v2, paths)


@pytest.mark.parametrize("scope", ["within_a", "a_b", "a_j", "b_j", "within_j"])
def test_v2_sessions_globally_disjoint(generated_v2, tmp_path, scope):
    # Five optional adjudications establish that additional inspected cases remain allowed.
    paths = stream_documents(
        generated_v2,
        tmp_path / "originals",
        adjudicated=document(generated_v2)["cases"][:5],
    )
    origin, target, number = {
        "within_a": (0, 0, 1),
        "a_b": (0, 1, 0),
        "a_j": (0, 2, 0),
        "b_j": (1, 2, 0),
        "within_j": (2, 2, 1),
    }[scope]
    session = assessments.read_json(paths[origin])["segments"][0]["session_id"]
    edit_segment(paths[target], number, lambda d: d.update(session_id=session))
    index = assessments.read_json(paths[target])
    index["segments"][number]["session_id"] = session
    write(paths[target], index)
    with pytest.raises(ValueError, match="globally distinct"):
        validated_streams(generated_v2, paths)


@pytest.mark.parametrize("field", [*assessments.LABEL_FIELDS, "agreed_negative"])
def test_v2_every_raw_difference_and_agreed_negative_requires_source_adjudication(
    generated_v2, tmp_path, field
):
    a, b = document(generated_v2)["cases"], document(generated_v2)["cases"]
    a[0] = row_for(generated_v2["inputs"]["cases"][0], "visible_localizable")
    b[0] = copy.deepcopy(a[0])
    if field == "agreed_negative":
        a[0] = row_for(generated_v2["inputs"]["cases"][0], "not_visible")
        b[0] = copy.deepcopy(a[0])
    else:
        b[0][field] = {
            "visibility": "visible_unlocalizable",
            "x": 8,
            "y": 3,
            "uncertainty_radius": 3,
            "scene": "play_view",
            "difficulty": ["blur"],
        }[field]
        if field == "visibility":
            b[0].update(x=None, y=None, uncertainty_radius=None)
    paths = stream_documents(generated_v2, tmp_path / "originals", a, b)
    with pytest.raises(ValueError, match="Explicit adjudication required"):
        validated_streams(generated_v2, paths)


@pytest.mark.parametrize(
    "change",
    [
        "index_assessment_order",
        "segment_assessment_order",
        "segment_session",
        "segment_assessor",
        "index_schema",
        "index_stream",
        "index_role",
        "index_protocol",
        "index_inputs",
        "index_eligibility",
        "index_extra_field",
        "segment_protocol",
        "segment_inputs",
        "segment_eligibility",
        "negative_without_evidence",
        "unknown_with_coordinates",
        "missing_inspection",
    ],
)
def test_v2_provenance_and_observation_contract(generated_v2, tmp_path, change):
    paths = stream_documents(
        generated_v2,
        tmp_path / "originals",
        adjudicated=document(generated_v2)["cases"][:1],
    )
    if change == "index_assessment_order":
        index = assessments.read_json(paths[2])
        index["assessment_sha256"].reverse()
        write(paths[2], index)
    elif change == "segment_assessment_order":
        edit_segment(paths[2], 0, lambda d: d["assessment_sha256"].reverse())
    elif change.startswith("index_"):
        field, value = {
            "index_schema": ("schema_version", True),
            "index_stream": ("stream_id", "b"),
            "index_role": ("role", "source_only_assessment"),
            "index_protocol": ("protocol_sha256", "0" * 64),
            "index_inputs": ("inputs_sha256", "0" * 64),
            "index_eligibility": (
                "eligibility",
                dict.fromkeys(assessments.ELIGIBILITY, True),
            ),
            "index_extra_field": ("unexpected", True),
        }[change]
        index = assessments.read_json(paths[0])
        index[field] = value
        write(paths[0], index)
    else:

        def mutate(segment):
            if change == "segment_session":
                segment["session_id"] = "unbound generated session"
            elif change == "segment_assessor":
                segment["assessor_id"] = "b"
            elif change in ("segment_protocol", "segment_inputs"):
                segment[change.removeprefix("segment_") + "_sha256"] = "0" * 64
            elif change == "segment_eligibility":
                segment["eligibility"]["training_allowed"] = True
            elif change == "negative_without_evidence":
                segment["cases"][0]["visibility"] = "not_visible"
            elif change == "unknown_with_coordinates":
                segment["cases"][0]["x"] = 1
            else:
                segment["cases"][0]["inspected_frames"] = []

        edit_segment(paths[0], 0, mutate)
    with pytest.raises(ValueError):
        validated_streams(generated_v2, paths)


@pytest.mark.parametrize("mode", ["uninspected", "shared", "one_byte_excess"])
def test_v2_session_png_budget_counts_unique_paths_across_rows(
    generated_v2, tmp_path, mode
):
    # Synthetic receipt sizes exercise transport accounting without allocating large PNGs.
    inputs = copy.deepcopy(generated_v2["inputs"])
    first = inputs["cases"][0]
    selected = first["context"][-1]["identity"]
    for member in first["context"]:
        member["identity"]["image"]["bytes"] = assessments.MAX_SESSION_IMAGES // 4
    # The first center is repeated by clamping: its PNG counts once.
    for case in inputs["cases"][1:4]:
        center = next(m for m in case["context"] if m["offset"] == 0)
        center["identity"]["image"]["bytes"] = assessments.MAX_SESSION_IMAGES // 4
    if mode != "uninspected":
        selected["image"]["bytes"] = 1
    if mode == "shared":
        for member in first["context"]:
            if member["frame"] == first["center_frame"]:
                member["identity"]["image"]["bytes"] -= 1
        # A context PNG shared across rows is charged once for this session.
        for case in inputs["cases"][1:4]:
            case["context"][0].update(
                frame=selected["frame"], identity=copy.deepcopy(selected)
            )
    alternate = {
        **generated_v2,
        "inputs": inputs,
        "inputs_path": tmp_path / "synthetic-inputs.json",
    }
    write(alternate["inputs_path"], inputs)
    rows = document(alternate)["cases"]
    if mode != "uninspected":
        for row in rows[:4] if mode == "shared" else rows[:1]:
            row["inspected_frames"].append(
                {
                    "frame": selected["frame"],
                    "image_sha256": selected["image"]["sha256"],
                }
            )
    paths = stream_documents(alternate, tmp_path / "originals", a=rows)
    if mode == "one_byte_excess":
        with pytest.raises(ValueError, match="PNG byte budget"):
            validated_streams(alternate, paths)
    else:
        assert validated_streams(alternate, paths)[-1]["case_count"] == 128


def test_v2_rejects_full_v1_documents(generated_v2, tmp_path):
    paths = documents(generated_v2, tmp_path / "originals")
    with pytest.raises(ValueError, match="Stream index fields"):
        validated_streams(generated_v2, paths)


def test_v2_originals_obey_total_byte_budget(generated_v2, tmp_path, monkeypatch):
    paths = stream_documents(generated_v2, tmp_path / "originals")
    monkeypatch.setattr(assessments, "MAX_OUTPUT", sum(p.stat().st_size for p in paths))
    with pytest.raises(ValueError, match="originals exceed byte budget"):
        validated_streams(generated_v2, paths)


def test_v2_relative_index_paths_remain_portable(generated_v2, tmp_path, monkeypatch):
    paths = stream_documents(generated_v2, tmp_path / "originals")
    monkeypatch.chdir(tmp_path)
    relative_paths = [p.relative_to(tmp_path) for p in paths]
    assert validated_streams(generated_v2, relative_paths)[-1]["case_count"] == 128
