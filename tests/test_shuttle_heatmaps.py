"""Research observation must preserve default inference and complete evidence."""

import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from badminton import shuttle
from badminton import shuttle_heatmaps as diagnostic
from badminton.shuttle_supervision import publish_json
from PIL import Image


def source_frame(value):
    return SimpleNamespace(
        to_image=lambda: Image.fromarray(np.full((8, 8, 3), value, np.uint8))
    )


def ensemble(size, observer=None):
    calls = []
    times = [2.0 + n * 0.037 for n in range(size)]

    def predict(images):
        calls.append([int(image[0, 0, 0]) for image in images[1:]])
        values = np.zeros((3, 288, 512), np.float32)
        for offset, image in enumerate(images[1:]):
            values[offset, 20, 30] = 0.6 + int(image[0, 0, 0]) * 0.01
        return values

    rows = list(
        shuttle.infer_camera_segment(
            [(n + 7, t, source_frame(n)) for n, t in enumerate(times)],
            np.zeros((288, 512, 3), np.uint8),
            3,
            predict,
            1280,
            720,
            heatmap_observer=observer,
        )
    )
    return rows, calls


@pytest.mark.parametrize("size", [1, 2, 3, 8])
def test_observer_isolated_readonly_copy_preserves_all_rows_weights_and_pts(size):
    expected, calls = ensemble(size)
    seen = []

    def observe(frame, timestamp, heat):
        assert not heat.flags.writeable
        with pytest.raises(ValueError):
            heat[0, 0] = 1
        seen.append((frame, timestamp, heat.copy()))
        # A caller can reenable writing on its own copy, but cannot change output.
        heat.setflags(write=True)
        heat[:] = 0

    current, current_calls = ensemble(size, observe)
    assert current == expected and current_calls == calls
    assert [(frame, time) for frame, time, _ in seen] == [
        (row["frame"], row["time_s"]) for row in expected
    ]
    assert len(seen) == size
    for index, (_, _, heat) in enumerate(seen):
        assert heat.dtype == np.float32 and heat.shape == (288, 512)
        assert float(heat[20, 30]) == pytest.approx(0.6 + index * 0.01)


def test_observer_failure_is_not_swallowed_and_camera_segments_never_share_arrays():
    def fail(*_args):
        raise RuntimeError("capture unavailable")

    with pytest.raises(RuntimeError, match="capture unavailable"):
        ensemble(5, fail)
    captured = []
    ensemble(1, lambda _f, _t, h: captured.append(h))
    ensemble(2, lambda _f, _t, h: captured.append(h))
    assert len(captured) == 3
    assert all(
        not np.shares_memory(a, b)
        for i, a in enumerate(captured)
        for b in captured[i + 1 :]
    )


def test_response_geometry_uses_source_pixels_and_first_row_major_tie():
    heat = np.zeros((288, 512), np.float32)
    heat[50, 30] = heat[100, 100] = 0.8
    case = {"width": 1280, "height": 720}
    label = {"state": "visible", "x": 76.25, "y": 126.25, "uncertainty_px": 2}
    result = diagnostic.response_statistics(heat, case, label)
    assert result["global_first_argmax_source_xy"] == [76.25, 126.25]
    assert result["global_argmax_label_distance_px"] == 0
    assert result["local"]["nominal"]["local_global_ratio"] == 1
    assert result["local"]["nominal"]["above_original_threshold_cells"] == 1
    inner, nominal, outer = [
        result["local"][k]["cell_support"]
        for k in ("uncertainty_inner", "nominal", "uncertainty_outer")
    ]
    assert 0 < inner < nominal < outer


