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
                "suggested_reading_goal": "argument",
                "goal_confidence": 0.82,
                "suggested_domain_template": "generic",
                "domain_confidence": 0.82,
            }
        elif schema_name == "content_analysis":
            payload = {
                "core_summary": "Short summary",
                "bottom_line": "Final synthesis",
                "content_kind": "analysis",
                "author_stance": "critical",
                "audience_fit": "Readers who want a fast argument map.",
                "save_worthy_points": ["Point A", "Point B"],
                "author_thesis": "Demo headline",
                "evidence_backed_points": [
                    {
                        "id": "kp-1",
                        "title": "Point A",
                        "details": "Point A details",
                        "evidence_segment_ids": ["e1"],
                    }
                ],
                "interpretive_points": [
                    {
                        "id": "an-1",
                        "kind": "implication",
                        "statement": "Point A",
                        "evidence_segment_ids": ["e1"],
                    },
                    {
                        "id": "an-2",
                        "kind": "alternative",
                        "statement": "Point B",
                        "evidence_segment_ids": [],
                    },
                ],
                "what_is_new": "Novel perspective on the topic",
                "tensions": ["Tension between claim A and claim B"],
                "uncertainties": ["What is missing?"],
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
    monkeypatch.delenv("ZENMUX_API_KEY", raising=False)
    monkeypatch.delenv("ZENMUX_BASE_URL", raising=False)
    monkeypatch.delenv("ZENMUX_ANALYSIS_MODEL", raising=False)
    monkeypatch.delenv("ZENMUX_MULTIMODAL_MODEL", raising=False)
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
    assert result.requested_reading_goal is None
    assert result.resolved_reading_goal == "argument"
    assert result.goal_confidence == 0.82
    assert result.requested_domain_template is None
    assert result.resolved_domain_template == "generic"
    assert result.domain_confidence == 0.82
    assert result.route_key == "argument.generic"
    assert result.structured_result.editorial is not None
    assert result.structured_result.editorial.requested_reading_goal is None
    assert result.structured_result.editorial.resolved_reading_goal == "argument"
    assert result.structured_result.editorial.goal_confidence == 0.82
    assert result.structured_result.editorial.resolved_domain_template == "generic"
    assert result.structured_result.editorial.domain_confidence == 0.82
    assert result.structured_result.editorial.route_key == "argument.generic"
    assert result.structured_result.product_view is not None
    assert result.structured_result.product_view.layout == "analysis_brief"
    assert result.reader_result_path == "analysis/llm/reader_result.json"
    assert result.synthesizer_result_path == "analysis/llm/synthesizer_result.json"
    assert (job_dir / "analysis" / "llm" / "reader_result.json").exists()
    assert (job_dir / "analysis" / "llm" / "synthesizer_result.json").exists()
    analysis_result_payload = json.loads((job_dir / "analysis" / "llm" / "analysis_result.json").read_text(encoding="utf-8"))
    assert analysis_result_payload["reader_result_path"] == "analysis/llm/reader_result.json"
    assert analysis_result_payload["synthesizer_result_path"] == "analysis/llm/synthesizer_result.json"
    assert analysis_result_payload["requested_reading_goal"] is None
    assert analysis_result_payload["resolved_reading_goal"] == "argument"
    assert analysis_result_payload["goal_confidence"] == 0.82
    assert analysis_result_payload["requested_domain_template"] is None
    assert analysis_result_payload["resolved_domain_template"] == "generic"
    assert analysis_result_payload["domain_confidence"] == 0.82
    assert analysis_result_payload["route_key"] == "argument.generic"
    assert analysis_result_payload["result"]["chapter_map"][0]["id"] == "ch-1"
    assert analysis_result_payload["result"]["synthesis"]["what_is_new"] == "Novel perspective on the topic"
    assert analysis_result_payload["result"]["synthesis"]["tensions"] == ["Tension between claim A and claim B"]
    assert analysis_result_payload["result"]["editorial"]["requested_reading_goal"] is None
    assert analysis_result_payload["result"]["editorial"]["resolved_reading_goal"] == "argument"
    assert analysis_result_payload["result"]["editorial"]["goal_confidence"] == 0.82
    assert analysis_result_payload["result"]["editorial"]["resolved_domain_template"] == "generic"
    assert analysis_result_payload["result"]["editorial"]["domain_confidence"] == 0.82
    assert analysis_result_payload["result"]["editorial"]["route_key"] == "argument.generic"
    assert analysis_result_payload["result"]["product_view"]["layout"] == "analysis_brief"
    assert analysis_result_payload["result"]["product_view"]["template"] == "argument.generic"


def test_analyze_asset_skips_without_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ZENMUX_API_KEY", raising=False)
    monkeypatch.delenv("ZENMUX_BASE_URL", raising=False)
    monkeypatch.delenv("ZENMUX_ANALYSIS_MODEL", raising=False)
    monkeypatch.delenv("ZENMUX_MULTIMODAL_MODEL", raising=False)
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


def test_reader_schema_has_routing_v2_fields() -> None:
    from content_ingestion.pipeline.llm_pipeline import READER_SCHEMA

    props = READER_SCHEMA["properties"]
    assert "suggested_reading_goal" in props
    assert props["suggested_reading_goal"]["type"] == "string"
    assert set(props["suggested_reading_goal"]["enum"]) == {"argument", "guide", "review", "narrative"}
    assert "suggested_domain_template" in props
    assert props["suggested_domain_template"]["type"] == "string"
    assert set(props["suggested_domain_template"]["enum"]) == {
        "politics_public_issue",
        "macro_business",
        "game_guide",
        "personal_narrative",
        "generic",
    }
    assert "domain_confidence" in props
    assert props["domain_confidence"]["type"] == "number"
    assert "goal_confidence" in props
    assert props["goal_confidence"]["type"] == "number"
    assert "suggested_reading_goal" in READER_SCHEMA["required"]
    assert "suggested_domain_template" in READER_SCHEMA["required"]
    assert "domain_confidence" in READER_SCHEMA["required"]
    assert "goal_confidence" in READER_SCHEMA["required"]


def test_resolve_routing_honors_explicit_reading_goal_override() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="guide",
        requested_domain_template=None,
        reader_payload={
            "suggested_reading_goal": "review",
            "suggested_domain_template": "macro_business",
            "goal_confidence": 0.73,
            "domain_confidence": 0.91,
        },
    )

    assert route.reading_goal == "guide"
    assert route.domain_template == "generic"
    assert route.route_key == "guide.generic"
    assert route.goal_confidence == 1.0
    assert route.requested_reading_goal == "guide"


