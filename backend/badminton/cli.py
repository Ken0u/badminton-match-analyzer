import argparse
import json
import os
from pathlib import Path

from .config import DATA, ROOT
from .jobs import run_local_job
from .storage import ConflictError, Store
from .video import resolve_source, seconds_to_frames, timestamps_for, write_json


def load_evaluation_run(store, video_id, run_id, stage):
    """Read only a completed, same-video job's matching artifact."""
    job = next(
        (
            job
            for job in store.jobs(video_id)
            if job["id"] == run_id
            and job["status"] == "completed"
            and job["kind"] == stage
        ),
        None,
    )
    if job is None:
        raise ValueError(f"Completed {stage} run for this video not found: {run_id}")
    directory = (store.data / video_id / "runs").resolve()
    path = (directory / f"{run_id}.json").resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise ValueError("Run artifact is unavailable. Rerun this analysis window.")
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("video_id") != video_id or result.get("stage") != stage:
        raise ValueError("Run artifact does not match its registered video and stage")
    return result | {"run_id": run_id}


def main():
    parser = argparse.ArgumentParser(
        description="Badminton video inspection and review"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser(
        "ingest", help="Register and visually inspect a project-local video"
    )
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--mode", choices=["singles", "doubles"], required=True)
    serve = commands.add_parser("serve", help="Start the local review application")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="Allow a non-loopback listener behind an authenticated private proxy",
    )
    track = commands.add_parser(
        "track", help="Run player/pose baseline on a registered clip"
    )
    track.add_argument("video_id")
    track.add_argument("--start", type=float, default=0, help="Start in seconds")
    track.add_argument("--duration", type=float, default=10)
    track.add_argument("--stride", type=int, default=1)
    track.add_argument("--stage", choices=["players", "shuttle"], default="players")
    track.add_argument("--player-model", choices=["small", "nano"], default="small")
    track.add_argument(
        "--no-auto-court",
        action="store_true",
        help="Disable automatic court geometry for player tracking",
    )
    process = commands.add_parser(
        "process",
        help="Process or resume all source frames with bounded inference windows",
    )
    process.add_argument("video_id")
    process.add_argument("--player-model", choices=["small", "nano"], default="small")
    process.add_argument("--no-auto-court", action="store_true")
    process.add_argument("--no-recognition", action="store_true")
    segment = commands.add_parser(
        "segments", help="Scan the full video for camera/timestamp boundaries"
    )
    segment.add_argument("video_id")
    rallies = commands.add_parser(
        "rallies", help="Propose uncertain serve and rally-end review intervals"
    )
    rallies.add_argument("video_id")
    rallies.add_argument("--players-run", required=True)
    rallies.add_argument("--shuttle-run", required=True)
    evaluate = commands.add_parser(
        "evaluate", help="Measure saved runs against explicit human review labels"
    )
    evaluate.add_argument("video_id")
    evaluate.add_argument("--contacts-run", help="Completed contact proposal job ID")
    evaluate.add_argument("--shuttle-run", help="Completed shuttle tracking job ID")
    evaluate.add_argument(
        "--recognition-run", help="Completed shot-family recognition job ID"
    )
    evaluate.add_argument("--rallies-run", help="Completed serve/end proposal job ID")
    evaluate.add_argument("--output", type=Path, help="Also save the JSON report")
    export_plan = commands.add_parser(
        "export-rally-plan",
        help="Plan reviewed source-frame rally exports without rendering",
    )
    export_plan.add_argument("video_id")
    export_plan.add_argument("--revision", type=int, required=True)
    export_plan.add_argument("--output", type=Path, required=True)
    export_videos = commands.add_parser(
        "export-rally-videos",
        help="Render plain clips from a verified saved rally plan",
    )
    export_videos.add_argument("plan", type=Path)
    export_videos.add_argument("--output", type=Path, required=True)
    annotated = commands.add_parser(
        "export-annotated-videos",
        help="Render reviewed annotation overlays on a full video or rally clips",
    )
    annotated.add_argument("plan", type=Path)
    annotated.add_argument("--output", type=Path, required=True)
    annotated.add_argument("--scope", choices=("full", "rallies"), required=True)
    recognize = commands.add_parser(
        "recognize",
        help="Suggest singles shot families from cached pose and shuttle runs",
    )
    recognize.add_argument("video_id")
    recognize.add_argument("--players-run", required=True)
    recognize.add_argument("--shuttle-run", required=True)
    recognize.add_argument("--contacts-run")
    recognize.add_argument("--min-family-score", type=float, default=0.5)
    dataset = commands.add_parser(
        "import-shuttleset",
        help="Normalize pinned public stroke labels; source video alignment remains separate",
    )
    dataset.add_argument("source", type=Path)
    dataset.add_argument("--output", type=Path, required=True)
    doubles = commands.add_parser(
        "import-s2doubles",
        help="Normalize pinned doubles labels without certifying media alignment",
    )
    doubles.add_argument("source", type=Path)
    doubles.add_argument("--output", type=Path, required=True)
    finebadminton = commands.add_parser(
        "import-finebadminton",
        help="Normalize pinned action/side labels and separate published contact references",
    )
    finebadminton.add_argument("source", type=Path)
    finebadminton.add_argument("--output", type=Path, required=True)
    aicup = commands.add_parser(
        "import-aicup2023",
        help="Index pinned rally clips and contact/family/side labels without assuming match splits",
    )
    aicup.add_argument("archive", type=Path)
    aicup.add_argument("--output", type=Path, required=True)
    visual = commands.add_parser(
        "prepare-visual-features",
        help="Cache source RGB features for the frozen experimental singles learner",
    )
    visual.add_argument("archive", type=Path)
    visual.add_argument("--index", type=Path, required=True)
    visual.add_argument("--weights", type=Path, required=True)
    visual.add_argument("--output", type=Path, required=True)
    visual.add_argument("--device", default="cuda:0")
    visual.add_argument("--batch-size", type=int, default=32)
    visual_train = commands.add_parser(
        "train-visual-events",
        help="Train the experimental temporal event heads; no app weight installation",
    )
    visual_test = commands.add_parser(
        "evaluate-visual-events",
        help="Evaluate a frozen validation-selected visual event model",
    )
    for command in (visual_train, visual_test):
        command.add_argument("--index", type=Path, required=True)
        command.add_argument("--features", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--device", default="cuda:0")
    visual_test.add_argument("--run", type=Path, required=True)
    args = parser.parse_args()
    if args.command in ("train-visual-events", "evaluate-visual-events"):
        from .visual_learning import evaluate_visual, train_visual

        def visual_task(job_id, progress):
            if args.command == "train-visual-events":
                return train_visual(
                    args.index, args.features, args.output, progress, device=args.device
                )
            return evaluate_visual(
                args.index,
                args.features,
                args.run,
                args.output,
                progress,
                device=args.device,
            )

        try:
            result = run_local_job(Store(DATA), args.command, None, visual_task)
        except (ConflictError, ValueError, OSError, ImportError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2))
    elif args.command == "prepare-visual-features":
        from .visual_inputs import prepare_features

        try:
            result = run_local_job(
                Store(DATA),
                "feature-preparation",
                None,
                lambda job_id, progress: prepare_features(
                    args.archive,
                    args.index,
                    args.weights,
                    args.output,
                    progress,
                    device=args.device,
                    batch_size=args.batch_size,
                ),
            )
        except (ConflictError, ValueError, OSError, ImportError) as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2))
    elif args.command == "export-rally-plan":
        from .rally_export import ExportPlanStore, plan_rally_exports, write_export_plan

        try:
            plan = plan_rally_exports(
                ExportPlanStore(DATA), args.video_id, args.revision, ROOT
            )
            write_export_plan(args.output, plan, DATA)
        except (KeyError, ValueError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(plan, indent=2))
    elif args.command == "export-rally-videos":
        from .rally_export import ExportPlanStore
        from .rally_video import render_rally_videos

        try:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            manifest = render_rally_videos(
                ExportPlanStore(DATA), plan, ROOT, args.output
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(manifest, indent=2))
    elif args.command == "export-annotated-videos":
        from .rally_export import ExportPlanStore
        from .rally_overlay import render_annotated_videos

        try:
            plan = json.loads(args.plan.read_text(encoding="utf-8"))
            manifest = render_annotated_videos(
                ExportPlanStore(DATA), plan, ROOT, args.output, scope=args.scope
            )
        except (KeyError, TypeError, ValueError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(manifest, indent=2))
    elif args.command == "import-aicup2023":
        from .aicup_data import import_aicup2023

        try:
            report = import_aicup2023(args.archive, args.output)
        except (ValueError, OSError, KeyError) as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "record_count",
                        "clip_counts",
                        "labelled_clip_count",
                        "contact_label_eligible_records",
                        "training_ready_records",
                        "media_alignment",
                    )
                },
                indent=2,
            )
        )
    elif args.command == "import-finebadminton":
        from .finebadminton_data import import_finebadminton

        try:
            report = import_finebadminton(args.source, args.output)
        except (ValueError, OSError, KeyError) as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "record_count",
                        "rally_count",
                        "published_contact_records",
                        "training_ready_records",
                        "media_alignment",
                    )
                },
                indent=2,
            )
        )
    elif args.command == "import-s2doubles":
        from .doubles_data import import_doubles

        try:
            report = import_doubles(args.source, args.output)
        except (ValueError, OSError, KeyError) as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "record_count",
                        "rally_count",
                        "label_eligible_records",
                        "training_ready_records",
                        "media_alignment",
                    )
                },
                indent=2,
            )
        )
    elif args.command == "import-shuttleset":
        from .datasets import import_shuttleset

        try:
            report = import_shuttleset(args.source, args.output)
        except (ValueError, OSError, KeyError) as exc:
            parser.error(str(exc))
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "record_count",
                        "rally_count",
                        "family_eligible_records",
                        "side_eligible_records",
                        "training_ready_records",
                        "media_alignment",
                    )
                },
                indent=2,
            )
        )
    elif args.command == "ingest":
        from .ingest import inspect_video

        store = Store(DATA)
        try:
            result = run_local_job(
                store,
                "import",
                None,
                lambda job_id, progress: inspect_video(
                    args.path, args.mode, store, ROOT, progress
                ),
            )
        except ConflictError as exc:
            parser.error(str(exc))
        print(json.dumps(result, indent=2))
    elif args.command == "serve":
        if (
            args.host not in ("127.0.0.1", "::1", "localhost")
            and not (
                os.environ.get("BADMINTON_USERNAME")
                and os.environ.get("BADMINTON_PASSWORD")
            )
            and not args.allow_unauthenticated
        ):
            parser.error(
                "Set BADMINTON_USERNAME and BADMINTON_PASSWORD before binding a network interface, or explicitly use --allow-unauthenticated behind an authenticated proxy"
            )
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
    elif args.command == "segments":
        from .segments import scan_video

        store = Store(DATA)
        video = store.video(args.video_id)

        def task(job_id, progress):
            return scan_video(
                video,
                ROOT,
                DATA,
                progress,
                DATA / args.video_id / "runs" / f"{job_id}.json",
            )

        try:
            summary = run_local_job(store, "segments", args.video_id, task)
        except (ConflictError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(summary, indent=2))
    elif args.command == "track":
        from .shuttle import track_shuttle
        from .tracking import track_players

        store = Store(DATA)
        video = store.video(args.video_id)
        times = timestamps_for(DATA, args.video_id)
        try:
            start, end = seconds_to_frames(video, times, args.start, args.duration)
            if not 1 <= args.stride <= 10:
                raise ValueError("Stride must be between 1 and 10")
            if args.stage == "shuttle" and args.stride != 1:
                raise ValueError(
                    "Shuttle inference requires every source frame (stride 1)"
                )
        except ValueError as exc:
            parser.error(str(exc))

        def task(job_id, progress):
            output = DATA / args.video_id / "runs" / f"{job_id}.json"
            if args.stage == "players":
                return track_players(
                    video,
                    ROOT,
                    DATA,
                    store.annotations(args.video_id),
                    start,
                    end,
                    args.stride,
                    progress,
                    output,
                    player_model=args.player_model,
                    auto_calibrate=not args.no_auto_court,
                )
            return track_shuttle(video, ROOT, DATA, start, end, progress, output)

        try:
            summary = run_local_job(store, args.stage, args.video_id, task)
        except ConflictError as exc:
            parser.error(str(exc))
        print(json.dumps(summary, indent=2))
    elif args.command == "process":
        from .pipeline import process_match

        store = Store(DATA)
        video = store.video(args.video_id)
        settings = {
            "player_model": args.player_model,
            "auto_calibrate": not args.no_auto_court,
            "recognize": not args.no_recognition,
        }
        try:
            summary = run_local_job(
                store,
                "analysis",
                args.video_id,
                lambda job_id, progress: process_match(
                    video,
                    ROOT,
                    store,
                    store.annotations(args.video_id),
                    job_id,
                    progress,
                    settings,
                ),
            )
        except (ConflictError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(summary, indent=2))
    elif args.command == "rallies":
        from .rallies import generate_rallies, validate_rally_inputs

        store = Store(DATA)
        try:
            video = store.video(args.video_id)
            resolve_source(video, ROOT)
            players = load_evaluation_run(
                store, args.video_id, args.players_run, "players"
            )
            shuttle = load_evaluation_run(
                store, args.video_id, args.shuttle_run, "shuttle"
            )
            snapshot = store.annotations(args.video_id)
            times = timestamps_for(DATA, args.video_id)
            validate_rally_inputs(video, players, shuttle, snapshot, times)
            summary = run_local_job(
                store,
                "rallies",
                args.video_id,
                lambda job_id, progress: generate_rallies(
                    video,
                    players,
                    shuttle,
                    snapshot,
                    args.players_run,
                    args.shuttle_run,
                    DATA / args.video_id / "runs" / f"{job_id}.json",
                    times,
                ),
            )
        except (ConflictError, ValueError) as exc:
            parser.error(str(exc))
        print(json.dumps(summary, indent=2))
    elif args.command == "recognize":
        from .recognition import recognition_targets, recognize_strokes

        store = Store(DATA)
        try:
            video = store.video(args.video_id)
            resolve_source(video, ROOT)
            if video["mode"] != "singles":
                raise ValueError(
                    "The current pretrained classifier supports singles only"
                )
            players = load_evaluation_run(
                store, args.video_id, args.players_run, "players"
            )
            shuttle = load_evaluation_run(
                store, args.video_id, args.shuttle_run, "shuttle"
            ) | {"run_id": args.shuttle_run}
            contacts = (
                load_evaluation_run(store, args.video_id, args.contacts_run, "contacts")
                if args.contacts_run
                else None
            )
            if contacts and (
                contacts.get("shuttle_run_id") != args.shuttle_run
                or contacts.get("player_run_id") not in (None, args.players_run)
            ):
                raise ValueError("Contact proposals must use these same tracking runs")
            annotations = store.annotations(args.video_id)
            targets = recognition_targets(
                annotations,
                contacts,
                start_frame=max(players["start_frame"], shuttle["start_frame"]),
                end_frame=min(players["end_frame"], shuttle["end_frame"]),
            )
            if not targets:
                raise ValueError(
                    "Review shot contacts or generate contact suggestions first"
                )
            summary = run_local_job(
                store,
                "recognition",
                args.video_id,
                lambda job_id, progress: recognize_strokes(
                    video,
                    timestamps_for(DATA, args.video_id),
                    annotations,
                    players,
                    shuttle,
                    targets,
                    args.players_run,
                    progress,
                    DATA / args.video_id / "runs" / f"{job_id}.json",
                    args.min_family_score,
                    contacts_run_id=args.contacts_run,
                ),
            )
        except (KeyError, ValueError, OSError, RuntimeError, ConflictError) as exc:
            parser.error(str(exc))
        print(json.dumps(summary, indent=2))
    elif args.command == "evaluate":
        from .evaluation import evaluate_contacts, evaluate_shuttle
        from .rally_evaluation import evaluate_rallies
        from .recognition_evaluation import evaluate_recognition

        if not any(
            (
                args.contacts_run,
                args.shuttle_run,
                args.recognition_run,
                args.rallies_run,
            )
        ):
            parser.error(
                "Supply --contacts-run, --shuttle-run, --recognition-run, or --rallies-run"
            )
        store = Store(DATA)
        try:
            video = store.video(args.video_id)
            resolve_source(video, ROOT)
            annotations = store.annotations(args.video_id).model_dump()
            report = {
                "schema_version": 1,
                "video_id": video["id"],
                "video_sha256": video["sha256"],
                "annotation_revision": annotations["revision"],
            }
            native_times = None
            if args.contacts_run or args.recognition_run:
                try:
                    native_times = timestamps_for(DATA, args.video_id)
                except (OSError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "Native source timestamp map is unavailable or malformed"
                    ) from exc
            if args.rallies_run:
                report["rallies"] = evaluate_rallies(
                    video,
                    annotations,
                    load_evaluation_run(
                        store, args.video_id, args.rallies_run, "rallies"
                    ),
                    timestamps_for(DATA, args.video_id),
                )
            if args.recognition_run:
                report["recognition"] = evaluate_recognition(
                    video,
                    annotations,
                    load_evaluation_run(
                        store, args.video_id, args.recognition_run, "recognition"
                    ),
                    native_timestamps=native_times,
                )
            if args.contacts_run:
                report["contacts"] = evaluate_contacts(
                    video,
                    annotations,
                    load_evaluation_run(
                        store, args.video_id, args.contacts_run, "contacts"
                    ),
                    native_timestamps=native_times,
                )
            if args.shuttle_run:
                report["shuttle"] = evaluate_shuttle(
                    video,
                    annotations,
                    load_evaluation_run(
                        store, args.video_id, args.shuttle_run, "shuttle"
                    ),
                )
            if args.output:
                write_json(args.output, report)
        except (KeyError, ValueError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
