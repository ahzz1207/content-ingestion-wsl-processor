import json
from datetime import datetime
from pathlib import Path

from content_ingestion.core.config import load_settings
from content_ingestion.core.models import ContentAsset, ContentAttachment, ContentBlock, EvidenceSegment
from content_ingestion.pipeline.llm_contract import build_text_analysis_envelope, resolve_content_policy
from content_ingestion.pipeline.llm_pipeline import analyze_asset


class _FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        schema_name = kwargs.get("text", {}).get("format", {}).get("name", "")
        if schema_name == "reader_analysis":
            payload = {
                "document_type": "article",
                "thesis": "Demo thesis",
                "chapter_map": [
                    {
                        "id": "ch-1",
                        "title": "Chapter 1",
                        "summary": "Chapter 1 summary",
                        "block_ids": ["b1"],
                        "role": "argument",
                        "weight": "high",
                    }
                ],
                "argument_skeleton": [
                    {
                        "id": "arg-1",
                        "claim": "Main claim",
                        "chapter_id": "ch-1",
                        "claim_type": "fact",
                    }
                ],
                "content_signals": {
                    "evidence_density": "medium",
                    "rhetoric_density": "low",
                    "has_novel_claim": True,
                    "has_data": False,
                    "estimated_depth": "medium",
                },
            }
        elif schema_name == "content_analysis":
            payload = {
                "summary": {"headline": "Demo headline", "short_text": "Short summary"},
                "key_points": [
                    {
                        "id": "kp-1",
                        "title": "Point A",
                        "details": "Point A details",
                        "evidence_segment_ids": ["e1"],
                    }
                ],
                "analysis_items": [
                    {
                        "id": "an-1",
                        "kind": "implication",
                        "statement": "Point A",
                        "evidence_segment_ids": ["e1"],
                        "confidence": 0.9,
                    },
                    {
                        "id": "an-2",
                        "kind": "alternative",
                        "statement": "Point B",
                        "evidence_segment_ids": [],
                        "confidence": 0.6,
                    },
                ],
                "verification_items": [
                    {
                        "id": "ver-1",
                        "claim": "Claim A",
                        "status": "supported",
                        "evidence_segment_ids": ["e1"],
                        "rationale": "Evidence matches claim",
                        "confidence": 0.95,
                    },
                ],
                "synthesis": {
                    "final_answer": "Final synthesis",
                    "what_is_new": "Novel perspective on the topic",
                    "tensions": ["Tension between claim A and claim B"],
                    "next_steps": ["Review later"],
                    "open_questions": ["What is missing?"],
                },
            }
        else:
            payload = {
                "visual_findings": [
                    {
                        "id": "vf-1",
                        "finding": "Frame confirms setting",
                        "evidence_frame_paths": ["analysis/frames/frame-001.jpg"],
                    }
                ],
                "verification_adjustments": [
                    {
                        "id": "ver-2",
                        "claim": "Claim B",
                        "status": "partial",
                        "rationale": "Frame is partially consistent",
                        "evidence_frame_paths": ["analysis/frames/frame-001.jpg"],
                    }
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
    assert result.provider == "openai"
    assert result.schema_mode == "json_schema"
    assert result.content_policy_id == "video_text_first_v1"
    assert result.supported_input_modalities == ["text", "text_image"]
    assert result.text_input_modality == "text_image"
    assert result.multimodal_input_modality == "text_image"
    assert result.task_intent == "summarize_video_from_subtitle_and_whisper_transcript"
    assert result.summary == "Short summary"
    assert result.request_artifacts["text"] == "analysis/llm/text_request.json"
    assert result.request_artifacts["multimodal"] == "analysis/llm/multimodal_request.json"
    assert result.key_points[0].id == "kp-1"
    assert result.analysis_items[:2] == ["Point A", "Point B"]
    assert result.verification_items[0]["claim"] == "Claim A"
    assert result.structured_result is not None
    assert result.structured_result.summary is not None
    assert result.structured_result.summary.headline == "Demo headline"
    assert result.structured_result.synthesis is not None
    assert result.structured_result.synthesis.final_answer == "Final synthesis"
    assert result.output_path == "analysis/llm/analysis_result.json"
    assert len(fake_client.responses.calls) == 3
    assert (job_dir / "analysis" / "llm" / "analysis_result.json").exists()
    assert (job_dir / "analysis" / "llm" / "text_request.json").exists()
    assert (job_dir / "analysis" / "llm" / "multimodal_request.json").exists()
    reader_input_check = fake_client.responses.calls[0]["input"]
    reader_ctx = json.loads(reader_input_check[0]["content"][0]["text"])
    assert reader_ctx["task"]["task_id"] == "reader_pass_v1"
    assert "transcript_text" in reader_ctx["document"]
    synthesizer_input = fake_client.responses.calls[1]["input"]
    assert synthesizer_input[0]["content"][0]["type"] == "input_text"
    synthesizer_context = json.loads(synthesizer_input[0]["content"][0]["text"])
    assert synthesizer_context["task"]["task_id"] == "synthesizer_pass_v1"
    assert synthesizer_context["task"]["input_modality"] == "text_image"
    assert synthesizer_context["content_policy"]["policy_id"] == "video_text_first_v1"
    assert synthesizer_context["content_policy"]["supported_input_modalities"] == ["text", "text_image"]
    assert synthesizer_context["document"]["allowed_evidence_ids"] == ["e1"]
    assert synthesizer_context["document"]["image_inputs"] == []
    assert "reader_output" in synthesizer_context["document"]
    assert synthesizer_context["document"]["reader_output"]["document_type"] == "article"
    assert synthesizer_context["document"]["selected_block_count"] >= 1
    assert synthesizer_context["document"]["selected_evidence_count"] >= 1
    multimodal_input = fake_client.responses.calls[2]["input"]
    assert multimodal_input[0]["content"][0]["type"] == "input_text"
    multimodal_context = json.loads(multimodal_input[0]["content"][0]["text"])
    assert multimodal_context["task"]["input_modality"] == "text_image"
    assert multimodal_context["content_policy"]["policy_id"] == "video_text_first_v1"
    assert multimodal_context["document"]["image_inputs"] == ["analysis/frames/frame-001.jpg"]
    assert result.structured_result.synthesis.what_is_new == "Novel perspective on the topic"
    assert result.structured_result.synthesis.tensions == ["Tension between claim A and claim B"]
    assert result.structured_result.chapter_map[0].id == "ch-1"
    assert result.reader_result_path == "analysis/llm/reader_result.json"
    assert result.synthesizer_result_path == "analysis/llm/synthesizer_result.json"
    assert (job_dir / "analysis" / "llm" / "reader_result.json").exists()
    assert (job_dir / "analysis" / "llm" / "synthesizer_result.json").exists()
    analysis_result_payload = json.loads((job_dir / "analysis" / "llm" / "analysis_result.json").read_text(encoding="utf-8"))
    assert analysis_result_payload["reader_result_path"] == "analysis/llm/reader_result.json"
    assert analysis_result_payload["synthesizer_result_path"] == "analysis/llm/synthesizer_result.json"
    assert analysis_result_payload["result"]["chapter_map"][0]["id"] == "ch-1"
    assert analysis_result_payload["result"]["synthesis"]["what_is_new"] == "Novel perspective on the topic"
    assert analysis_result_payload["result"]["synthesis"]["tensions"] == ["Tension between claim A and claim B"]


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
    assert result.skip_reason == "missing OPENAI_API_KEY"
    assert result.schema_mode == "json_schema"
    assert result.content_policy_id == "article_text_first_v1"
    assert result.supported_input_modalities == ["text", "image", "text_image"]
    assert result.text_input_modality == "text_image"
    assert result.multimodal_input_modality == "text_image"
    assert result.task_intent == "summarize_article_with_optional_image_grounding"
    assert result.request_artifacts == {}
    assert result.warnings


def test_analyze_asset_cleans_invalid_evidence_references(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    settings = load_settings()

    class _InvalidResponses:
        def create(self, **kwargs):
            payload = {
                "summary": {"headline": "Headline", "short_text": "Summary"},
                "key_points": [
                    {
                        "id": "kp-1",
                        "title": "Point A",
                        "details": "Details",
                        "evidence_segment_ids": ["missing-id", "e1"],
                    }
                ],
                "analysis_items": [
                    {
                        "id": "an-1",
                        "kind": "fact",
                        "statement": "Statement",
                        "evidence_segment_ids": ["missing-id"],
                        "confidence": 0.8,
                    }
                ],
                "verification_items": [
                    {
                        "id": "ver-1",
                        "claim": "Claim A",
                        "status": "supported",
                        "evidence_segment_ids": ["missing-id"],
                        "rationale": "Model claimed evidence exists",
                        "confidence": 0.9,
                    }
                ],
                "synthesis": {
                    "final_answer": "Answer",
                    "next_steps": [],
                    "open_questions": [],
                },
            }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class _InvalidClient:
        def __init__(self) -> None:
            self.responses = _InvalidResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: _InvalidClient())

    asset = ContentAsset(
        source_platform="generic",
        source_url="https://example.com",
        title="Demo",
        content_text="hello",
        evidence_segments=[EvidenceSegment(id="e1", kind="text_block", text="Evidence 1", source="paragraph-1")],
    )

    result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)

    assert result.status == "pass"
    assert result.structured_result is not None
    assert result.structured_result.key_points[0].evidence_segment_ids == ["e1"]
    assert result.structured_result.analysis_items[0].evidence_segment_ids == []
    assert result.structured_result.verification_items[0].evidence_segment_ids == []
    assert result.structured_result.verification_items[0].status == "unclear"
    assert result.structured_result.warnings
    assert result.structured_result.warnings[0].code == "invalid_evidence_reference"
    assert result.structured_result.warnings[0].severity == "warn"
    assert result.structured_result.warnings[0].related_refs[0].kind in {"key_point", "analysis_item", "verification_item"}
    assert result.structured_result.warnings[0].related_refs[0].id in {"kp-1", "an-1", "ver-1"}
    assert result.structured_result.warnings[0].related_refs[1].kind == "evidence_segment"
    assert result.structured_result.warnings[0].related_refs[1].id == "missing-id"
    assert any("unknown evidence id" in warning for warning in result.warnings)


def test_analyze_asset_repairs_invalid_evidence_references(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    settings = load_settings()

    class _RepairResponses:
        def __init__(self) -> None:
            self.call_count = 0

        def create(self, **kwargs):
            self.call_count += 1
            if self.call_count == 1:
                payload = {
                    "summary": {"headline": "Headline", "short_text": "Summary"},
                    "key_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["missing-id"],
                        }
                    ],
                    "analysis_items": [
                        {
                            "id": "an-1",
                            "kind": "fact",
                            "statement": "Statement",
                            "evidence_segment_ids": ["missing-id"],
                            "confidence": 0.8,
                        }
                    ],
                    "verification_items": [
                        {
                            "id": "ver-1",
                            "claim": "Claim A",
                            "status": "supported",
                            "evidence_segment_ids": ["missing-id"],
                            "rationale": "Initial invalid reference",
                            "confidence": 0.9,
                        }
                    ],
                    "synthesis": {
                        "final_answer": "Answer",
                        "next_steps": [],
                        "open_questions": [],
                    },
                }
            else:
                payload = {
                    "summary": {"headline": "Headline", "short_text": "Summary"},
                    "key_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["e1"],
                        }
                    ],
                    "analysis_items": [
                        {
                            "id": "an-1",
                            "kind": "fact",
                            "statement": "Statement",
                            "evidence_segment_ids": ["e1"],
                            "confidence": 0.8,
                        }
                    ],
                    "verification_items": [
                        {
                            "id": "ver-1",
                            "claim": "Claim A",
                            "status": "supported",
                            "evidence_segment_ids": ["e1"],
                            "rationale": "Repaired reference",
                            "confidence": 0.9,
                        }
                    ],
                    "synthesis": {
                        "final_answer": "Answer",
                        "next_steps": [],
                        "open_questions": [],
                    },
                }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class _RepairClient:
        def __init__(self) -> None:
            self.responses = _RepairResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: _RepairClient())

    asset = ContentAsset(
        source_platform="generic",
        source_url="https://example.com",
        title="Demo",
        content_text="hello",
        evidence_segments=[EvidenceSegment(id="e1", kind="text_block", text="Evidence 1", source="paragraph-1")],
    )

    result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)

    assert result.status == "pass"
    assert result.structured_result is not None
    assert result.structured_result.key_points[0].evidence_segment_ids == ["e1"]
    assert result.structured_result.analysis_items[0].evidence_segment_ids == ["e1"]
    assert result.structured_result.verification_items[0].evidence_segment_ids == ["e1"]
    assert result.structured_result.verification_items[0].status == "supported"
    assert not any("unknown evidence id" in warning for warning in result.warnings)