def test_zero_response_and_empty_disk_remain_explicit_not_perfect_or_negative():
    heat = np.zeros((288, 512), np.float32)
    result = diagnostic.response_statistics(
        heat,
        {"width": 1280, "height": 720},
        {"state": "visible", "x": 0, "y": 0, "uncertainty_px": 99},
    )
    assert result["global_zero_response"] and result["global_max"] == 0
    assert result["local"]["nominal"]["local_global_ratio"] is None
    assert result["local"]["uncertainty_inner"]["cell_support"] == 0
    assert result["local"]["uncertainty_inner"]["max_response"] is None
    unknown = diagnostic.response_statistics(
        heat,
        {"width": 1280, "height": 720},
        {"state": "unknown", "x": 100, "y": 100, "uncertainty_px": 1},
    )
    assert unknown["local"] is None
    aggregate = diagnostic.aggregate_responses(
        [
            {"state": "visible", "response": result},
            {"state": "unknown", "response": unknown},
            {"state": "not_visible", "response": None},
        ]
    )
    assert aggregate["counts"]["cases"] == 3
    assert aggregate["counts"]["available_heatmaps"] == 2
    assert aggregate["counts"]["unavailable_heatmaps"] == 1
    assert aggregate["counts"]["visible_coordinate_support"] == 1
    assert aggregate["counts"]["state:visible_unlocalizable"] == 0
    assert diagnostic.aggregate_responses([])["descriptive"] == {}


@pytest.mark.parametrize(
    "bad",
    [
        np.zeros((288, 512), np.float64),
        np.zeros((8, 8), np.float32),
        np.full((288, 512), np.nan, np.float32),
        np.full((288, 512), -1, np.float32),
        np.full((288, 512), 2, np.float32),
    ],
)
def test_invalid_heatmap_is_never_used(bad):
    with pytest.raises(ValueError, match="finite float32"):
        diagnostic.validate_heatmap(bad)


def test_array_seal_trailing_bytes_and_protocol_are_strict(tmp_path):
    assert diagnostic.protocol()["expected"]["cases"] == 60
    path = tmp_path / "heat.npy"
    stream = io.BytesIO()
    np.save(stream, np.zeros((288, 512), np.float32), allow_pickle=False)
    diagnostic.publish_bytes(path, stream.getvalue())
    entry = diagnostic.audit.seal(tmp_path, path)
    assert diagnostic.read_heatmap(tmp_path, entry).shape == (288, 512)
    with pytest.raises(FileExistsError):
        diagnostic.publish_bytes(path, stream.getvalue())
    changed = tmp_path / "trailing.npy"
    diagnostic.publish_bytes(changed, stream.getvalue() + b"extra")
    with pytest.raises(ValueError, match="trailing"):
        diagnostic.read_heatmap(tmp_path, diagnostic.audit.seal(tmp_path, changed))
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Changed"):
        diagnostic.read_heatmap(tmp_path, entry)


def test_completed_view_requires_exact_source_case_frame_and_raw_components(tmp_path):
    rows, _ = ensemble(1)
    view = {
        "id": "view",
        "video_id": "video",
        "start_frame": 7,
        "end_frame": 8,
        "case_ids": ["video:7"],
    }
    case = {
        "id": "video:7",
        "video_id": "video",
        "frame": 7,
        "width": 1280,
        "height": 720,
    }
    heat = []
    ensemble(1, lambda _f, _t, h: heat.append(h.copy()))
    stream = io.BytesIO()
    np.save(stream, heat[0], allow_pickle=False)
    diagnostic.publish_bytes(tmp_path / "heat.npy", stream.getvalue())
    publish_json(tmp_path / "native.json", {"frames": rows})
    item = {
        "case": case,
        "view_id": "view",
        "time_s": rows[0]["time_s"],
        "array": diagnostic.audit.seal(tmp_path, tmp_path / "heat.npy"),
    }
    record = {
        "clip": "view",
        "view": view,
        "context_sha256": "frozen",
        "run": diagnostic.audit.seal(tmp_path, tmp_path / "native.json"),
        "heatmaps": {"video:7": item},
    }
    publish_json(tmp_path / "complete.json", record)
    seal = diagnostic.audit.seal(tmp_path, tmp_path / "complete.json")
    assert (
        diagnostic.completed_view(tmp_path, seal, view, [case], "frozen")[0] == record
    )
    with pytest.raises(ValueError, match="binding"):
        diagnostic.completed_view(tmp_path, seal, view, [case], "other")
    record["heatmaps"] = {}
    publish_json(tmp_path / "missing.json", record)
    with pytest.raises(ValueError, match="membership"):
        diagnostic.completed_view(
            tmp_path,
            diagnostic.audit.seal(tmp_path, tmp_path / "missing.json"),
            view,
            [case],
            "frozen",
        )


