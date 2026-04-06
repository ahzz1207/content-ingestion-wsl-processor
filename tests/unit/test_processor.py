import json
import os
from pathlib import Path

from content_ingestion.core.evidence import build_evidence_segment_id
from content_ingestion.core.models import RelatedRef, StructuredResult, WarningItem
from content_ingestion.inbox.processor import JobProcessor
from content_ingestion.inbox.protocol import ensure_shared_inbox


def test_processor_writes_structured_asset_fields(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = inbox.processing / "job123"
    job_dir.mkdir(parents=True)

    (job_dir / "payload.html").write_text(
        "<html><head><title>Demo Video</title></head><body><p>Body text</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "job123",
                "source_url": "https://example.com/video",
                "collector": "windows-client",
                "collected_at": "2026-03-15T09:00:00+00:00",
                "content_type": "html",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "audio",
                "capture_manifest_filename": "capture_manifest.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    video_dir = job_dir / "attachments" / "video"
    video_dir.mkdir(parents=True)
    (video_dir / "video.mp3").write_bytes(b"audio")
    (video_dir / "video.en.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello world\n",
        encoding="utf-8",
    )
    (job_dir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "job_id": "job123",
                "source_url": "https://example.com/video",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "audio",
                "primary_payload": {
                    "path": "payload.html",
                    "role": "focused_capture",
                    "media_type": "text/html",
                    "content_type": "html",
                    "size_bytes": 77,
                    "is_primary": True,
                },
                "artifacts": [
                    {
                        "path": "payload.html",
                        "role": "focused_capture",
                        "media_type": "text/html",
                        "content_type": "html",
                        "size_bytes": 77,
                        "is_primary": True,
                    },
                    {
                        "path": "attachments/video/video.mp3",
                        "role": "audio_file",
                        "media_type": "audio/mpeg",
                        "size_bytes": 5,
                        "is_primary": False,
                    },
                    {
                        "path": "attachments/video/video.en.vtt",
                        "role": "subtitle",
                        "media_type": "text/vtt",
                        "size_bytes": 52,
                        "is_primary": False,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    target_dir = JobProcessor().process(job_dir)
    normalized = json.loads((target_dir / "normalized.json").read_text(encoding="utf-8"))

    asset = normalized["asset"]
    assert asset["content_shape"] == "video"
    assert asset["attachments"]
    assert asset["attachments"][0]["kind"] == "audio"
    assert asset["evidence_segments"]
    assert asset["metadata"]["handoff"]["video_download_mode"] == "audio"
    assert asset["metadata"]["capture"]["video_download_mode"] == "audio"
    assert asset["metadata"]["llm_processing"]["status"] == "skipped"
    assert asset["metadata"]["llm_processing"]["content_policy_id"] == "video_text_first_v1"
    assert asset["metadata"]["llm_processing"]["supported_input_modalities"] == ["text", "text_image"]
    assert asset["metadata"]["llm_processing"]["text_input_modality"] == "text_image"
    assert asset["metadata"]["llm_processing"]["multimodal_input_modality"] == "text_image"
    assert asset["metadata"]["llm_processing"]["task_intent"] == "summarize_video_from_subtitle_and_whisper_transcript"
    assert asset["metadata"]["llm_processing"]["skip_reason"] == "missing OPENAI_API_KEY"
    assert asset["metadata"]["llm_processing"]["request_artifacts"] == {}
    assert asset["metadata"]["llm_processing"]["handshake"]["schema_mode"] == "json_schema"
    assert asset["metadata"]["llm_processing"]["handshake"]["content_policy_id"] == "video_text_first_v1"


def test_processor_runs_ffmpeg_whisper_and_llm_pipeline(tmp_path: Path, monkeypatch) -> None:
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = inbox.processing / "job234"
    job_dir.mkdir(parents=True)

    ffmpeg_script = tmp_path / "ffmpeg"
    ffmpeg_script.write_text(
        "#!/bin/sh\n"
        "last=''\n"
        "for arg in \"$@\"; do last=\"$arg\"; done\n"
        "case \"$last\" in\n"
        "  *frame-%03d.jpg)\n"
        "    outdir=$(dirname \"$last\")\n"
        "    mkdir -p \"$outdir\"\n"
        "    printf 'frame1' > \"$outdir/frame-001.jpg\"\n"
        "    printf 'frame2' > \"$outdir/frame-002.jpg\"\n"
        "    ;;\n"
        "  *)\n"
        "    mkdir -p \"$(dirname \"$last\")\"\n"
        "    printf 'audio-bytes' > \"$last\"\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    whisper_script = tmp_path / "whisper"
    whisper_script.write_text(
        "#!/bin/sh\n"
        "src=\"$1\"\n"
        "shift\n"
        "outdir=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output_dir\" ]; then\n"
        "    shift\n"
        "    outdir=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "base=$(basename \"$src\")\n"
        "stem=${base%.*}\n"
        "mkdir -p \"$outdir\"\n"
        "cat > \"$outdir/$stem.json\" <<'EOF'\n"
        "{\"text\": \"hello transcript\", \"segments\": [{\"start\": 0.0, \"end\": 1.2, \"text\": \"hello transcript\"}]}\n"
        "EOF\n"
        "printf 'hello transcript' > \"$outdir/$stem.txt\"\n",
        encoding="utf-8",
    )
    os.chmod(ffmpeg_script, 0o755)
    os.chmod(whisper_script, 0o755)
    monkeypatch.setenv("CONTENT_INGESTION_FFMPEG_COMMAND", str(ffmpeg_script))
    monkeypatch.setenv("CONTENT_INGESTION_WHISPER_COMMAND", str(whisper_script))
    monkeypatch.setenv("CONTENT_INGESTION_WHISPER_MODEL", "tiny")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("CONTENT_INGESTION_MULTIMODAL_MODEL", "gpt-4.1")
    transcript_evidence_id = build_evidence_segment_id(
        kind="transcript",
        source="analysis/transcript/transcript.json",
        text="hello transcript",
        sequence=1,
        start_ms=0,
        end_ms=1200,
    )

    class _FakeResponses:
        def create(self, **kwargs):
            schema_name = kwargs.get("text", {}).get("format", {}).get("name", "")
            if schema_name == "reader_analysis":
                return type(
                    "Response",
                    (),
                    {
                        "output_text": json.dumps(
                            {
                                "document_type": "article",
                                "thesis": "Transcript summary",
                                "chapter_map": [
                                    {
                                        "id": "ch-1",
                                        "title": "Opening",
                                        "summary": "Summary of the video opening",
                                        "block_ids": ["b1"],
                                        "role": "argument",
                                        "weight": "high",
                                    }
                                ],
                                "argument_skeleton": [
                                    {
                                        "id": "arg-1",
                                        "claim": "Key point",
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
                                "suggested_mode": "argument",
                                "mode_confidence": 0.88,
                                "suggested_reading_goal": "argument",
                                "goal_confidence": 0.88,
                                "suggested_domain_template": "generic",
                                "domain_confidence": 0.82,
                            }
                        )
                    },
                )()
            if kwargs["model"] == "gpt-4.1-mini":
                return type(
                    "Response",
                    (),
                    {
                        "output_text": json.dumps(
                            {
                                "core_summary": "Summarized transcript",
                                "bottom_line": "Synthesized answer",
                                "content_kind": "analysis",
                                "author_stance": "explanatory",
                                "audience_fit": "Readers who want a quick macro brief",
                                "save_worthy_points": ["Key point"],
                                "author_thesis": "Transcript summary",
                                "evidence_backed_points": [
                                    {
                                        "id": "kp-1",
                                        "title": "Key point",
                                        "details": "Important supporting detail",
                                        "evidence_segment_ids": [transcript_evidence_id],
                                    }
                                ],
                                "interpretive_points": [
                                    {
                                        "id": "an-1",
                                        "kind": "implication",
                                        "statement": "Point 1",
                                        "evidence_segment_ids": [transcript_evidence_id],
                                    }
                                ],
                                "what_is_new": "A concise framing of the transcript",
                                "tensions": [],
                                "uncertainties": [],
                                "verification_items": [
                                    {
                                        "id": "ver-1",
                                        "claim": "Claim 1",
                                        "status": "supported",
                                        "evidence_segment_ids": [transcript_evidence_id],
                                        "rationale": "Evidence 1",
                                        "confidence": 0.9,
                                    }
                                ],
                            }
                        )
                    },
                )()
            return type(
                "Response",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "visual_findings": [
                                {
                                    "id": "vf-1",
                                    "finding": "Frame review",
                                    "evidence_frame_paths": ["analysis/frames/frame-001.jpg"],
                                }
                            ],
                            "verification_adjustments": [
                                {
                                    "id": "ver-2",
                                    "claim": "Claim 2",
                                    "status": "partial",
                                    "rationale": "Frame mismatch",
                                    "evidence_frame_paths": ["analysis/frames/frame-001.jpg"],
                                }
                            ],
                            "overall_assessment": "Visual review done",
                        }
                    )
                },
            )()

    class _FakeClient:
        def __init__(self) -> None:
            self.responses = _FakeResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: _FakeClient())

    (job_dir / "payload.html").write_text(
        "<html><head><title>Demo Video</title></head><body><p>Body text</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "job234",
                "source_url": "https://example.com/video",
                "collector": "windows-client",
                "collected_at": "2026-03-15T09:00:00+00:00",
                "content_type": "html",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "video",
                "capture_manifest_filename": "capture_manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")
    video_dir = job_dir / "attachments" / "video"
    video_dir.mkdir(parents=True)
    (video_dir / "video.mp4").write_bytes(b"video")
    (job_dir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "job_id": "job234",
                "source_url": "https://example.com/video",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "video",
                "primary_payload": {
                    "path": "payload.html",
                    "role": "focused_capture",
                    "media_type": "text/html",
                    "content_type": "html",
                    "size_bytes": 77,
                    "is_primary": True,
                },
                "artifacts": [
                    {
                        "path": "payload.html",
                        "role": "focused_capture",
                        "media_type": "text/html",
                        "content_type": "html",
                        "size_bytes": 77,
                        "is_primary": True,
                    },
                    {
                        "path": "attachments/video/video.mp4",
                        "role": "video_file",
                        "media_type": "video/mp4",
                        "size_bytes": 5,
                        "is_primary": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    target_dir = JobProcessor().process(job_dir)
    normalized = json.loads((target_dir / "normalized.json").read_text(encoding="utf-8"))
    asset = normalized["asset"]

    assert asset["transcript_text"] == "hello transcript"
    assert "Transcript:" in asset["analysis_text"]
    assert any(segment["id"].startswith("transcript-") for segment in asset["evidence_segments"])
    assert asset["metadata"]["media_processing"]["status"] == "pass"
    assert asset["summary"] == "Summarized transcript"
    transcript_ids = [segment["id"] for segment in asset["evidence_segments"] if segment["kind"] == "transcript"]
    assert transcript_ids
    first_transcript_id = transcript_ids[0]
    assert asset["result"]["summary"]["headline"] == "Transcript summary"
    assert asset["result"]["summary"]["id"] == "summary-primary"
    assert asset["result"]["summary"]["display"]["kind"] == "summary"
    assert asset["result"]["summary"]["display"]["tone"] == "hero"
    assert asset["result"]["summary"]["display"]["priority"] == 0
    assert asset["result"]["key_points"][0]["id"] == "kp-1"
    assert asset["result"]["key_points"][0]["resolved_evidence"]
    assert asset["result"]["key_points"][0]["resolved_evidence"][0]["kind"] == "transcript"
    assert asset["result"]["key_points"][0]["display"]["kind"] == "key_point"
    assert asset["result"]["key_points"][0]["display"]["tone"] == "accent"
    assert asset["result"]["key_points"][0]["display"]["priority"] == 101
    assert asset["result"]["analysis_items"][0]["resolved_evidence"]
    assert asset["result"]["analysis_items"][0]["resolved_evidence"][0]["id"] == first_transcript_id
    assert asset["result"]["analysis_items"][0]["display"]["kind"] == "analysis_item"
    assert asset["result"]["analysis_items"][0]["display"]["tone"] == "neutral"
    assert asset["result"]["analysis_items"][0]["display"]["priority"] == 201
    assert asset["analysis_items"]
    assert asset["verification_items"]
    assert asset["verification_items"][0]["resolved_evidence"]
    assert asset["verification_items"][0]["resolved_evidence"][0]["kind"] == "transcript"
    assert asset["verification_items"][0]["resolved_evidence"][0]["preview_text"] == "hello transcript"
    assert asset["result"]["verification_items"][0]["resolved_evidence"]
    assert asset["result"]["verification_items"][0]["resolved_evidence"][0]["id"] == first_transcript_id
    assert asset["result"]["verification_items"][0]["display"]["kind"] == "verification_item"
    assert asset["result"]["verification_items"][0]["display"]["tone"] == "positive"
    assert asset["result"]["verification_items"][0]["display"]["priority"] == 361
    assert asset["result"]["display_plan"]["version"] == 1
    assert asset["result"]["display_plan"]["sections"][0]["id"] == "summary"
    assert asset["result"]["display_plan"]["sections"][0]["default_view"] == "hero"
    assert asset["result"]["display_plan"]["sections"][0]["item_ids"] == ["summary-primary"]
    assert asset["result"]["display_plan"]["sections"][1]["id"] == "key_points"
    assert asset["result"]["display_plan"]["sections"][1]["item_ids"] == ["kp-1"]
    assert asset["result"]["display_plan"]["sections"][2]["id"] == "analysis_items"
    assert asset["result"]["display_plan"]["sections"][2]["default_expanded"] is False
    assert asset["result"]["display_plan"]["sections"][3]["id"] == "verification_items"
    assert asset["result"]["display_plan"]["sections"][3]["default_view"] == "evidence_strip"
    assert asset["result"]["synthesis"]["display"]["kind"] == "synthesis"
    assert asset["result"]["synthesis"]["display"]["tone"] == "hero"
    assert asset["result"]["synthesis"]["display"]["priority"] == 400
    assert asset["result"]["synthesis"]["id"] == "synthesis-primary"
    assert asset["result"]["display_plan"]["sections"][4]["id"] == "synthesis"
    assert asset["result"]["display_plan"]["sections"][4]["default_view"] == "spotlight"
    assert asset["result"]["display_plan"]["sections"][4]["item_ids"] == ["synthesis-primary"]
    assert asset["result"]["warnings"] == []
    assert asset["result"]["display_plan"]["sections"][5]["id"] == "warnings"
    assert asset["result"]["display_plan"]["sections"][5]["item_count"] == 0
    assert asset["result"]["display_plan"]["sections"][5]["default_expanded"] is False
    assert first_transcript_id in asset["result"]["evidence_backlinks"]
    assert asset["result"]["evidence_backlinks"][first_transcript_id][0]["kind"] == "key_point"
    assert asset["result"]["evidence_backlinks"][first_transcript_id][1]["kind"] == "analysis_item"
    assert asset["result"]["evidence_backlinks"][first_transcript_id][2]["kind"] == "verification_item"
    assert asset["result"]["result_index"]["summary-primary"]["section"] == "summary"
    assert asset["result"]["result_index"]["kp-1"]["section"] == "key_points"
    assert asset["result"]["result_index"]["kp-1"]["evidence_segment_ids"] == [first_transcript_id]
    assert asset["result"]["result_index"]["synthesis-primary"]["kind"] == "synthesis"
    assert asset["evidence_index"]
    assert first_transcript_id in asset["evidence_index"]
    assert asset["evidence_index"][first_transcript_id]["kind"] == "transcript"
    assert asset["evidence_index"][first_transcript_id]["preview_text"] == "hello transcript"
    assert asset["synthesis"] == "Synthesized answer"
    assert asset["metadata"]["llm_processing"]["status"] == "pass"
    assert asset["metadata"]["llm_processing"]["provider"] == "openai"
    assert asset["metadata"]["llm_processing"]["content_policy_id"] == "video_text_first_v1"
    assert asset["metadata"]["llm_processing"]["supported_input_modalities"] == ["text", "text_image"]
    assert asset["metadata"]["llm_processing"]["text_input_modality"] == "text_image"
    assert asset["metadata"]["llm_processing"]["multimodal_input_modality"] == "text_image"
    assert asset["metadata"]["llm_processing"]["task_intent"] == "summarize_video_from_subtitle_and_whisper_transcript"
    assert asset["metadata"]["llm_processing"]["request_artifacts"]["text"] == "analysis/llm/text_request.json"
    assert asset["metadata"]["llm_processing"]["request_artifacts"]["multimodal"] == "analysis/llm/multimodal_request.json"
    assert asset["metadata"]["llm_processing"]["requested_mode"] == "auto"
    assert asset["metadata"]["llm_processing"]["resolved_mode"] == "argument"
    assert asset["metadata"]["llm_processing"]["mode_confidence"] == 0.88
    assert asset["metadata"]["llm_processing"]["resolved_domain_template"] == "generic"
    assert asset["metadata"]["llm_processing"]["domain_template_confidence"] == 0.82
    assert asset["metadata"]["llm_processing"]["routing_signals"]["suggested_reading_goal"] == "argument"
    assert asset["metadata"]["llm_processing"]["routing_signals"]["suggested_domain_template"] == "generic"
    assert asset["metadata"]["llm_processing"]["routing_signals"]["content_signals"]["estimated_depth"] == "medium"
    assert asset["metadata"]["llm_processing"]["handshake"]["request_artifacts"]["text"] == "analysis/llm/text_request.json"
    assert asset["metadata"]["llm_processing"]["handshake"]["analysis_model"] == "gpt-4.1-mini"
    assert asset["metadata"]["llm_processing"]["handshake"]["schema_mode"] == "json_schema"
    assert asset["metadata"]["llm_processing"]["handshake"]["content_policy_id"] == "video_text_first_v1"


def test_processor_threads_requested_goal_and_domain_overrides_into_llm_pipeline(tmp_path: Path, monkeypatch) -> None:
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = inbox.processing / "job-goal-override"
    job_dir.mkdir(parents=True)

    (job_dir / "payload.html").write_text(
        "<html><head><title>Demo</title></head><body><p>Body text</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "job-goal-override",
                "source_url": "https://example.com/article",
                "collector": "windows-client",
                "collected_at": "2026-03-15T09:00:00+00:00",
                "content_type": "html",
                "platform": "generic",
                "requested_mode": "auto",
                "requested_reading_goal": "guide",
                "requested_domain_template": "game_guide",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    captured: dict[str, object] = {}

    def _fake_analyze_asset(*, job_dir, asset, settings, requested_mode="auto", requested_reading_goal=None, requested_domain_template=None):
        captured["requested_mode"] = requested_mode
        captured["requested_reading_goal"] = requested_reading_goal
        captured["requested_domain_template"] = requested_domain_template
        return type(
            "AnalysisResult",
            (),
            {
                "status": "pass",
                "provider": "openai",
                "base_url": None,
                "analysis_model": "gpt-test",
                "multimodal_model": None,
                "schema_mode": "json_schema",
                "content_policy_id": "text_only_v1",
                "requested_mode": requested_mode,
                "resolved_mode": "guide",
                "mode_confidence": 1.0,
                "requested_reading_goal": requested_reading_goal,
                "resolved_reading_goal": "guide",
                "goal_confidence": 1.0,
                "requested_domain_template": requested_domain_template,
                "resolved_domain_template": "game_guide",
                "domain_confidence": 1.0,
                "route_key": "guide.game_guide",
                "supported_input_modalities": ["text"],
                "text_input_modality": "text",
                "multimodal_input_modality": "text",
                "task_intent": "summarize_article",
                "skip_reason": None,
                "request_artifacts": {},
                "summary": None,
                "key_points": [],
                "analysis_items": [],
                "verification_items": [],
                "structured_result": None,
                "output_path": None,
                "warnings": [],
                "steps": [],
                "reader_result_path": None,
            },
        )()

    monkeypatch.setattr("content_ingestion.inbox.processor.analyze_asset", _fake_analyze_asset)

    JobProcessor().process(job_dir)

    assert captured == {
        "requested_mode": "auto",
        "requested_reading_goal": "guide",
        "requested_domain_template": "game_guide",
    }


def test_serialize_structured_result_includes_typed_warning_refs() -> None:
    processor = JobProcessor()
    payload = processor._serialize_structured_result(  # noqa: SLF001
        StructuredResult(
            warnings=[
                WarningItem(
                    code="invalid_evidence_reference",
                    severity="warn",
                    message="verification_item:ver-1 referenced unknown evidence id: missing-id",
                    related_refs=[
                        RelatedRef(kind="verification_item", id="ver-1", role="source_item"),
                        RelatedRef(kind="evidence_segment", id="missing-id", role="missing_reference"),
                    ],
                )
            ]
        ),
        evidence_segments=[],
    )

    assert payload is not None
    assert payload["warnings"][0]["code"] == "invalid_evidence_reference"
    assert payload["warnings"][0]["related_refs"][0]["kind"] == "verification_item"
    assert payload["warnings"][0]["related_refs"][0]["id"] == "ver-1"
    assert payload["warnings"][0]["related_refs"][1]["kind"] == "evidence_segment"
    assert payload["warnings"][0]["related_refs"][1]["role"] == "missing_reference"
    assert payload["evidence_backlinks"] == {}
    assert payload["result_index"]["warning-1"]["section"] == "warnings"
    assert payload["result_index"]["warning-1"]["evidence_segment_ids"] == ["missing-id"]


def test_serialize_structured_result_includes_editorial_display_payload() -> None:
    from content_ingestion.core.models import EditorialBase, EditorialResult, KeyPoint, ResultSummary, SynthesisResult

    processor = JobProcessor()
    payload = processor._serialize_structured_result(  # noqa: SLF001
        StructuredResult(
            summary=ResultSummary(headline="Headline", short_text="Short summary"),
            key_points=[KeyPoint(id="kp-1", title="Point A", details="Details")],
            synthesis=SynthesisResult(final_answer="Bottom line"),
            editorial=EditorialResult(
                requested_mode="auto",
                resolved_mode="guide",
                mode_confidence=0.77,
                base=EditorialBase(
                    core_summary="Core summary",
                    bottom_line="Bottom line",
                    audience_fit="General readers",
                    save_worthy_points=["Save this"],
                ),
                mode_payload={
                    "guide_goal": "Do the thing",
                    "recommended_steps": ["Step one"],
                    "tips": ["Tip A"],
                    "pitfalls": ["Pitfall A"],
                    "prerequisites": ["Need account"],
                    "quick_win": "Start small",
                },
            ),
        ),
        evidence_segments=[],
    )

    assert payload is not None
    assert payload["editorial"]["requested_mode"] == "auto"
    assert payload["editorial"]["resolved_mode"] == "guide"
    assert payload["editorial"]["base"]["core_summary"]["display"]["kind"] == "summary"
    assert payload["editorial"]["mode_payload"]["guide_goal"]["display"]["kind"] == "meta"
    assert payload["editorial"]["mode_payload"]["recommended_steps"][0]["display"]["kind"] == "step"
    assert payload["editorial"]["mode_payload"]["pitfalls"][0]["display"]["tone"] == "warning"


def _make_minimal_job(inbox, job_id: str) -> Path:
    """Create a minimal valid job in processing/ for state machine tests."""
    job_dir = inbox.processing / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "payload.html").write_text(
        "<html><head><title>Test</title></head><body><p>content</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        __import__("json").dumps({
            "job_id": job_id,
            "source_url": "https://example.com/article",
            "collector": "windows-client",
            "collected_at": "2026-03-28T10:00:00+00:00",
            "content_type": "html",
        }),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")
    return job_dir


def test_processed_dir_only_populated_after_all_files_written(tmp_path: Path) -> None:
    """Job must land in processed/ only after normalized.json, normalized.md,
    pipeline.json, and status.json are all present (W1 finalizing stage)."""
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = _make_minimal_job(inbox, "jobW1a")

    target_dir = JobProcessor().process(job_dir)

    # target_dir must be in processed/
    assert target_dir.parent == shared_root / "processed"

    # All required files must be present in processed/
    for filename in ("normalized.json", "normalized.md", "pipeline.json", "status.json"):
        assert (target_dir / filename).exists(), f"Missing required file: {filename}"

    # processing/ must be empty (job moved away)
    assert not (shared_root / "processing" / "jobW1a").exists()

    # finalizing/ must be empty (transit only, job moved to processed/)
    assert not (shared_root / "finalizing" / "jobW1a").exists()


def test_finalizing_dir_created_by_ensure_shared_inbox(tmp_path: Path) -> None:
    """ensure_shared_inbox must create finalizing/ alongside the other stage dirs."""
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    assert inbox.finalizing.exists()
    assert (shared_root / "finalizing").is_dir()


def test_verify_required_outputs_raises_on_missing_files(tmp_path: Path) -> None:
    """_verify_required_outputs must raise JobProtocolError when required files are absent."""
    from content_ingestion.inbox.protocol import JobProtocolError
    processor = JobProcessor()
    job_dir = tmp_path / "job_incomplete"
    job_dir.mkdir()
    # Only write normalized.md — the rest are missing
    (job_dir / "normalized.md").write_text("content", encoding="utf-8")

    try:
        processor._verify_required_outputs(job_dir)  # noqa: SLF001
        assert False, "Expected JobProtocolError"
    except JobProtocolError as exc:
        assert "normalized.json" in str(exc)
        assert "pipeline.json" in str(exc)
        assert "status.json" in str(exc)
        assert "normalized.md" not in str(exc)  # this one is present


def test_verify_required_outputs_passes_when_all_files_present(tmp_path: Path) -> None:
    """_verify_required_outputs must not raise when all required files exist."""
    from content_ingestion.inbox.protocol import JobProtocolError
    processor = JobProcessor()
    job_dir = tmp_path / "job_complete"
    job_dir.mkdir()
    for filename in ("normalized.json", "normalized.md", "pipeline.json", "status.json"):
        (job_dir / filename).write_text("{}", encoding="utf-8")

    processor._verify_required_outputs(job_dir)  # noqa: SLF001 — must not raise


def test_handle_failure_rescues_job_stuck_in_finalizing(tmp_path: Path) -> None:
    """If a job ends up in finalizing/ (e.g. finalizing->processed move failed),
    _handle_failure must move it to failed/ rather than leaving it stuck."""
    from content_ingestion.inbox.protocol import JobProtocolError, ensure_shared_inbox
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)

    # Simulate a job that somehow ended up in finalizing/
    finalizing_dir = inbox.finalizing / "jobStuck"
    finalizing_dir.mkdir(parents=True)
    (finalizing_dir / "metadata.json").write_text(
        __import__("json").dumps({
            "job_id": "jobStuck",
            "source_url": "https://example.com",
            "collector": "test",
            "collected_at": "2026-03-28T00:00:00+00:00",
            "content_type": "html",
        }),
        encoding="utf-8",
    )
    (finalizing_dir / "READY").write_text("", encoding="utf-8")

    # Build a JobPaths that points to processing/ (as if it came from get_processing_job)
    from content_ingestion.inbox.protocol import JobPaths
    from datetime import datetime, timezone
    job = JobPaths(shared_root=shared_root, stage_dir=inbox.processing, job_id="jobStuck")

    processor = JobProcessor()
    exc = JobProtocolError("simulated move failure")
    started_at = datetime.now(timezone.utc)

    # _handle_failure should rescue from finalizing/ → failed/
    result_dir = processor._handle_failure(job, exc, started_at)  # noqa: SLF001

    assert result_dir.parent == shared_root / "failed"
    assert not finalizing_dir.exists()
    assert (shared_root / "failed" / "jobStuck").exists()


def test_handle_failure_rescue_from_finalizing_preserves_metadata(tmp_path):
    import json as _json
    from content_ingestion.inbox.protocol import (
        JobPaths, JobProtocolError, ensure_shared_inbox, METADATA_FILENAME,
    )
    from content_ingestion.inbox.processor import JobProcessor
    from datetime import datetime, timezone

    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    finalizing_job = inbox.finalizing / "jobMeta"
    finalizing_job.mkdir(parents=True)
    (finalizing_job / METADATA_FILENAME).write_text(
        _json.dumps({
            "job_id": "jobMeta",
            "source_url": "https://example.com/article",
            "collector": "test",
            "collected_at": "2026-03-28T00:00:00+00:00",
            "content_type": "html",
        }),
        encoding="utf-8",
    )
    (finalizing_job / "payload.html").write_text("<p>content</p>", encoding="utf-8")
    (finalizing_job / "READY").write_text("", encoding="utf-8")

    job = JobPaths(shared_root=shared_root, stage_dir=inbox.processing, job_id="jobMeta")
    processor = JobProcessor()
    exc = JobProtocolError("simulated error")
    started_at = datetime.now(timezone.utc)

    result_dir = processor._handle_failure(job, exc, started_at)

    assert result_dir.parent == shared_root / "failed"
    error = _json.loads((result_dir / "error.json").read_text(encoding="utf-8"))
    assert error["content_type"] == "html", f"content_type lost: {error}"
    assert error["source_url"] == "https://example.com/article", f"source_url lost: {error}"
    assert error["payload_filename"] == "payload.html", f"payload_filename lost: {error}"


def test_visual_findings_in_result_not_in_analysis_items(tmp_path, monkeypatch):
    import json as _json
    from content_ingestion.core.models import (
        AnalysisItem, ResultSummary, StructuredResult, SynthesisResult, VisualFinding,
    )
    from content_ingestion.inbox.processor import JobProcessor
    from content_ingestion.inbox.protocol import ensure_shared_inbox
    from content_ingestion.pipeline.llm_pipeline import LlmAnalysisResult
    from content_ingestion.pipeline.media_pipeline import MediaProcessingResult

    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = inbox.processing / "jobVF"
    job_dir.mkdir(parents=True)
    (job_dir / "payload.html").write_text(
        "<html><head><title>T</title></head><body><p>body</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        _json.dumps({
            "job_id": "jobVF",
            "source_url": "https://example.com",
            "collector": "test",
            "collected_at": "2026-03-28T00:00:00+00:00",
            "content_type": "html",
        }),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    structured = StructuredResult(
        content_kind="article",
        author_stance="neutral",
        summary=ResultSummary(headline="H", short_text="S"),
        analysis_items=[
            AnalysisItem(id="an-1", kind="fact", statement="Normal point",
                         evidence_segment_ids=[], confidence=0.9)
        ],
        visual_findings=[
            VisualFinding(id="vf-1", finding="Frame shows X",
                          evidence_frame_paths=["analysis/frames/frame-001.jpg"])
        ],
        synthesis=SynthesisResult(final_answer="F", next_steps=[], open_questions=[]),
    )
    fake_llm = LlmAnalysisResult(
        status="pass", provider="openai",
        structured_result=structured, summary="S",
        analysis_items=["Normal point"], verification_items=[], synthesis="F",
    )
    monkeypatch.setattr("content_ingestion.inbox.processor.analyze_asset",
                        lambda **_kw: fake_llm)
    monkeypatch.setattr("content_ingestion.inbox.processor.process_media_asset",
                        lambda **_kw: MediaProcessingResult(status="skipped", steps=[]))

    target_dir = JobProcessor().process(job_dir)
    normalized = _json.loads((target_dir / "normalized.json").read_text(encoding="utf-8"))
    result = normalized["asset"]["result"] or {}

    assert "visual_findings" in result, f"visual_findings missing: {list(result.keys())}"
    assert result["visual_findings"][0]["id"] == "vf-1"
    assert result["visual_findings"][0]["finding"] == "Frame shows X"
    for item in result.get("analysis_items", []):
        assert item.get("kind") != "visual_finding", "visual_finding leaked into analysis_items"
    assert len(result["analysis_items"]) == 1
    assert result["analysis_items"][0]["id"] == "an-1"
    assert result.get("content_kind") == "article"
    assert result.get("author_stance") == "neutral"