def test_llm_contract_resolves_input_policy_by_content_shape(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = load_settings()

    article_asset = ContentAsset(
        source_platform="wechat",
        source_url="https://example.com/article",
        content_shape="article",
        title="Article",
        content_text="Article body",
    )
    video_asset = ContentAsset(
        source_platform="bilibili",
        source_url="https://example.com/video",
        content_shape="video",
        title="Video",
        content_text="Video page",
    )
    audio_asset = ContentAsset(
        source_platform="podcast",
        source_url="https://example.com/audio",
        content_shape="audio",
        title="Audio",
        content_text="Audio page",
    )

    assert resolve_content_policy(article_asset).policy_id == "article_text_first_v1"
    assert resolve_content_policy(video_asset).policy_id == "video_text_first_v1"
    assert resolve_content_policy(audio_asset).policy_id == "audio_text_only_v1"

    article_envelope = build_text_analysis_envelope(
        asset=article_asset,
        job_dir=None,
        settings=settings,
        model=settings.analysis_model,
        output_schema_name="content_analysis",
    )
    audio_envelope = build_text_analysis_envelope(
        asset=audio_asset,
        job_dir=None,
        settings=settings,
        model=settings.analysis_model,
        output_schema_name="content_analysis",
    )

    assert article_envelope.task.input_modality == "text_image"
    assert article_envelope.content_policy.supported_input_modalities == ["text", "image", "text_image"]
    assert article_envelope.task_intent == "summarize_article_with_optional_image_grounding"
    assert article_envelope.content_policy.table_representation == "image"
    assert audio_envelope.task.input_modality == "text_image"
    assert audio_envelope.content_policy.supported_input_modalities == ["text", "text_image"]
    assert audio_envelope.task_intent == "summarize_and_verify_audio_transcript"


def test_text_analysis_envelope_includes_content_images_but_not_analysis_frames(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    settings = load_settings()

    article_dir = tmp_path / "job" / "attachments"
    image_dir = article_dir / "images"
    frame_dir = tmp_path / "job" / "analysis" / "frames"
    image_dir.mkdir(parents=True)
    frame_dir.mkdir(parents=True)
    content_image = image_dir / "figure-1.jpg"
    analysis_frame = frame_dir / "frame-001.jpg"
    content_image.write_bytes(b"jpeg-bytes")
    analysis_frame.write_bytes(b"frame-bytes")

    asset = ContentAsset(
        source_platform="wechat",
        source_url="https://example.com/article",
        content_shape="article",
        title="Article",
        content_text="Article body",
        attachments=[
            ContentAttachment(
                id="img-1",
                path="attachments/images/figure-1.jpg",
                role="content_image",
                media_type="image/jpeg",
                kind="image",
            ),
            ContentAttachment(
                id="frame-1",
                path="analysis/frames/frame-001.jpg",
                role="analysis_frame",
                media_type="image/jpeg",
                kind="image",
            ),
        ],
    )

    envelope = build_text_analysis_envelope(
        asset=asset,
        job_dir=tmp_path / "job",
        settings=settings,
        model=settings.analysis_model,
        output_schema_name="content_analysis",
    )

    assert envelope.task.input_modality == "text_image"
    assert envelope.image_paths == [str(content_image)]
    assert envelope.document["image_inputs"] == ["figure-1.jpg"]


def test_analyze_asset_repair_preserves_chapter_map(monkeypatch, tmp_path: Path) -> None:
    """Repair path must pass reader_payload through so chapter_map is not lost."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    settings = load_settings()

    class _RepairWithReaderResponses:
        def __init__(self) -> None:
            self.call_count = 0

        def create(self, **kwargs):
            self.call_count += 1
            schema_name = kwargs.get("text", {}).get("format", {}).get("name", "")
            if schema_name == "reader_analysis":
                payload = {
                    "document_type": "article",
                    "thesis": "Test thesis",
                    "chapter_map": [
                        {
                            "id": "ch-1",
                            "title": "Chapter 1",
                            "summary": "Summary of chapter 1",
                            "block_ids": ["b1"],
                            "role": "argument",
                            "weight": "high",
                        }
                    ],
                    "argument_skeleton": [],
                    "content_signals": {
                        "evidence_density": "medium",
                        "rhetoric_density": "low",
                        "has_novel_claim": False,
                        "has_data": False,
                        "estimated_depth": "medium",
                    },
                }
            elif self.call_count == 2:
                # First synthesizer call — invalid evidence
                payload = {
                    "summary": {"headline": "Headline", "short_text": "Summary"},
                    "key_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["missing-id"],
                        }
                    ],
                    "analysis_items": [],
                    "verification_items": [],
                    "synthesis": {
                        "final_answer": "Answer",
                        "what_is_new": "Something new",
                        "tensions": [],
                        "next_steps": [],
                        "open_questions": [],
                    },
                }
            else:
                # Repair call — valid evidence
                payload = {
                    "summary": {"headline": "Headline", "short_text": "Summary"},
                    "key_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["e1"],
                        }
                    ],
                    "analysis_items": [],
                    "verification_items": [],
                    "synthesis": {
                        "final_answer": "Answer",
                        "what_is_new": "Something new",
                        "tensions": [],
                        "next_steps": [],
                        "open_questions": [],
                    },
                }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class _RepairWithReaderClient:
        def __init__(self) -> None:
            self.responses = _RepairWithReaderResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr(
        "content_ingestion.pipeline.llm_pipeline._create_client",
        lambda settings: _RepairWithReaderClient(),
    )

    asset = ContentAsset(
        source_platform="generic",
        source_url="https://example.com",
        title="Demo",
        content_text="hello",
        blocks=[ContentBlock(id="b1", kind="paragraph", text="Paragraph 1")],
        evidence_segments=[EvidenceSegment(id="e1", kind="text_block", text="Evidence 1", source="paragraph-1")],
    )

    result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)

    assert result.status == "pass"
    assert result.structured_result is not None
    # chapter_map must survive the repair path
    assert len(result.structured_result.chapter_map) == 1
    assert result.structured_result.chapter_map[0].id == "ch-1"
    assert result.structured_result.key_points[0].evidence_segment_ids == ["e1"]
    analysis_result_payload = json.loads((tmp_path / "analysis" / "llm" / "analysis_result.json").read_text(encoding="utf-8"))
    assert analysis_result_payload["result"]["chapter_map"][0]["id"] == "ch-1"
    assert analysis_result_payload["result"]["synthesis"]["what_is_new"] == "Something new"