def test_resolve_routing_honors_explicit_domain_override_when_provided() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="auto",
        requested_domain_template="macro_business",
        reader_payload={
            "suggested_reading_goal": "argument",
            "suggested_domain_template": "generic",
            "goal_confidence": 0.66,
            "domain_confidence": 0.4,
        },
    )

    assert route.reading_goal == "argument"
    assert route.domain_template == "macro_business"
    assert route.route_key == "argument.macro_business"


def test_resolve_routing_uses_reader_suggestion_for_auto_goal() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="auto",
        requested_domain_template=None,
        reader_payload={
            "suggested_reading_goal": "review",
            "suggested_domain_template": "generic",
            "goal_confidence": 0.88,
            "domain_confidence": 0.88,
        },
    )

    assert route.reading_goal == "review"
    assert route.domain_template == "generic"
    assert route.route_key == "review.generic"
    assert route.goal_confidence == 0.88


def test_resolve_routing_falls_back_to_legacy_v1_reader_keys() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="auto",
        requested_domain_template=None,
        reader_payload={
            "suggested_mode": "guide",
            "mode_confidence": 0.64,
        },
    )

    assert route.reading_goal == "guide"
    assert route.goal_confidence == 0.64
    assert route.domain_template == "generic"
    assert route.route_key == "guide.generic"


def test_resolve_routing_preserves_explicit_zero_confidence() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="auto",
        requested_domain_template=None,
        reader_payload={
            "suggested_reading_goal": "review",
            "suggested_domain_template": "macro_business",
            "goal_confidence": 0.0,
            "domain_confidence": 0.0,
        },
    )

    assert route.reading_goal == "review"
    assert route.goal_confidence == 0.0
    assert route.domain_confidence == 0.0
    assert route.domain_template == "generic"
    assert route.route_key == "review.generic"


def test_analyze_asset_preserves_legacy_v1_routing_in_result_metadata(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    settings = load_settings()

    class _LegacyRoutingResponses:
        def create(self, **kwargs):
            schema_name = kwargs.get("text", {}).get("format", {}).get("name", "")
            if schema_name == "reader_analysis":
                payload = {
                    "document_type": "tutorial",
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
                        "has_novel_claim": False,
                        "has_data": False,
                        "estimated_depth": "medium",
                    },
                    "suggested_mode": "guide",
                    "mode_confidence": 0.64,
                }
            else:
                payload = {
                    "core_summary": "Guide summary",
                    "bottom_line": "Try the first step",
                    "content_kind": "tutorial",
                    "author_stance": "explanatory",
                    "audience_fit": "new readers",
                    "save_worthy_points": ["Start simple"],
                    "guide_goal": "learn the flow",
                    "recommended_steps": ["Step 1", "Step 2"],
                    "tips": ["Tip A"],
                    "pitfalls": ["Pitfall A"],
                    "prerequisites": ["Prereq A"],
                    "quick_win": "Begin with Step 1",
                }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class _LegacyRoutingClient:
        def __init__(self) -> None:
            self.responses = _LegacyRoutingResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: _LegacyRoutingClient())

    asset = ContentAsset(
        source_platform="generic",
        source_url="https://example.com/tutorial",
        title="Demo Tutorial",
        content_text="hello",
        blocks=[ContentBlock(id="b1", kind="paragraph", text="Paragraph 1")],
    )

    result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)

    assert result.status == "pass"
    assert result.requested_mode == "auto"
    assert result.resolved_mode == "guide"
    assert result.mode_confidence == 0.64
    assert result.requested_reading_goal is None
    assert result.resolved_reading_goal == "guide"
    assert result.goal_confidence == 0.64
    assert result.requested_domain_template is None
    assert result.resolved_domain_template == "generic"
    assert result.domain_confidence == 0.0
    assert result.route_key == "guide.generic"
    assert result.structured_result is not None
    assert result.structured_result.editorial is not None
    assert result.structured_result.editorial.requested_mode == "auto"
    assert result.structured_result.editorial.resolved_mode == "guide"
    assert result.structured_result.editorial.mode_confidence == 0.64
    assert result.structured_result.editorial.requested_reading_goal is None
    assert result.structured_result.editorial.resolved_reading_goal == "guide"
    assert result.structured_result.editorial.goal_confidence == 0.64
    assert result.structured_result.editorial.resolved_domain_template == "generic"
    assert result.structured_result.editorial.route_key == "guide.generic"
    analysis_result_payload = json.loads((tmp_path / "analysis" / "llm" / "analysis_result.json").read_text(encoding="utf-8"))
    assert analysis_result_payload["resolved_mode"] == "guide"
    assert analysis_result_payload["mode_confidence"] == 0.64
    assert analysis_result_payload["resolved_reading_goal"] == "guide"
    assert analysis_result_payload["goal_confidence"] == 0.64
    assert analysis_result_payload["resolved_domain_template"] == "generic"
    assert analysis_result_payload["route_key"] == "guide.generic"
    assert analysis_result_payload["result"]["editorial"]["resolved_mode"] == "guide"
    assert analysis_result_payload["result"]["editorial"]["mode_confidence"] == 0.64
    assert analysis_result_payload["result"]["editorial"]["resolved_reading_goal"] == "guide"
    assert analysis_result_payload["result"]["editorial"]["goal_confidence"] == 0.64
    assert analysis_result_payload["result"]["editorial"]["route_key"] == "guide.generic"