def test_native_emitted_terminal_roundtrip_retains_cumulative_seals(
    tmp_path, monkeypatch
):
    # The real Store/lifetime behavior is covered by subprocess tests below;
    # this checks the exact emitted writer schema without any model import.
    from badminton.jobs import JobCancelled
    from badminton.storage import Store

    root = tmp_path
    shared = root / "data/processed"
    store = Store(shared)
    output = root / ".cache/output"
    monkeypatch.setattr(diagnostic, "_require_store", lambda _root: shared)
    monkeypatch.setattr(
        diagnostic,
        "load",
        lambda *_args: (
            {"views": [], "consumer_files": {}},
            {"max_native_seconds": 10},
            (None,) * 6,
        ),
    )
    import sys

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True)),
    )
    monkeypatch.setitem(sys.modules, "torchvision", SimpleNamespace())
    monkeypatch.setattr(diagnostic, "prior_proofs", lambda *_args: [])
    monkeypatch.setattr(diagnostic, "resume_plan", lambda *_args: ({}, [], 0))

    # Fail after real admission, before any completed output can exist.
    def unavailable(*_args):
        raise JobCancelled("fixture interrupted")

    monkeypatch.setattr(diagnostic, "consumers", unavailable)
    monkeypatch.setattr(
        diagnostic,
        "load",
        lambda *_args: (
            {"views": [{"id": "view"}], "consumer_files": {}},
            {"max_native_seconds": 10},
            (None,) * 6,
        ),
    )
    with pytest.raises(JobCancelled):
        diagnostic.native(root, output, "context")
    terminal = next((output / "attempts").glob("*/terminal.json"))
    document = diagnostic.read(terminal)
    assert (
        document["prior_terminal_seals"] == []
        and document["completed_clips"] == []
        and document["status"] == "interrupted"
    )
    with pytest.raises(ValueError, match="still alive"):
        from badminton.shuttle_diagnostic import prior_proofs

        prior_proofs(root, output)
    assert store.jobs()[0]["status"] == "interrupted"


@pytest.mark.parametrize(
    "changed", [None, "source", "snapshot", "protocol", "labels", "runtime", "views"]
)
def test_freeze_and_load_revalidate_every_source_and_consumer(
    tmp_path, monkeypatch, changed
):
    root = tmp_path
    source = root / "consumer.py"
    source.write_text("fixed source\n", encoding="utf-8")
    for name in ("packet", "labels"):
        publish_json(root / name / (name + ".json"), {"cases": []})
    publish_json(root / "baseline.json", {})
    monkeypatch.setattr(
        diagnostic, "_require_store", lambda _r: root / "data/processed"
    )
    monkeypatch.setattr(
        diagnostic,
        "consumers",
        lambda _r: {"consumer.py": diagnostic.audit.seal(root, source)},
    )
    monkeypatch.setattr(
        diagnostic.comparison, "runtime_snapshot", lambda: {"generated": True}
    )
    monkeypatch.setattr(diagnostic, "inputs", lambda *_a: (({"cases": []},), []))
    output = root / ".cache/frozen"
    result = diagnostic.freeze(
        root, root / "packet", root / "labels", root / "baseline.json", output
    )
    digest = result["experiment_sha256"]
    if changed == "source":
        source.write_bytes(b"changed")
    elif changed == "snapshot":
        (output / "consumer/consumer.py").write_bytes(b"changed")
    elif changed == "protocol":
        (output / "protocol.json").write_bytes(b"changed")
    elif changed == "labels":
        (root / "labels/labels.json").write_bytes(b"changed")
    elif changed == "runtime":
        monkeypatch.setattr(
            diagnostic.comparison, "runtime_snapshot", lambda: {"generated": False}
        )
    elif changed == "views":
        monkeypatch.setattr(
            diagnostic, "inputs", lambda *_a: (({"cases": []},), [{"id": "foreign"}])
        )
    if changed:
        with pytest.raises(ValueError, match=r"[Cc]hanged"):
            diagnostic.load(root, output, digest)
    else:
        assert diagnostic.load(root, output, digest)[0]["views"] == []
        with pytest.raises(ValueError, match="Changed"):
            diagnostic.load(root, output, "0" * 64)


