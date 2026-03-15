import argparse
import json
from pathlib import Path

from content_ingestion.app.bootstrap import build_app
from content_ingestion.core.models import FetchResult, SessionStatus


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="content-ingestion")
    subparsers = parser.add_subparsers(dest="command", required=True)

    login = subparsers.add_parser("login")
    login.add_argument("platform")
    login.add_argument("--url")
    login.add_argument("--profile-dir", type=Path)
    login.add_argument("--browser-channel")

    session_status = subparsers.add_parser("session-status")
    session_status.add_argument("platform")

    clear_session = subparsers.add_parser("clear-session")
    clear_session.add_argument("platform")

    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("url")
    fetch.add_argument("--output-dir", type=Path)
    fetch.add_argument("--profile-dir", type=Path)
    fetch.add_argument("--browser-channel")

    ingest = subparsers.add_parser("ingest")
    ingest.add_argument("url")
    ingest.add_argument("--profile-dir", type=Path)
    ingest.add_argument("--browser-channel")

    process_job = subparsers.add_parser("process-job")
    process_job.add_argument("job_dir", type=Path)

    validate_job = subparsers.add_parser("validate-job")
    validate_job.add_argument("job_dir", type=Path)

    validate_inbox = subparsers.add_parser("validate-inbox")
    validate_inbox.add_argument("shared_root", nargs="?", type=Path)

    watch_inbox = subparsers.add_parser("watch-inbox")
    watch_inbox.add_argument("shared_root", nargs="?", type=Path)
    watch_inbox.add_argument("--once", action="store_true")
    watch_inbox.add_argument("--interval-seconds", type=float, default=5.0)

    subparsers.add_parser("doctor")
    return parser


def _print_session_status(status: SessionStatus) -> None:
    state = "available" if status.is_available else "missing"
    print(f"platform={status.platform} status={state}")


def _print_fetch_result(result: FetchResult) -> None:
    print(f"status={result.status} platform={result.platform} url={result.url}")
    if result.error_code:
        print(f"error_code={result.error_code}")
    if result.error_message:
        print(f"error_message={result.error_message}")
    if result.content:
        print(f"title={result.content.title}")


def _resolve_shared_root(value: Path | None, fallback: Path) -> Path:
    return value or fallback


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    container = build_app()

    if args.command == "login":
        _print_session_status(
            container.service.login(
                args.platform,
                start_url=args.url,
                profile_dir=args.profile_dir,
                browser_channel=args.browser_channel,
            )
        )
        return
    if args.command == "session-status":
        _print_session_status(container.service.get_session_status(args.platform))
        return
    if args.command == "clear-session":
        container.service.clear_session(args.platform)
        print(f"cleared session for {args.platform}")
        return
    if args.command == "fetch":
        _print_fetch_result(
            container.service.fetch(
                args.url,
                output_dir=args.output_dir,
                profile_dir=args.profile_dir,
                browser_channel=args.browser_channel,
            )
        )
        return
    if args.command == "ingest":
        print(
            f"ingestion_id={container.service.ingest(args.url, profile_dir=args.profile_dir, browser_channel=args.browser_channel)}"
        )
        return
    if args.command == "process-job":
        print(f"job_output={container.service.process_job(args.job_dir)}")
        return
    if args.command == "validate-job":
        print(json.dumps(container.service.validate_job(args.job_dir), ensure_ascii=False, indent=2))
        return
    if args.command == "validate-inbox":
        shared_root = _resolve_shared_root(args.shared_root, container.settings.shared_inbox_root)
        print(
            json.dumps(
                container.service.validate_inbox(shared_root),
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    if args.command == "watch-inbox":
        shared_root = _resolve_shared_root(args.shared_root, container.settings.shared_inbox_root)
        outputs = container.service.watch_inbox(
            shared_root,
            once=args.once,
            interval_seconds=args.interval_seconds,
        )
        if not args.once and not outputs:
            print("watcher_stopped=keyboard_interrupt")
        for path in outputs:
            print(f"job_output={path}")
        return
    if args.command == "doctor":
        for line in container.service.doctor():
            print(line)
        return

    parser.error(f"unknown command: {args.command}")
