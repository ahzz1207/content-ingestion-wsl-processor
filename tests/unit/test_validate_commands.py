import json
from pathlib import Path

from content_ingestion.app.bootstrap import build_app


def test_validate_job_returns_structured_result(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "incoming" / "20260312_153000_valid"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.txt").write_text("hello", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_valid",
                "source_url": "https://example.com/article",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "txt",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    result = build_app().service.validate_job(job_dir)

    assert result["is_valid"] is True
    assert result["payload_filename"] == "payload.txt"
    assert result["errors"] == []


def test_validate_inbox_returns_invalid_job_errors(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "incoming" / "20260312_153000_invalid"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.html").write_text("<html></html>", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_invalid",
                "source_url": "https://example.com/article",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "txt",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    results = build_app().service.validate_inbox(shared_root)

    assert len(results) == 1
    assert results[0]["is_valid"] is False
    assert "content_type does not match payload suffix: txt != html" in results[0]["errors"]