RECOVERY_CHILD = r"""
import json,sys,os
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from badminton import shuttle
from badminton import shuttle_heatmaps as d
from badminton.storage import Store, ConflictError
root=Path(sys.argv[1]); stage=sys.argv[2]; out=root/'.cache/output'
store=Store(root/'data/processed')
sys.modules['torch']=SimpleNamespace(cuda=SimpleNamespace(is_available=lambda:True))
sys.modules['torchvision']=SimpleNamespace()
times=[i*.04 for i in range(20)]
meta={'id':'video','width':1280,'height':720,'frame_count':20}
cases=[{'id':f'video:{i}','video_id':'video','frame':i,'width':1280,'height':720} for i in (10,11,12)]
views=[{'id':f'view{i}','video_id':'video','start_frame':i,'end_frame':i+1,'core_index':0,'case_ids':[f'video:{i}']} for i in (10,11,12)]
reference_heat=np.zeros((288,512),np.float32);reference_heat[20,30]=.8
reference_point=shuttle.locate_shuttle(reference_heat,1280,720)
reference_rows=[{'frame':i,'time_s':times[i],'camera_segment_start_frame':0,'shuttle':dict(reference_point)} for i in range(20)]
if os.environ.get('FIXTURE_CONTROL_MISMATCH')=='1':reference_rows[12]['shuttle']['x']+=40
for v in views:v['expected_rows_sha256']=d.audit.digest(d.audit.encoded([d.comparison.native_row(reference_rows[v['start_frame']])]))
labels={'cases':[{'id':c['id'],'label':{'state':'visible' if c['frame']==10 else 'unknown','x':76.25,'y':51.25,'uncertainty_px':2,'difficulty':['ordinary']},'disagreement':{'state':False}} for c in cases]}
scan=root/'.cache/source-data/video/runs/scan.json'
if not scan.exists():d.publish(scan,{})
scan_sha=d.audit.file_hash(scan)
baseline={'locations':{'data':'.cache/source-data'},'evidence':{'catalogs':{'video':{'snapshot':{'annotations':{}}}}}}
baseline['evidence']['observations']={c['id']:{'available':True} for c in cases}
data=({'cases':cases},[(None,meta,times,None)],labels,baseline,{('video',0):{'start_frame':0,'frames':reference_rows}},{'video':{'segments':{'run_id':'scan','sha256':scan_sha}}})
spec={'max_native_seconds':3600,'expected':{'cases':3,'native_view_rows':3,'states':{'visible':1,'unknown':2,'not_visible':0,'visible_unlocalizable':0}},'control_gate':{'confidence_absolute_tolerance':.00001},'metrics':{'diagonal_tolerance':.005},'eligibility':{'training_allowed':False},'limitations':['Generated CPU stub only']}
d.load=lambda *_:({'views':views,'consumer_files':{}},spec,data)
checks=0
def consumers(*_):
    global checks
    checks+=1
    if stage=='early':raise KeyboardInterrupt()
    return {}
d.consumers=consumers
d.comparison.validate_research_run=lambda *_:None
invocations=[]
def track(video,root,data,start,end,progress,path,**kwargs):
    invocations.append(start)
    if stage in {'first','partial'} and len(invocations)>1:raise KeyboardInterrupt()
    heat=np.zeros((288,512),np.float32);heat[20,30]=.8
    kwargs['heatmap_observer'](start,times[start],heat)
    point=shuttle.locate_shuttle(heat,1280,720)
    d.publish(path,{'frames':[{'frame':start,'time_s':times[start],'camera_segment_start_frame':0,'shuttle':point}]})
    progress(1)
shuttle.track_shuttle=track
before=list((out/'attempts').glob('*/terminal.json'))
receipt=max(before,key=lambda p:p.stat().st_mtime_ns) if before else None
if stage.startswith('interpret'):
    terminal=d.read(receipt);entry=terminal['output_index']
    if stage=='interpret-mismatch':
        def must_not_interpret(*_):raise AssertionError('Response interpretation before compatible gate')
        d.response_statistics=must_not_interpret
    result=d.interpret(root,out,'frozen',out/entry['path'],entry['sha256'],receipt,d.audit.file_hash(receipt))
    report=d.read(d.sealed(out,result['report']))
    print(json.dumps({'compatible':result['compatible'],'cases':result['cases'],'summary':report.get('summary'),'groups':sorted(report['groups'])}))
    raise SystemExit(0)
if stage=='refused':store.claim_job({'id':'occupied','kind':'generated','video_id':None,'status':'running'})
try:d.native(root,out,'frozen',receipt,d.audit.file_hash(receipt) if receipt else None)
except (KeyboardInterrupt,ConflictError):pass
new=[p for p in (out/'attempts').glob('*/terminal.json') if p not in before]
assert len(new)==1
terminal=d.read(new[0])
if stage=='refused':store.put_job({'id':'occupied','kind':'generated','video_id':None,'status':'completed'})
print(json.dumps({'stage':stage,'complete':len(terminal['completed_clips']),'history':len(terminal['prior_terminal_seals']),'status':terminal['status'],'invocations':invocations}))
"""


