"""Opt-in real checkpoint/track compatibility; this is not an accuracy test."""

import hashlib
import json
import os

import pytest
from badminton.config import DATA, WEIGHTS
from badminton.recognition import recognition_targets, recognize_strokes
from badminton.storage import Store
from badminton.video import timestamps_for


@pytest.mark.skipif(
    os.environ.get("BADMINTON_GPU_TESTS") != "1", reason="Opt-in real checkpoint test"
)
def test_published_bst_checkpoint_on_actual_source_aligned_tracks(tmp_path):
    torch = pytest.importorskip("torch")
    pytest.importorskip("positional_encodings")
    pytest.importorskip("torchinfo")
    if not torch.cuda.is_available():
        pytest.skip("CUDA required for the real laptop checkpoint check")
    if not (WEIGHTS / "bst_0_JnB_bone_2.pt").is_file():
        pytest.skip("Download the stroke checkpoint first")
    video_id = "970dbd8adfe548d8"
    paths = [
        DATA / video_id / "runs" / f"{identifier}.json"
        for identifier in (
            "b8bdae17e8374a20bbf16f554c551f19",
            "ad0696c19b4b4be0beddf592a641cca0",
        )
    ]
    if not all(path.is_file() for path in paths):
        pytest.skip("This check needs the cached pilot perception runs")
    store = Store(DATA)
    document = store.annotations(video_id)
    revision, events = document.revision, document.model_dump()["events"]
    checksums = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    players, shuttle = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    output = tmp_path / "recognition.json"
    summary = recognize_strokes(
        store.video(video_id),
        timestamps_for(DATA, video_id),
        document,
        players,
        shuttle,
        recognition_targets(document),
        "b8bdae17e8374a20bbf16f554c551f19",
        lambda value: None,
        output,
    )
    assert summary["device"] == "cuda:0" and summary["candidate_count"] == len(events)
    result = json.loads(output.read_text())
    valid = [item for item in result["candidates"] if item.get("top_classes")]
    assert valid and all(item["side"] == "unknown" for item in valid)
    assert all(0 <= item["family_score"] <= 1 for item in valid)
    assert store.annotations(video_id).revision == revision
    assert store.annotations(video_id).model_dump()["events"] == events
    assert [
        hashlib.sha256(path.read_bytes()).hexdigest() for path in paths
    ] == checksums