def test_analyze_asset_bridges_narrative_route_to_legacy_argument_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    settings = load_settings()

    class _NarrativeRoutingResponses:
        def create(self, **kwargs):
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
                            "role": "setup",
                            "weight": "high",
                        }
                    ],
                    "argument_skeleton": [
                        {
                            "id": "arg-1",
                            "claim": "Main claim",
                            "chapter_id": "ch-1",
                            "claim_type": "interpretation",
                        }
                    ],
                    "content_signals": {
                        "evidence_density": "low",
                        "rhetoric_density": "medium",
                        "has_novel_claim": False,
                        "has_data": False,
                        "estimated_depth": "medium",
                    },
                    "suggested_reading_goal": "narrative",
                    "goal_confidence": 0.91,
                    "suggested_domain_template": "personal_narrative",
                    "domain_confidence": 0.91,
                }
            else:
                payload = {
                    "core_summary": "Narrative summary",
                    "bottom_line": "Personal takeaway",
                    "content_kind": "article",
                    "author_stance": "mixed",
                    "audience_fit": "general readers",
                    "save_worthy_points": ["Point A"],
                    "author_thesis": "Narrative headline",
                    "evidence_backed_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Point A details",
                            "evidence_segment_ids": [],
                        }
                    ],
                    "interpretive_points": [
                        {
                            "id": "an-1",
                            "kind": "implication",
                            "statement": "Point A",
                            "evidence_segment_ids": [],
                        }
                    ],
                    "what_is_new": "A personal angle",
                    "tensions": [],
                    "uncertainties": [],
                    "verification_items": [],
                }
            return type("Response", (), {"output_text": json.dumps(payload, ensure_ascii=False)})()

    class _NarrativeRoutingClient:
        def __init__(self) -> None:
            self.responses = _NarrativeRoutingResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: _NarrativeRoutingClient())

    asset = ContentAsset(
        source_platform="generic",
        source_url="https://example.com/story",
        title="Demo Story",
        content_text="hello",
        blocks=[ContentBlock(id="b1", kind="paragraph", text="Paragraph 1")],
    )

    result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)

    assert result.status == "pass"
    assert result.requested_mode == "auto"
    assert result.requested_reading_goal is None
    assert result.resolved_reading_goal == "narrative"
    assert result.goal_confidence == 0.91
    assert result.resolved_domain_template == "personal_narrative"
    assert result.domain_confidence == 0.91
    assert result.route_key == "narrative.personal_narrative"
    assert result.resolved_mode == "argument"
    assert result.mode_confidence == 0.91
    assert result.structured_result is not None
    assert result.structured_result.editorial is not None
    assert result.structured_result.editorial.requested_reading_goal is None
    assert result.structured_result.editorial.resolved_reading_goal == "narrative"
    assert result.structured_result.editorial.goal_confidence == 0.91
    assert result.structured_result.editorial.resolved_domain_template == "personal_narrative"
    assert result.structured_result.editorial.domain_confidence == 0.91
    assert result.structured_result.editorial.route_key == "narrative.personal_narrative"
    assert result.structured_result.editorial.resolved_mode == "argument"
    analysis_result_payload = json.loads((tmp_path / "analysis" / "llm" / "analysis_result.json").read_text(encoding="utf-8"))
    assert analysis_result_payload["requested_reading_goal"] is None
    assert analysis_result_payload["resolved_reading_goal"] == "narrative"
    assert analysis_result_payload["goal_confidence"] == 0.91
    assert analysis_result_payload["resolved_domain_template"] == "personal_narrative"
    assert analysis_result_payload["domain_confidence"] == 0.91
    assert analysis_result_payload["route_key"] == "narrative.personal_narrative"
    assert analysis_result_payload["resolved_mode"] == "argument"
    assert analysis_result_payload["mode_confidence"] == 0.91
    assert analysis_result_payload["result"]["editorial"]["requested_reading_goal"] is None
    assert analysis_result_payload["result"]["editorial"]["resolved_reading_goal"] == "narrative"
    assert analysis_result_payload["result"]["editorial"]["goal_confidence"] == 0.91
    assert analysis_result_payload["result"]["editorial"]["resolved_domain_template"] == "personal_narrative"
    assert analysis_result_payload["result"]["editorial"]["domain_confidence"] == 0.91
    assert analysis_result_payload["result"]["editorial"]["route_key"] == "narrative.personal_narrative"
    assert analysis_result_payload["result"]["editorial"]["resolved_mode"] == "argument"


def test_resolve_routing_falls_back_to_argument_when_goal_invalid() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="auto",
        requested_domain_template=None,
        reader_payload={
            "suggested_reading_goal": "informational",
            "suggested_domain_template": "macro_business",
            "goal_confidence": 0.93,
            "domain_confidence": 0.93,
        },
    )

    assert route.reading_goal == "argument"
    assert route.domain_template == "macro_business"
    assert route.route_key == "argument.macro_business"
    assert route.goal_confidence == 0.5


def test_resolve_routing_falls_back_to_generic_for_low_domain_confidence() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="auto",
        requested_domain_template=None,
        reader_payload={
            "suggested_reading_goal": "argument",
            "suggested_domain_template": "macro_business",
            "goal_confidence": 0.71,
            "domain_confidence": 0.2,
        },
    )

    assert route.reading_goal == "argument"
    assert route.domain_template == "generic"
    assert route.route_key == "argument.generic"


