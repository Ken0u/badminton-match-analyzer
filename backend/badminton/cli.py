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
    evaluate.add_argument("--output", type=Path, help="Also save the JSON report")
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
    args = parser.parse_args()
    if args.command == "import-s2doubles":
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
        from .recognition_evaluation import evaluate_recognition

        if not any((args.contacts_run, args.shuttle_run, args.recognition_run)):
            parser.error("Supply --contacts-run, --shuttle-run, or --recognition-run")
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
            if args.recognition_run:
                report["recognition"] = evaluate_recognition(
                    video,
                    annotations,
                    load_evaluation_run(
                        store, args.video_id, args.recognition_run, "recognition"
                    ),
                )
            if args.contacts_run:
                report["contacts"] = evaluate_contacts(
                    video,
                    annotations,
                    load_evaluation_run(
                        store, args.video_id, args.contacts_run, "contacts"
                    ),
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