def test_exited_process_recovery_retains_real_store_and_lifetime_guards(tmp_path):
    env = os.environ.copy()
    env.update(
        GH_TOKEN="",
        GITHUB_TOKEN="",
        BADMINTON_ROOT=str(tmp_path),
        BADMINTON_DATA_DIR=str(tmp_path / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(tmp_path / "models/weights"),
        GH_CONFIG_DIR=str(tmp_path / ".cache/offline-gh"),
    )
    output = tmp_path / ".cache/output"
    results = []
    raw_seals = {}
    for stage, expected in (
        ("first", 1),
        ("early", 1),
        ("partial", 2),
        ("refused", 2),
        ("final", 3),
    ):
        result = subprocess.run(
            [sys.executable, "-c", RECOVERY_CHILD, str(tmp_path), stage],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        value = json.loads(result.stdout.splitlines()[-1])
        assert value["complete"] == expected
        assert value["history"] == len(results)
        for path, digest in raw_seals.items():
            assert diagnostic.audit.file_hash(path) == digest
        raw_seals = {
            path: diagnostic.audit.file_hash(path) for path in output.rglob("*.npy")
        }
        results.append(value)
    assert results[-1]["invocations"] == [12] and results[-1]["status"] == "completed"
    assert results[1]["invocations"] == results[3]["invocations"] == []
    assert len(raw_seals) == 3
    for stage, compatible in (("interpret", True),):
        result = subprocess.run(
            [sys.executable, "-c", RECOVERY_CHILD, str(tmp_path), stage],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        value = json.loads(result.stdout.splitlines()[-1])
        assert value["compatible"] is compatible
        assert value["cases"] == (3 if compatible else 0)
        if compatible:
            assert value["summary"]["counts"]["cases"] == 3
            assert value["summary"]["counts"]["state:unknown"] == 2
            assert "state:visible_unlocalizable" in value["groups"]
    # A second immutable lineage has a fixed baseline disagreement from inception.
    # Never mutate expected view metadata in an already frozen lineage.
    mismatch_root = tmp_path / "mismatch"
    env.update(
        BADMINTON_ROOT=str(mismatch_root),
        BADMINTON_DATA_DIR=str(mismatch_root / "data/processed"),
        BADMINTON_WEIGHTS_DIR=str(mismatch_root / "models/weights"),
        FIXTURE_CONTROL_MISMATCH="1",
    )
    for stage in ("final", "interpret-mismatch"):
        result = subprocess.run(
            [sys.executable, "-c", RECOVERY_CHILD, str(mismatch_root), stage],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout.splitlines()[-1])
    assert value["compatible"] is False and value["cases"] == 3
    assert value["summary"]["counts"]["cases"] == 3
    assert value["summary"]["counts"]["available_heatmaps"] == 3
    assert value["summary"]["counts"]["unavailable_heatmaps"] == 0
    assert value["summary"]["counts"]["uninterpreted_heatmaps"] == 3