def test_resolve_routing_falls_back_to_goal_generic_for_unsupported_combo() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_reading_goal="review",
        requested_domain_template="macro_business",
        reader_payload={
            "suggested_reading_goal": "review",
            "suggested_domain_template": "macro_business",
            "goal_confidence": 0.97,
            "domain_confidence": 0.97,
        },
    )

    assert route.reading_goal == "review"
    assert route.domain_template == "generic"
    assert route.route_key == "review.generic"


def test_resolve_routing_uses_requested_mode_as_compatibility_bridge() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_mode="guide",
        reader_payload={
            "suggested_reading_goal": "argument",
            "suggested_domain_template": "game_guide",
            "goal_confidence": 0.94,
            "domain_confidence": 0.94,
        },
    )

    assert route.reading_goal == "guide"
    assert route.domain_template == "game_guide"
    assert route.route_key == "guide.game_guide"
    assert route.requested_reading_goal is None


def test_resolve_routing_keeps_requested_mode_separate_from_requested_reading_goal() -> None:
    from content_ingestion.pipeline.llm_pipeline import _resolve_routing

    route = _resolve_routing(
        requested_mode="review",
        reader_payload={
            "suggested_reading_goal": "argument",
            "suggested_domain_template": "generic",
            "goal_confidence": 0.94,
            "domain_confidence": 0.94,
        },
    )

    assert route.reading_goal == "review"
    assert route.requested_reading_goal is None


def test_editorial_result_dataclasses_exist() -> None:
    from content_ingestion.core.models import EditorialBase, EditorialResult, StructuredResult

    base = EditorialBase(
        core_summary="summary",
        bottom_line="bottom line",
        audience_fit="general readers",
        save_worthy_points=["point-1"],
    )
    editorial = EditorialResult(
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.83,
        base=base,
        mode_payload={"author_thesis": "test thesis"},
    )
    result = StructuredResult(editorial=editorial)

    assert result.editorial is not None
    assert result.editorial.resolved_mode == "argument"
    assert result.editorial.base.core_summary == "summary"
    assert result.editorial.mode_payload["author_thesis"] == "test thesis"


def test_build_structured_result_argument_mode_builds_editorial() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "summary",
        "bottom_line": "bottom",
        "content_kind": "analysis",
        "author_stance": "critical",
        "audience_fit": "macro readers",
        "save_worthy_points": ["point-1"],
        "author_thesis": "thesis",
        "evidence_backed_points": [
            {"id": "ep-1", "title": "Point A", "details": "A detail", "evidence_segment_ids": ["e1"]}
        ],
        "interpretive_points": [
            {"id": "ip-1", "statement": "Implication A", "kind": "implication", "evidence_segment_ids": ["e1"]}
        ],
        "what_is_new": "new thing",
        "tensions": ["tension-1"],
        "uncertainties": ["uncertainty-1"],
        "verification_items": [],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="argument",
            domain_template="generic",
            route_key="argument.generic",
            goal_confidence=0.72,
            domain_confidence=0.61,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.72,
    )

    assert result.editorial is not None
    assert result.editorial.requested_mode == "auto"
    assert result.editorial.resolved_mode == "argument"
    assert result.editorial.mode_confidence == 0.72
    assert result.editorial.base.core_summary == "summary"
    assert result.editorial.mode_payload["author_thesis"] == "thesis"
    assert result.editorial.mode_payload["what_is_new"] == "new thing"
    assert result.editorial.mode_payload["tensions"] == ["tension-1"]


def test_build_structured_result_guide_mode_builds_editorial() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "guide summary",
        "bottom_line": "do X",
        "content_kind": "tutorial",
        "author_stance": "explanatory",
        "audience_fit": "players",
        "save_worthy_points": ["tip-1"],
        "guide_goal": "learn Y",
        "recommended_steps": ["Step 1", "Step 2"],
        "tips": ["Tip A"],
        "pitfalls": ["Pitfall A"],
        "prerequisites": ["Need account"],
        "quick_win": "Start with stage 1",
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="guide",
            domain_template="generic",
            route_key="guide.generic",
            goal_confidence=1.0,
            domain_confidence=0.0,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="guide",
        resolved_mode="guide",
        mode_confidence=1.0,
    )

    assert result.editorial is not None
    assert result.editorial.resolved_mode == "guide"
    assert result.editorial.mode_payload["guide_goal"] == "learn Y"
    assert result.editorial.mode_payload["recommended_steps"] == ["Step 1", "Step 2"]


def test_build_structured_result_review_mode_builds_editorial() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "review summary",
        "bottom_line": "worth trying",
        "content_kind": "review",
        "author_stance": "mixed",
        "audience_fit": "fans of ambient music",
        "save_worthy_points": ["highlight-1"],
        "overall_judgment": "excellent",
        "highlights": ["Great production"],
        "style_and_mood": "warm and spacious",
        "what_stands_out": "texture",
        "who_it_is_for": "ambient listeners",
        "reservation_points": ["slow pacing"],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="review",
            domain_template="generic",
            route_key="review.generic",
            goal_confidence=1.0,
            domain_confidence=0.0,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="review",
        resolved_mode="review",
        mode_confidence=1.0,
    )

    assert result.editorial is not None
    assert result.editorial.resolved_mode == "review"
    assert result.editorial.mode_payload["overall_judgment"] == "excellent"
    assert result.editorial.mode_payload["highlights"] == ["Great production"]


