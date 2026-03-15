import json
from pathlib import Path

from content_ingestion.inbox.protocol import (
    JobPaths,
    find_payload_file,
    inspect_job,
    is_job_ready,
    validate_job,
)


def test_protocol_finds_ready_job_payload(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "incoming" / "20260312_153000_ab12cd"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.txt").write_text("hello", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_ab12cd",
                "source_url": "https://example.com/article",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "txt",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    job = JobPaths(shared_root=shared_root, stage_dir=shared_root / "incoming", job_id=job_dir.name)

    assert find_payload_file(job_dir) == job_dir / "payload.txt"
    assert is_job_ready(job) is True
    assert validate_job(job)["job_id"] == job.job_id


def test_protocol_inspect_job_reports_invalid_content_type(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "incoming" / "20260312_153000_badtype"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.txt").write_text("hello", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_badtype",
                "source_url": "https://example.com/article",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "html",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    job = JobPaths(shared_root=shared_root, stage_dir=shared_root / "incoming", job_id=job_dir.name)
    result = inspect_job(job)

    assert result.is_valid is False
    assert result.payload_filename == "payload.txt"
    assert "content_type does not match payload suffix: html != txt" in (result.errors or [])


def test_protocol_accepts_valid_capture_manifest(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "incoming" / "20260312_153000_manifest"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.html").write_text("<html><body>focused</body></html>", encoding="utf-8")
    (job_dir / "attachments" / "source").mkdir(parents=True)
    (job_dir / "attachments" / "source" / "raw.html").write_text(
        "<html><body>raw</body></html>",
        encoding="utf-8",
    )
    (job_dir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "job_id": "20260312_153000_manifest",
                "primary_payload": {
                    "path": "payload.html",
                    "role": "focused_capture",
                    "media_type": "text/html",
                    "content_type": "html",
                    "size_bytes": 33,
                    "is_primary": True,
                },
                "artifacts": [
                    {
                        "path": "payload.html",
                        "role": "focused_capture",
                        "media_type": "text/html",
                        "size_bytes": 33,
                        "is_primary": True,
                    },
                    {
                        "path": "attachments/source/raw.html",
                        "role": "raw_capture",
                        "media_type": "text/html",
                        "size_bytes": 29,
                        "is_primary": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_manifest",
                "source_url": "https://example.com/article",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "html",
                "capture_manifest_filename": "capture_manifest.json",
                "content_shape": "article",
                "primary_payload_role": "focused_capture",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    job = JobPaths(shared_root=shared_root, stage_dir=shared_root / "incoming", job_id=job_dir.name)

    assert validate_job(job)["job_id"] == job.job_id
    assert inspect_job(job).is_valid is True
