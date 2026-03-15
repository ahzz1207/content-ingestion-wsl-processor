import json
from pathlib import Path

from content_ingestion.inbox.processor import JobProcessor
from content_ingestion.inbox.watcher import InboxWatcher


def test_watcher_claims_and_processes_ready_job(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "incoming" / "20260312_153000_watch"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.md").write_text("# Markdown Title\n\nHello watcher", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_watch",
                "source_url": "https://example.com/markdown",
                "platform": "generic",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "md",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    outputs = InboxWatcher(shared_root, JobProcessor()).scan_once()

    assert outputs == [shared_root / "processed" / "20260312_153000_watch"]
    assert not job_dir.exists()
    assert (shared_root / "processed" / "20260312_153000_watch" / "normalized.md").exists()
    normalized_md = (
        shared_root / "processed" / "20260312_153000_watch" / "normalized.md"
    ).read_text(encoding="utf-8")
    assert normalized_md == "# Markdown Title\n\nHello watcher"