def test_build_structured_result_builds_specialized_product_view_for_politics_argument() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "Policy proposal summary",
        "bottom_line": "The proposal is directionally strong but underspecified on costs.",
        "content_kind": "analysis",
        "author_stance": "critical",
        "audience_fit": "readers tracking public policy arguments",
        "save_worthy_points": ["The fiscal tradeoff is central."],
        "author_thesis": "The policy could help, but the current case is incomplete.",
        "evidence_backed_points": [
            {
                "id": "kp-1",
                "title": "Cost assumptions are thin",
                "details": "The author cites benefits more clearly than financing details.",
                "evidence_segment_ids": ["e1"],
            }
        ],
        "interpretive_points": [
            {
                "id": "an-1",
                "statement": "Implementation risk is understated.",
                "kind": "implication",
                "evidence_segment_ids": ["e1"],
            }
        ],
        "what_is_new": "It combines local budget pressure with service-quality concerns.",
        "tensions": ["The piece calls for urgency while omitting a concrete funding path."],
        "uncertainties": ["How the policy would be paid for across regions."],
        "verification_items": [
            {
                "id": "ver-1",
                "claim": "The proposal reduces wait times.",
                "status": "partial",
                "evidence_segment_ids": ["e1"],
                "rationale": "The evidence is suggestive rather than conclusive.",
                "confidence": 0.7,
            }
        ],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="argument",
            domain_template="politics_public_issue",
            route_key="argument.politics_public_issue",
            goal_confidence=0.88,
            domain_confidence=0.84,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.88,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "analysis_brief"
    assert result.product_view.template == "argument.politics_public_issue"
    assert result.product_view.title == "The policy could help, but the current case is incomplete."
    assert result.product_view.sections[0].kind == "summary"
    assert result.product_view.sections[1].kind == "key_points"
    assert result.product_view.sections[2].kind == "verification"
    assert result.product_view.sections[3].kind == "tensions"


def test_build_structured_result_builds_specialized_product_view_for_macro_business_argument() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "Macro summary",
        "bottom_line": "The analysis is useful, but recession timing remains uncertain.",
        "content_kind": "analysis",
        "author_stance": "skeptical",
        "audience_fit": "readers following the macro cycle",
        "save_worthy_points": ["Credit conditions matter more than headline inflation."],
        "author_thesis": "The cycle is slowing, but not all indicators point the same way.",
        "evidence_backed_points": [
            {
                "id": "kp-1",
                "title": "Labor remains firmer than expected",
                "details": "The labor market data complicates the bearish call.",
                "evidence_segment_ids": ["e1"],
            }
        ],
        "interpretive_points": [
            {
                "id": "an-1",
                "statement": "Risk assets may be mispricing the timing of the slowdown.",
                "kind": "alternative",
                "evidence_segment_ids": [],
            }
        ],
        "what_is_new": "It ties credit tightening to lagging consumer weakness.",
        "tensions": ["Soft-landing language conflicts with the severity of the downside case."],
        "uncertainties": ["Whether policy easing arrives before earnings weaken."],
        "verification_items": [],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="argument",
            domain_template="macro_business",
            route_key="argument.macro_business",
            goal_confidence=0.86,
            domain_confidence=0.83,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.86,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "analysis_brief"
    assert result.product_view.template == "argument.macro_business"
    assert result.product_view.sections[0].kind == "summary"
    assert result.product_view.sections[1].kind == "key_points"
    assert result.product_view.sections[2].kind == "implications"
    assert result.product_view.sections[3].kind == "uncertainties"


def test_build_structured_result_builds_specialized_product_view_for_game_guide() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "Route summary",
        "bottom_line": "Focus on stamina upgrades before the boss rush.",
        "content_kind": "tutorial",
        "author_stance": "explanatory",
        "audience_fit": "players learning the midgame route",
        "save_worthy_points": ["You can skip an early grind."],
        "guide_goal": "Reach the midgame quickly with a safe build.",
        "recommended_steps": ["Unlock the canyon shortcut.", "Buy the second stamina upgrade."],
        "tips": ["Use the merchant reset after each miniboss."],
        "pitfalls": ["Do not spend shards on early weapons."],
        "prerequisites": ["Finish the tutorial temple."],
        "quick_win": "Grab the free map item first.",
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="guide",
            domain_template="game_guide",
            route_key="guide.game_guide",
            goal_confidence=0.94,
            domain_confidence=0.92,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="guide",
        resolved_mode="guide",
        mode_confidence=0.94,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "practical_guide"
    assert result.product_view.template == "guide.game_guide"
    assert result.product_view.title == "Reach the midgame quickly with a safe build."
    assert result.product_view.sections[0].kind == "quick_win"
    assert result.product_view.sections[1].kind == "steps"
    assert result.product_view.sections[2].kind == "tips"
    assert result.product_view.sections[3].kind == "pitfalls"


def test_build_structured_result_builds_specialized_product_view_for_personal_narrative() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "Memoir summary",
        "bottom_line": "The story lands because the emotional shift is specific and earned.",
        "content_kind": "article",
        "author_stance": "mixed",
        "audience_fit": "readers who like reflective personal writing",
        "save_worthy_points": ["A small family detail reframes the whole story."],
        "author_thesis": "A routine visit becomes a story about inherited fear and care.",
        "evidence_backed_points": [
            {
                "id": "kp-1",
                "title": "The opening grounds the scene",
                "details": "Concrete details establish the narrator's unease before reflection begins.",
                "evidence_segment_ids": [],
            }
        ],
        "interpretive_points": [
            {
                "id": "an-1",
                "statement": "The narrator is really writing about responsibility rather than the event itself.",
                "kind": "implication",
                "evidence_segment_ids": [],
            }
        ],
        "what_is_new": "It connects a private memory to a wider inherited pattern without overstating it.",
        "tensions": ["The narrator wants distance but writes with intimate detail."],
        "uncertainties": ["How representative the family story is beyond this moment."],
        "verification_items": [],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="narrative",
            domain_template="personal_narrative",
            route_key="narrative.personal_narrative",
            goal_confidence=0.9,
            domain_confidence=0.9,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.9,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "narrative_digest"
    assert result.product_view.template == "narrative.personal_narrative"
    assert result.product_view.title == "A routine visit becomes a story about inherited fear and care."
    assert result.product_view.sections[0].kind == "summary"
    assert result.product_view.sections[1].kind == "story_beats"
    assert result.product_view.sections[2].kind == "themes"
    assert result.product_view.sections[3].kind == "takeaway"


