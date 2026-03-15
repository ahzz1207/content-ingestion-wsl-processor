import json
from pathlib import Path

import pytest

from content_ingestion.inbox.processor import JobProcessor
from content_ingestion.inbox.protocol import JobProtocolError


def test_job_processor_writes_processed_outputs(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "processing" / "20260312_153000_ab12cd"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.txt").write_text("Title line\n\nBody line", encoding="utf-8")
    (job_dir / "attachments" / "source").mkdir(parents=True)
    (job_dir / "attachments" / "source" / "raw.html").write_text(
        "<html><body>raw</body></html>",
        encoding="utf-8",
    )
    (job_dir / "attachments" / "derived").mkdir(parents=True)
    (job_dir / "attachments" / "derived" / "capture_validation.json").write_text(
        json.dumps(
            {
                "summary": {
                    "status": "pass",
                    "passed": 4,
                    "warned": 0,
                    "failed": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "job_id": "20260312_153000_ab12cd",
                "content_shape": "article",
                "primary_payload": {
                    "path": "payload.txt",
                    "role": "focused_capture",
                    "media_type": "text/plain",
                    "content_type": "txt",
                    "size_bytes": 22,
                    "is_primary": True,
                },
                "artifacts": [
                    {
                        "path": "payload.txt",
                        "role": "focused_capture",
                        "media_type": "text/plain",
                        "size_bytes": 22,
                        "is_primary": True,
                    },
                    {
                        "path": "attachments/source/raw.html",
                        "role": "raw_capture",
                        "media_type": "text/html",
                        "size_bytes": 29,
                        "is_primary": False,
                    },
                    {
                        "path": "attachments/derived/capture_validation.json",
                        "role": "capture_validation",
                        "media_type": "application/json",
                        "size_bytes": 88,
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
                "job_id": "20260312_153000_ab12cd",
                "source_url": "https://example.com/article",
                "platform": "generic",
                "collector": "windows-client",
                "collected_at": "2026-03-12T15:30:00+08:00",
                "content_type": "txt",
                "final_url": "https://example.com/final-article",
                "collection_mode": "browser",
                "browser_channel": "msedge",
                "profile_slug": "wechat-profile",
                "wait_until": "networkidle",
                "wait_for_selector": ".rich_media_content",
                "wait_for_selector_state": "visible",
                "title_hint": "Inbox Title",
                "author_hint": "Inbox Author",
                "published_at_hint": "2026\u5e743\u670814\u65e5 12:58",
                "primary_payload_role": "focused_capture",
                "content_shape": "article",
                "capture_manifest_filename": "capture_manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    output_dir = JobProcessor().process(job_dir)

    assert output_dir == shared_root / "processed" / "20260312_153000_ab12cd"
    assert (output_dir / "normalized.json").exists()
    assert (output_dir / "normalized.md").exists()
    assert (output_dir / "pipeline.json").exists()
    assert (output_dir / "status.json").exists()
    normalized = json.loads((output_dir / "normalized.json").read_text(encoding="utf-8"))
    status = json.loads((output_dir / "status.json").read_text(encoding="utf-8"))
    pipeline = json.loads((output_dir / "pipeline.json").read_text(encoding="utf-8"))
    normalized_md = (output_dir / "normalized.md").read_text(encoding="utf-8")
    assert normalized["status"] == "success"
    assert normalized["content_type"] == "txt"
    assert normalized["asset"]["title"] == "Inbox Title"
    assert normalized["asset"]["content_shape"] == "article"
    assert normalized["asset"]["canonical_url"] == "https://example.com/final-article"
    asset_metadata = normalized["asset"]["metadata"]
    assert asset_metadata["job_id"] == "20260312_153000_ab12cd"
    assert asset_metadata["content_type"] == "txt"
    assert asset_metadata["handoff"] == {
        "collector": "windows-client",
        "collected_at": "2026-03-12T15:30:00+08:00",
        "collection_mode": "browser",
        "browser_channel": "msedge",
        "profile_slug": "wechat-profile",
        "wait_until": "networkidle",
        "wait_for_selector": ".rich_media_content",
        "wait_for_selector_state": "visible",
        "primary_payload_role": "focused_capture",
        "content_shape": "article",
        "capture_manifest_filename": "capture_manifest.json",
    }
    assert asset_metadata["capture"]["content_shape"] == "article"
    assert asset_metadata["capture"]["validation"]["status"] == "pass"
    assert asset_metadata["media_processing"]["status"] == "skipped"
    assert asset_metadata["llm_processing"]["status"] == "skipped"
    assert asset_metadata["llm_processing"]["provider"] == "openai"
    assert asset_metadata["llm_processing"]["schema_mode"] == "json_schema"
    assert asset_metadata["llm_processing"]["content_policy_id"] == "article_text_first_v1"
    assert asset_metadata["llm_processing"]["supported_input_modalities"] == ["text", "image", "text_image"]
    assert asset_metadata["llm_processing"]["text_input_modality"] == "text_image"
    assert asset_metadata["llm_processing"]["multimodal_input_modality"] == "text_image"
    assert (
        asset_metadata["llm_processing"]["task_intent"]
        == "summarize_article_with_optional_image_grounding"
    )
    assert asset_metadata["llm_processing"]["skip_reason"] == "missing OPENAI_API_KEY"
    assert asset_metadata["llm_processing"]["request_artifacts"] == {}
    assert asset_metadata["llm_processing"]["warnings"] == ["OPENAI_API_KEY is not configured"]
    assert asset_metadata["llm_processing"]["handshake"] == {
        "provider": "openai",
        "base_url": None,
        "analysis_model": None,
        "multimodal_model": None,
        "schema_mode": "json_schema",
        "content_policy_id": "article_text_first_v1",
        "supported_input_modalities": ["text", "image", "text_image"],
        "text_input_modality": "text_image",
        "multimodal_input_modality": "text_image",
        "task_intent": "summarize_article_with_optional_image_grounding",
        "skip_reason": "missing OPENAI_API_KEY",
        "request_artifacts": {},
    }
    assert normalized["asset"]["blocks"]
    assert normalized["asset"]["attachments"]
    assert normalized["asset"]["evidence_segments"]
    assert normalized["asset"]["author"] == "Inbox Author"
    assert normalized["asset"]["published_at"] == "2026-03-14T12:58:00"
    assert status["status"] == "success"
    assert status["stage"] == "normalized"
    assert status["processor"] == "wsl-processor"
    assert status["payload_filename"] == "payload.txt"
    assert status["content_type"] == "txt"
    assert status["artifact_count"] == 3
    assert status["capture_manifest_filename"] == "capture_manifest.json"
    assert status["capture_validation_status"] == "pass"
    assert status["llm_provider"] == "openai"
    assert status["llm_skip_reason"] == "missing OPENAI_API_KEY"
    assert pipeline["status"] == "success"
    assert pipeline["payload_filename"] == "payload.txt"
    assert pipeline["content_type"] == "txt"
    assert pipeline["artifact_count"] == 3
    assert pipeline["capture_manifest_filename"] == "capture_manifest.json"
    assert pipeline["capture_validation_status"] == "pass"
    assert pipeline["media_processing_status"] == "skipped"
    assert pipeline["llm_processing_status"] == "skipped"
    assert pipeline["llm_provider"] == "openai"
    assert pipeline["llm_skip_reason"] == "missing OPENAI_API_KEY"
    assert [step["name"] for step in pipeline["steps"]] == [
        "load_metadata",
        "load_capture_manifest",
        "load_capture_validation",
        "parse_payload",
        "resolve_openai_api_key",
        "write_outputs",
    ]
    assert "- Author: Inbox Author" in normalized_md
    assert "- Published At: 2026-03-14T12:58:00" in normalized_md
    assert not (output_dir / "READY").exists()


def test_job_processor_moves_invalid_job_to_failed(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "processing" / "20260312_153000_badmeta"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.txt").write_text("Body line", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_badmeta",
                "source_url": "https://example.com/article"
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    output_dir = JobProcessor().process(job_dir)

    assert output_dir == shared_root / "failed" / "20260312_153000_badmeta"
    assert (output_dir / "error.json").exists()
    assert (output_dir / "status.json").exists()
    error = json.loads((output_dir / "error.json").read_text(encoding="utf-8"))
    status = json.loads((output_dir / "status.json").read_text(encoding="utf-8"))
    assert error["error_code"] == "job_protocol_error"
    assert error["payload_filename"] == "payload.txt"
    assert error["source_url"] == "https://example.com/article"
    assert status["status"] == "failed"
    assert status["processor"] == "wsl-processor"
    assert not (output_dir / "READY").exists()


def test_job_processor_keeps_original_markdown_payload(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "processing" / "20260312_153000_markdown"
    markdown = "# Original Title\n\n- item 1\n- item 2\n"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.md").write_text(markdown, encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_markdown",
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

    output_dir = JobProcessor().process(job_dir)

    assert (output_dir / "normalized.md").read_text(encoding="utf-8") == markdown.strip()
    normalized = json.loads((output_dir / "normalized.json").read_text(encoding="utf-8"))
    assert normalized["asset"]["content_markdown"] == markdown.strip()


def test_job_processor_refuses_to_overwrite_existing_output(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    job_dir = shared_root / "processing" / "20260312_153000_collision"
    existing_failed_dir = shared_root / "failed" / "20260312_153000_collision"
    job_dir.mkdir(parents=True)
    existing_failed_dir.mkdir(parents=True)
    (job_dir / "payload.txt").write_text("Body line", encoding="utf-8")
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "20260312_153000_collision",
                "source_url": "https://example.com/article"
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    with pytest.raises(JobProtocolError):
        JobProcessor().process(job_dir)

    assert job_dir.exists()
