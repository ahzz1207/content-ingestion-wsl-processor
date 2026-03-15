import json
from datetime import datetime
from pathlib import Path

from content_ingestion.core.config import load_settings
from content_ingestion.core.models import ContentAsset, ContentAttachment, ContentBlock, EvidenceSegment
from content_ingestion.pipeline.llm_pipeline import analyze_asset


class _FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        model = kwargs["model"]
        if model == "gpt-4.1-mini":
            payload = {
                "summary": "Short summary",
                "analysis_items": ["Point A", "Point B"],
                "verification_items": [
                    {"claim": "Claim A", "status": "supported", "evidence": ["e1", "e2"]},
                ],
                "synthesis": "Final synthesis",
            }
        else:
            payload = {
                "visual_findings": ["Frame confirms setting"],
                "verification_adjustments": [
                    {"claim": "Claim B", "status": "mixed", "rationale": "Frame is partially consistent"},
                ],
                "overall_assessment": "Visual review completed",
            }
        return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()


class _FakeClient:
    def __init__(self) -> None:
        self.responses = _FakeResponses()


def test_analyze_asset_uses_text_and_multimodal_calls(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("CONTENT_INGESTION_MULTIMODAL_MODEL", "gpt-4.1")
    settings = load_settings()
    fake_client = _FakeClient()
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: fake_client)

    job_dir = tmp_path / "job"
    (job_dir / "analysis" / "frames").mkdir(parents=True)
    frame_path = job_dir / "analysis" / "frames" / "frame-001.jpg"
    frame_path.write_bytes(b"jpeg-bytes")
    asset = ContentAsset(
        source_platform="bilibili",
        source_url="https://example.com/video",
        canonical_url="https://example.com/video",
        content_shape="video",
        title="Demo Video",
        author="Uploader",
        published_at=datetime(2026, 3, 15, 10, 0, 0),
        content_text="Captured page content",
        transcript_text="Transcript body",
        blocks=[ContentBlock(id="b1", kind="paragraph", text="Paragraph 1")],
        attachments=[
            ContentAttachment(
                id="frame-1",
                path="analysis/frames/frame-001.jpg",
                role="analysis_frame",
                media_type="image/jpeg",
                kind="image",
            )
        ],
        evidence_segments=[EvidenceSegment(id="e1", kind="transcript", text="Evidence 1", source="transcript")],
    )

    result = analyze_asset(job_dir=job_dir, asset=asset, settings=settings)

    assert result.status == "pass"
    assert result.summary == "Short summary"
    assert result.analysis_items[:2] == ["Point A", "Point B"]
    assert result.verification_items[0]["claim"] == "Claim A"
    assert result.output_path == "analysis/llm/analysis_result.json"
    assert len(fake_client.responses.calls) == 2
    assert (job_dir / "analysis" / "llm" / "analysis_result.json").exists()


def test_analyze_asset_skips_without_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings = load_settings()
    asset = ContentAsset(
        source_platform="generic",
        source_url="https://example.com",
        title="Demo",
        content_text="hello",
    )

    result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)

    assert result.status == "skipped"
    assert result.warnings