def test_build_structured_result_builds_generic_review_product_view() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "Review summary",
        "bottom_line": "Worth trying if you like slow, atmospheric work.",
        "content_kind": "review",
        "author_stance": "mixed",
        "audience_fit": "fans of quiet games",
        "save_worthy_points": ["The art direction carries the experience."],
        "overall_judgment": "Strong but niche.",
        "highlights": ["Excellent atmosphere", "Distinct visual design"],
        "style_and_mood": "slow and moody",
        "what_stands_out": "Its confidence in withholding explanation.",
        "who_it_is_for": "players who enjoy ambiguity",
        "reservation_points": ["The pacing will not work for everyone."],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="review",
            domain_template="generic",
            route_key="review.generic",
            goal_confidence=0.81,
            domain_confidence=0.0,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="review",
        resolved_mode="review",
        mode_confidence=0.81,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "review_curation"
    assert result.product_view.template == "review.generic"
    assert result.product_view.title == "Strong but niche."
    assert result.product_view.sections[0].kind == "summary"
    assert result.product_view.sections[1].kind == "highlights"
    assert result.product_view.sections[2].kind == "audience"
    assert result.product_view.sections[3].kind == "reservations"


def test_build_structured_result_builds_argument_generic_as_full_analysis_brief() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "The piece argues for a policy shift but leaves execution risk unresolved.",
        "bottom_line": "The argument is directionally persuasive but operationally incomplete.",
        "content_kind": "analysis",
        "author_stance": "analytical",
        "audience_fit": "Readers who want the full argument map",
        "save_worthy_points": ["Risk is concentrated in implementation."],
        "author_thesis": "The policy case is credible, but the implementation case is not yet proven.",
        "evidence_backed_points": [
            {
                "id": "kp-1",
                "title": "Claim one",
                "details": "The article says the policy addresses the core bottleneck.",
                "evidence_segment_ids": ["e1"],
            },
            {
                "id": "kp-2",
                "title": "Claim two",
                "details": "The article argues current incentives already align with adoption.",
                "evidence_segment_ids": ["e2"],
            },
        ],
        "interpretive_points": [
            {
                "id": "an-1",
                "statement": "Execution failure would damage the policy's credibility more than its theory.",
                "kind": "implication",
                "evidence_segment_ids": ["e2"],
            }
        ],
        "what_is_new": "The piece ties policy success to execution sequencing rather than principle alone.",
        "tensions": ["The author assumes coordination capacity that is not demonstrated."],
        "uncertainties": ["Implementation cost remains weakly specified."],
        "verification_items": [
            {
                "id": "ver-1",
                "claim": "The delivery timeline is realistic.",
                "status": "partial",
                "evidence_segment_ids": ["e2"],
                "rationale": "The article gives milestones but not resource assumptions.",
                "confidence": 0.62,
            }
        ],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="argument",
            domain_template="generic",
            route_key="argument.generic",
            goal_confidence=0.91,
            domain_confidence=0.0,
            requested_reading_goal="argument",
            requested_domain_template=None,
        ),
        requested_mode="argument",
        resolved_mode="argument",
        mode_confidence=0.91,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "analysis_brief"
    assert result.product_view.template == "argument.generic"
    assert [section.kind for section in result.product_view.sections] == [
        "core_judgment",
        "main_arguments",
        "evidence",
        "tensions",
        "verification",
    ]


def test_build_structured_result_builds_guide_generic_as_compressed_takeaway_view() -> None:
    from content_ingestion.pipeline.llm_pipeline import RoutingDecision, _build_structured_result

    payload = {
        "core_summary": "This is a dense article about how to navigate the decision quickly.",
        "bottom_line": "You only need the few moves that materially change the outcome.",
        "content_kind": "guide",
        "author_stance": "practical",
        "audience_fit": "Readers who want the shortest useful version",
        "save_worthy_points": ["Ignore low-value background detail."],
        "guide_goal": "Extract the fastest useful reading of the piece.",
        "recommended_steps": [
            "Read the author's central claim first.",
            "Keep only the evidence that changes the conclusion.",
            "Ignore rhetorical framing.",
            "Retain the final practical implication.",
            "Drop secondary caveats unless they change the decision.",
            "Skip historical backfill.",
        ],
        "tips": ["Treat statistics as support, not the destination."],
        "pitfalls": ["Do not over-read background sections."],
        "prerequisites": [],
        "quick_win": "Reduce the article to one sentence and four retained ideas.",
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="guide",
            domain_template="generic",
            route_key="guide.generic",
            goal_confidence=0.95,
            domain_confidence=0.0,
            requested_reading_goal="guide",
            requested_domain_template=None,
        ),
        requested_mode="guide",
        resolved_mode="guide",
        mode_confidence=0.95,
    )

    assert result.product_view is not None
    assert result.product_view.layout == "practical_guide"
    assert result.product_view.template == "guide.generic"
    assert [section.kind for section in result.product_view.sections] == [
        "one_line_summary",
        "core_takeaways",
        "remember_this",
    ]
    assert len(result.product_view.sections[1].items) == 5


def test_synthesizer_instruction_dispatch_specializes_politics_argument_route() -> None:
    from content_ingestion.pipeline.llm_pipeline import _synthesizer_instructions_for_mode

    instructions = _synthesizer_instructions_for_mode("argument", "argument.politics_public_issue")

    assert "public-issue" in instructions or "public issue" in instructions
    assert "tradeoff" in instructions or "trade-off" in instructions


def test_synthesizer_instruction_dispatch_specializes_macro_business_route() -> None:
    from content_ingestion.pipeline.llm_pipeline import _synthesizer_instructions_for_mode

    instructions = _synthesizer_instructions_for_mode("argument", "argument.macro_business")

    assert "macro" in instructions
    assert "cycle" in instructions or "business" in instructions


def test_synthesizer_instruction_dispatch_specializes_game_guide_route() -> None:
    from content_ingestion.pipeline.llm_pipeline import _synthesizer_instructions_for_mode

    instructions = _synthesizer_instructions_for_mode("guide", "guide.game_guide")

    assert "game" in instructions
    assert "player" in instructions or "build" in instructions or "route" in instructions


def test_synthesizer_instruction_dispatch_keeps_generic_argument_fallback() -> None:
    from content_ingestion.pipeline.llm_pipeline import _synthesizer_instructions_argument, _synthesizer_instructions_for_mode

    instructions = _synthesizer_instructions_for_mode("argument", "argument.generic")

    assert instructions == _synthesizer_instructions_argument()


def test_analyze_asset_cleans_invalid_evidence_references(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    settings = load_settings()

    class _InvalidResponses:
        def create(self, **kwargs):
            schema_name = kwargs.get("text", {}).get("format", {}).get("name", "")
            if schema_name == "reader_analysis":
                payload = {
                    "document_type": "article",
                    "thesis": "Demo thesis",
                    "chapter_map": [],
                    "argument_skeleton": [],
                    "content_signals": {
                        "evidence_density": "medium",
                        "rhetoric_density": "low",
                        "has_novel_claim": False,
                        "has_data": False,
                        "estimated_depth": "medium",
                    },
                    "suggested_reading_goal": "argument",
                    "goal_confidence": 0.6,
                    "suggested_domain_template": "generic",
                    "domain_confidence": 0.6,
                }
            else:
                payload = {
                    "core_summary": "Summary",
                    "bottom_line": "Answer",
                    "content_kind": "analysis",
                    "author_stance": "critical",
                    "audience_fit": "general readers",
                    "save_worthy_points": [],
                    "author_thesis": "Headline",
                    "evidence_backed_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["missing-id", "e1"],
                        }
                    ],
                    "interpretive_points": [
                        {
                            "id": "an-1",
                            "kind": "implication",
                            "statement": "Statement",
                            "evidence_segment_ids": ["missing-id"],
                        }
                    ],
                    "what_is_new": "",
                    "tensions": [],
                    "uncertainties": [],
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


def test_validate_structured_result_cleans_invalid_evidence_references_from_editorial_and_product_view() -> None:
    from content_ingestion.pipeline.llm_pipeline import (
        RoutingDecision,
        _build_structured_result,
        _validate_structured_result_evidence,
    )

    payload = {
        "core_summary": "Summary",
        "bottom_line": "Bottom line",
        "content_kind": "analysis",
        "author_stance": "critical",
        "audience_fit": "general readers",
        "save_worthy_points": [],
        "author_thesis": "Headline",
        "evidence_backed_points": [
            {
                "id": "kp-1",
                "title": "Point A",
                "details": "Details",
                "evidence_segment_ids": ["missing-id", "e1"],
            }
        ],
        "interpretive_points": [
            {
                "id": "an-1",
                "kind": "implication",
                "statement": "Statement",
                "evidence_segment_ids": ["missing-id"],
            }
        ],
        "what_is_new": "What is new",
        "tensions": ["A tension"],
        "uncertainties": ["An uncertainty"],
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
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="argument",
            domain_template="politics_public_issue",
            route_key="argument.politics_public_issue",
            goal_confidence=0.8,
            domain_confidence=0.8,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.8,
    )

    warnings = _validate_structured_result_evidence(result, valid_evidence_segment_ids={"e1"})

    assert warnings
    assert result.key_points[0].evidence_segment_ids == ["e1"]
    assert result.analysis_items[0].evidence_segment_ids == []
    assert result.verification_items[0].evidence_segment_ids == []
    assert result.verification_items[0].status == "unclear"
    assert result.editorial is not None
    assert result.editorial.mode_payload["evidence_backed_points"][0]["evidence_segment_ids"] == ["e1"]
    assert result.editorial.mode_payload["interpretive_points"][0]["evidence_segment_ids"] == []
    assert result.editorial.mode_payload["verification_items"][0]["evidence_segment_ids"] == []
    assert result.editorial.mode_payload["verification_items"][0]["status"] == "unclear"
    assert result.product_view is not None
    assert result.product_view.sections[1].items[0]["evidence_segment_ids"] == ["e1"]


def test_validate_structured_result_cleans_invalid_evidence_references_when_ids_are_missing_or_duplicated() -> None:
    from content_ingestion.pipeline.llm_pipeline import (
        RoutingDecision,
        _build_structured_result,
        _validate_structured_result_evidence,
    )

    payload = {
        "core_summary": "Summary",
        "bottom_line": "Bottom line",
        "content_kind": "analysis",
        "author_stance": "critical",
        "audience_fit": "general readers",
        "save_worthy_points": [],
        "author_thesis": "Headline",
        "evidence_backed_points": [
            {
                "id": "",
                "title": "Point A",
                "details": "Details A",
                "evidence_segment_ids": ["missing-a", "e1"],
            },
            {
                "id": "",
                "title": "Point B",
                "details": "Details B",
                "evidence_segment_ids": ["missing-b", "e2"],
            },
        ],
        "interpretive_points": [
            {
                "id": "dup",
                "kind": "implication",
                "statement": "Statement A",
                "evidence_segment_ids": ["missing-a", "e1"],
            },
            {
                "id": "dup",
                "kind": "alternative",
                "statement": "Statement B",
                "evidence_segment_ids": ["missing-b"],
            },
        ],
        "what_is_new": "What is new",
        "tensions": ["A tension"],
        "uncertainties": ["An uncertainty"],
        "verification_items": [
            {
                "id": "",
                "claim": "Claim A",
                "status": "supported",
                "evidence_segment_ids": ["missing-a", "e1"],
                "rationale": "Model claimed evidence exists",
                "confidence": 0.9,
            },
            {
                "id": "",
                "claim": "Claim B",
                "status": "partial",
                "evidence_segment_ids": ["missing-b"],
                "rationale": "Model claimed evidence exists",
                "confidence": 0.6,
            },
        ],
    }

    result = _build_structured_result(
        payload,
        reader_payload={"chapter_map": []},
        routing=RoutingDecision(
            reading_goal="argument",
            domain_template="politics_public_issue",
            route_key="argument.politics_public_issue",
            goal_confidence=0.8,
            domain_confidence=0.8,
            requested_reading_goal=None,
            requested_domain_template=None,
        ),
        requested_mode="auto",
        resolved_mode="argument",
        mode_confidence=0.8,
    )

    warnings = _validate_structured_result_evidence(result, valid_evidence_segment_ids={"e1", "e2"})

    assert warnings
    assert [item.evidence_segment_ids for item in result.key_points] == [["e1"], ["e2"]]
    assert [item.evidence_segment_ids for item in result.analysis_items] == [["e1"], []]
    assert [item.evidence_segment_ids for item in result.verification_items] == [["e1"], []]
    assert [item.status for item in result.verification_items] == ["supported", "unclear"]
    assert result.editorial is not None
    assert [item["evidence_segment_ids"] for item in result.editorial.mode_payload["evidence_backed_points"]] == [["e1"], ["e2"]]
    assert [item["evidence_segment_ids"] for item in result.editorial.mode_payload["interpretive_points"]] == [["e1"], []]
    assert [item["evidence_segment_ids"] for item in result.editorial.mode_payload["verification_items"]] == [["e1"], []]
    assert [item["status"] for item in result.editorial.mode_payload["verification_items"]] == ["supported", "unclear"]
    assert result.product_view is not None
    key_point_items = result.product_view.sections[1].items
    assert [item["evidence_segment_ids"] for item in key_point_items] == [["e1"], ["e2"]]


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
                    "document_type": "article",
                    "thesis": "Demo thesis",
                    "chapter_map": [],
                    "argument_skeleton": [],
                    "content_signals": {
                        "evidence_density": "medium",
                        "rhetoric_density": "low",
                        "has_novel_claim": False,
                        "has_data": False,
                        "estimated_depth": "medium",
                    },
                    "suggested_reading_goal": "argument",
                    "goal_confidence": 0.6,
                    "suggested_domain_template": "generic",
                    "domain_confidence": 0.6,
                }
            elif self.call_count == 2:
                payload = {
                    "core_summary": "Summary",
                    "bottom_line": "Answer",
                    "content_kind": "analysis",
                    "author_stance": "critical",
                    "audience_fit": "general readers",
                    "save_worthy_points": [],
                    "author_thesis": "Headline",
                    "evidence_backed_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["missing-id"],
                        }
                    ],
                    "interpretive_points": [
                        {
                            "id": "an-1",
                            "kind": "implication",
                            "statement": "Statement",
                            "evidence_segment_ids": ["missing-id"],
                        }
                    ],
                    "what_is_new": "",
                    "tensions": [],
                    "uncertainties": [],
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
                }
            else:
                payload = {
                    "core_summary": "Summary",
                    "bottom_line": "Answer",
                    "content_kind": "analysis",
                    "author_stance": "critical",
                    "audience_fit": "general readers",
                    "save_worthy_points": [],
                    "author_thesis": "Headline",
                    "evidence_backed_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["e1"],
                        }
                    ],
                    "interpretive_points": [
                        {
                            "id": "an-1",
                            "kind": "implication",
                            "statement": "Statement",
                            "evidence_segment_ids": ["e1"],
                        }
                    ],
                    "what_is_new": "",
                    "tensions": [],
                    "uncertainties": [],
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
                    "suggested_reading_goal": "argument",
                    "goal_confidence": 0.7,
                    "suggested_domain_template": "generic",
                    "domain_confidence": 0.7,
                }
            elif self.call_count == 2:
                # First synthesizer call — invalid evidence
                payload = {
                    "core_summary": "Summary",
                    "bottom_line": "Answer",
                    "content_kind": "analysis",
                    "author_stance": "critical",
                    "audience_fit": "general readers",
                    "save_worthy_points": [],
                    "author_thesis": "Headline",
                    "evidence_backed_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["missing-id"],
                        }
                    ],
                    "interpretive_points": [],
                    "what_is_new": "Something new",
                    "tensions": [],
                    "uncertainties": [],
                    "verification_items": [],
                }
            else:
                # Repair call — valid evidence
                payload = {
                    "core_summary": "Summary",
                    "bottom_line": "Answer",
                    "content_kind": "analysis",
                    "author_stance": "critical",
                    "audience_fit": "general readers",
                    "save_worthy_points": [],
                    "author_thesis": "Headline",
                    "evidence_backed_points": [
                        {
                            "id": "kp-1",
                            "title": "Point A",
                            "details": "Details",
                            "evidence_segment_ids": ["e1"],
                        }
                    ],
                    "interpretive_points": [],
                    "what_is_new": "Something new",
                    "tensions": [],
                    "uncertainties": [],
                    "verification_items": [],
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
