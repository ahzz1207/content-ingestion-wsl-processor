from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_ingestion.core.config import Settings
from content_ingestion.pipeline.visual_summary import generate_visual_summary
from content_ingestion.core.models import (
    AnalysisItem,
    ChapterEntry,
    ContentAsset,
    EditorialBase,
    EditorialResult,
    KeyPoint,
    RelatedRef,
    ResultSummary,
    StructuredResult,
    SynthesisResult,
    VisualFinding,
    VerificationItem,
    WarningItem,
)
from content_ingestion.pipeline.llm_contract import (
    build_multimodal_verification_envelope,
    build_reader_envelope,
    build_synthesizer_envelope,
    build_text_analysis_envelope,
)


_SHARED_EDITORIAL_SCHEMA_PROPS = {
    "core_summary": {"type": "string"},
    "bottom_line": {"type": "string"},
    "content_kind": {"type": "string"},
    "author_stance": {"type": "string"},
    "audience_fit": {"type": "string"},
    "save_worthy_points": {"type": "array", "items": {"type": "string"}},
}
_SHARED_EDITORIAL_REQUIRED = [
    "core_summary",
    "bottom_line",
    "content_kind",
    "author_stance",
    "audience_fit",
    "save_worthy_points",
]

_VERIFICATION_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "id": {"type": "string"},
        "claim": {"type": "string"},
        "status": {"type": "string", "enum": ["supported", "partial", "unsupported", "unclear"]},
        "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": ["string", "null"]},
        "confidence": {"type": ["number", "null"]},
    },
    "required": ["id", "claim", "status", "evidence_segment_ids", "rationale", "confidence"],
}

ARGUMENT_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **_SHARED_EDITORIAL_SCHEMA_PROPS,
        "author_thesis": {"type": "string"},
        "evidence_backed_points": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "details": {"type": "string"},
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "title", "details", "evidence_segment_ids"],
            },
        },
        "interpretive_points": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "statement": {"type": "string"},
                    "kind": {"type": "string", "enum": ["implication", "alternative"]},
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "statement", "kind", "evidence_segment_ids"],
            },
        },
        "what_is_new": {"type": "string"},
        "tensions": {"type": "array", "items": {"type": "string"}},
        "uncertainties": {"type": "array", "items": {"type": "string"}},
        "verification_items": {"type": "array", "items": _VERIFICATION_ITEM_SCHEMA},
    },
    "required": [
        *_SHARED_EDITORIAL_REQUIRED,
        "author_thesis",
        "evidence_backed_points",
        "interpretive_points",
        "what_is_new",
        "tensions",
        "uncertainties",
        "verification_items",
    ],
}

GUIDE_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **_SHARED_EDITORIAL_SCHEMA_PROPS,
        "guide_goal": {"type": "string"},
        "recommended_steps": {"type": "array", "items": {"type": "string"}},
        "tips": {"type": "array", "items": {"type": "string"}},
        "pitfalls": {"type": "array", "items": {"type": "string"}},
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "quick_win": {"type": ["string", "null"]},
    },
    "required": [
        *_SHARED_EDITORIAL_REQUIRED,
        "guide_goal",
        "recommended_steps",
        "tips",
        "pitfalls",
        "prerequisites",
        "quick_win",
    ],
}

REVIEW_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        **_SHARED_EDITORIAL_SCHEMA_PROPS,
        "overall_judgment": {"type": "string"},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "style_and_mood": {"type": "string"},
        "what_stands_out": {"type": "string"},
        "who_it_is_for": {"type": "string"},
        "reservation_points": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        *_SHARED_EDITORIAL_REQUIRED,
        "overall_judgment",
        "highlights",
        "style_and_mood",
        "what_stands_out",
        "who_it_is_for",
        "reservation_points",
    ],
}

TEXT_ANALYSIS_SCHEMA = ARGUMENT_ANALYSIS_SCHEMA

READER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "document_type": {"type": "string", "enum": ["article", "opinion", "report", "tutorial", "interview", "thread"]},
        "thesis": {"type": "string"},
        "chapter_map": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                    "block_ids": {"type": "array", "items": {"type": "string"}},
                    "role": {"type": "string", "enum": ["setup", "argument", "evidence", "counterpoint", "conclusion", "background"]},
                    "weight": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": ["id", "title", "summary", "block_ids", "role", "weight"],
            },
        },
        "argument_skeleton": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "claim": {"type": "string"},
                    "chapter_id": {"type": "string"},
                    "claim_type": {"type": "string", "enum": ["fact", "interpretation", "implication", "rhetoric"]},
                },
                "required": ["id", "claim", "chapter_id", "claim_type"],
            },
        },
        "content_signals": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "evidence_density": {"type": "string", "enum": ["high", "medium", "low"]},
                "rhetoric_density": {"type": "string", "enum": ["high", "medium", "low"]},
                "has_novel_claim": {"type": "boolean"},
                "has_data": {"type": "boolean"},
                "estimated_depth": {"type": "string", "enum": ["shallow", "medium", "deep"]},
            },
            "required": ["evidence_density", "rhetoric_density", "has_novel_claim", "has_data", "estimated_depth"],
        },
        "suggested_mode": {"type": "string", "enum": ["argument", "guide", "review"]},
        "mode_confidence": {"type": "number"},
    },
    "required": [
        "document_type",
        "thesis",
        "chapter_map",
        "argument_skeleton",
        "content_signals",
        "suggested_mode",
        "mode_confidence",
    ],
}

MULTIMODAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "visual_findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "finding": {"type": "string"},
                    "evidence_frame_paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "finding", "evidence_frame_paths"],
            },
        },
        "verification_adjustments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "claim": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "partial", "unsupported", "unclear"]},
                    "rationale": {"type": "string"},
                    "evidence_frame_paths": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "claim", "status", "rationale", "evidence_frame_paths"],
            },
        },
        "overall_assessment": {"type": "string"},
    },
    "required": ["visual_findings", "verification_adjustments", "overall_assessment"],
}


@dataclass(slots=True)
class LlmAnalysisResult:
    status: str
    provider: str | None = None
    base_url: str | None = None
    schema_mode: str | None = None
    content_policy_id: str | None = None
    supported_input_modalities: list[str] = field(default_factory=list)
    text_input_modality: str | None = None
    multimodal_input_modality: str | None = None
    task_intent: str | None = None
    skip_reason: str | None = None
    summary: str | None = None
    key_points: list[KeyPoint] = field(default_factory=list)
    analysis_items: list[str] = field(default_factory=list)
    verification_items: list[dict[str, object]] = field(default_factory=list)
    synthesis: str | None = None
    structured_result: StructuredResult | None = None
    analysis_model: str | None = None
    multimodal_model: str | None = None
    steps: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    content_kind: str | None = None
    author_stance: str | None = None
    output_path: str | None = None
    reader_result_path: str | None = None
    synthesizer_result_path: str | None = None
    requested_mode: str = "auto"
    resolved_mode: str | None = None
    mode_confidence: float | None = None
    request_artifacts: dict[str, str] = field(default_factory=dict)


_VALID_V1_MODES = {"argument", "guide", "review"}
_MODE_SCHEMA = {
    "argument": ARGUMENT_ANALYSIS_SCHEMA,
    "guide": GUIDE_ANALYSIS_SCHEMA,
    "review": REVIEW_ANALYSIS_SCHEMA,
}


def analyze_asset(
    *,
    job_dir: Path,
    asset: ContentAsset,
    settings: Settings,
    requested_mode: str = "auto",
) -> LlmAnalysisResult:
    text_envelope = build_text_analysis_envelope(
        asset=asset,
        job_dir=job_dir,
        settings=settings,
        model=settings.analysis_model,
        output_schema_name="content_analysis",
    )
    if not settings.openai_api_key:
        missing_key_name = "ZENMUX_API_KEY" if settings.llm_provider == "zenmux" else "OPENAI_API_KEY"
        return LlmAnalysisResult(
            status="skipped",
            provider=settings.llm_provider,
            base_url=settings.openai_base_url,
            schema_mode="json_schema",
            content_policy_id=text_envelope.content_policy.policy_id,
            supported_input_modalities=list(text_envelope.content_policy.supported_input_modalities),
            text_input_modality=text_envelope.task.input_modality,
            multimodal_input_modality=text_envelope.content_policy.multimodal_input_modality,
            task_intent=text_envelope.task_intent,
            skip_reason=f"missing {missing_key_name}",
            warnings=[f"{missing_key_name} is not configured"],
            steps=[{"name": "resolve_openai_api_key", "status": "skipped", "details": f"missing {missing_key_name}"}],
        )
    if not openai_sdk_available():
        return LlmAnalysisResult(
            status="skipped",
            provider=settings.llm_provider,
            base_url=settings.openai_base_url,
            schema_mode="json_schema",
            content_policy_id=text_envelope.content_policy.policy_id,
            supported_input_modalities=list(text_envelope.content_policy.supported_input_modalities),
            text_input_modality=text_envelope.task.input_modality,
            multimodal_input_modality=text_envelope.content_policy.multimodal_input_modality,
            task_intent=text_envelope.task_intent,
            skip_reason="missing openai package",
            warnings=["openai SDK is not installed"],
            steps=[{"name": "load_openai_sdk", "status": "skipped", "details": "missing openai package"}],
        )

    client = _create_client(settings)
    analysis_dir = job_dir / "analysis" / "llm"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    result = LlmAnalysisResult(
        status="pass",
        provider=settings.llm_provider,
        base_url=settings.openai_base_url,
        schema_mode="json_schema",
        analysis_model=settings.analysis_model,
        multimodal_model=settings.multimodal_model,
        steps=[
            {"name": "resolve_openai_api_key", "status": "success", "details": "api key available"},
            {"name": "load_openai_sdk", "status": "success", "details": "openai package available"},
        ],
    )

    result.content_policy_id = text_envelope.content_policy.policy_id
    result.supported_input_modalities = list(text_envelope.content_policy.supported_input_modalities)
    result.text_input_modality = text_envelope.task.input_modality
    result.multimodal_input_modality = text_envelope.content_policy.multimodal_input_modality
    result.task_intent = text_envelope.task_intent
    # === Reader Pass ===
    reader_envelope = build_reader_envelope(
        asset=asset,
        job_dir=job_dir,
        settings=settings,
        model=settings.analysis_model,
    )
    reader_request_path = analysis_dir / "reader_request.json"
    reader_request_path.write_text(
        json.dumps(reader_envelope.to_serializable_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.request_artifacts["reader"] = reader_request_path.relative_to(job_dir).as_posix()
    reader_payload = _call_structured_response(
        client=client,
        model=settings.analysis_model,
        instructions=_reader_instructions(),
        input_payload=reader_envelope.to_model_input(),
        schema_name="reader_analysis",
        schema=READER_SCHEMA,
    )
    reader_result_path = analysis_dir / "reader_result.json"
    reader_result_path.write_text(
        json.dumps(reader_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.reader_result_path = reader_result_path.relative_to(job_dir).as_posix()
    result.steps.append({"name": "llm_reader_pass", "status": "success", "details": settings.analysis_model})
    resolved_mode, mode_confidence = _resolve_mode(requested_mode, reader_payload)
    result.requested_mode = requested_mode
    result.resolved_mode = resolved_mode
    result.mode_confidence = mode_confidence
    result.steps.append(
        {
            "name": "mode_routing",
            "status": "success",
            "details": f"{requested_mode} -> {resolved_mode} ({mode_confidence:.2f})",
        }
    )

    # === Synthesizer Pass ===
    synthesizer_envelope = build_synthesizer_envelope(
        asset=asset,
        reader_output=reader_payload,
        job_dir=job_dir,
        settings=settings,
        model=settings.analysis_model,
        output_schema_name="content_analysis",
    )
    text_request_path = analysis_dir / "text_request.json"  # kept for backward compat
    text_request_path.write_text(
        json.dumps(synthesizer_envelope.to_serializable_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.request_artifacts["text"] = text_request_path.relative_to(job_dir).as_posix()
    text_payload = _call_structured_response(
        client=client,
        model=settings.analysis_model,
        instructions=_synthesizer_instructions_for_mode(resolved_mode),
        input_payload=synthesizer_envelope.to_model_input(),
        schema_name="content_analysis",
        schema=_MODE_SCHEMA.get(resolved_mode, ARGUMENT_ANALYSIS_SCHEMA),
    )
    synthesizer_result_path = analysis_dir / "synthesizer_result.json"
    synthesizer_result_path.write_text(
        json.dumps(text_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.synthesizer_result_path = synthesizer_result_path.relative_to(job_dir).as_posix()
    result.steps.append({"name": "llm_synthesizer_pass", "status": "success", "details": settings.analysis_model})
    structured_result = _build_structured_result(
        text_payload,
        reader_payload=reader_payload,
        requested_mode=requested_mode,
        resolved_mode=resolved_mode,
        mode_confidence=mode_confidence,
    )
    valid_evidence_segment_ids = {segment.id for segment in asset.evidence_segments}
    validation_warnings = _validate_structured_result_evidence(
        structured_result,
        valid_evidence_segment_ids=valid_evidence_segment_ids,
    )
    if validation_warnings:
        repaired_payload = _repair_structured_result_payload(
            client=client,
            model=settings.analysis_model,
            original_payload=text_payload,
            valid_evidence_segment_ids=valid_evidence_segment_ids,
            validation_warnings=[item.message for item in validation_warnings],
        )
        if repaired_payload is not None:
            repaired_result = _build_structured_result(
                repaired_payload,
                reader_payload=reader_payload,
                requested_mode=requested_mode,
                resolved_mode=resolved_mode,
                mode_confidence=mode_confidence,
            )
            repaired_warnings = _validate_structured_result_evidence(
                repaired_result,
                valid_evidence_segment_ids=valid_evidence_segment_ids,
            )
            result.steps.append({"name": "repair_evidence_references", "status": "success", "details": settings.analysis_model})
            structured_result = repaired_result
            validation_warnings = repaired_warnings
        else:
            result.steps.append({"name": "repair_evidence_references", "status": "skipped", "details": "repair unavailable"})
    if validation_warnings:
        result.warnings.extend(item.message for item in validation_warnings)
        result.steps.append(
            {
                "name": "validate_evidence_references",
                "status": "warn",
                "details": f"{len(validation_warnings)} evidence reference issue(s)",
            }
        )
    else:
        result.steps.append({"name": "validate_evidence_references", "status": "success", "details": "all references valid"})
    result.structured_result = structured_result
    result.content_kind = structured_result.content_kind
    result.author_stance = structured_result.author_stance
    if structured_result.summary is not None:
        if structured_result.summary and isinstance(structured_result.summary.short_text, str):
            result.summary = structured_result.summary.short_text.strip()
    result.key_points = structured_result.key_points
    result.analysis_items = [item.statement for item in structured_result.analysis_items if item.statement.strip()]
    result.verification_items = [_serialize_verification_item(item) for item in structured_result.verification_items]
    if structured_result.synthesis is not None:
        result.synthesis = structured_result.synthesis.final_answer.strip()

    frame_paths = _collect_frame_paths(job_dir, asset)
    if frame_paths:
        multimodal_envelope = build_multimodal_verification_envelope(
            asset=asset,
            settings=settings,
            model=settings.multimodal_model,
            output_schema_name="content_multimodal_verification",
            frame_paths=frame_paths,
        )
        result.multimodal_input_modality = multimodal_envelope.task.input_modality
        multimodal_request_path = analysis_dir / "multimodal_request.json"
        multimodal_request_path.write_text(
            json.dumps(multimodal_envelope.to_serializable_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        result.request_artifacts["multimodal"] = multimodal_request_path.relative_to(job_dir).as_posix()
        multimodal_payload = _call_structured_response(
            client=client,
            model=settings.multimodal_model,
            instructions=_multimodal_instructions(),
            input_payload=multimodal_envelope.to_model_input(),
            schema_name="content_multimodal_verification",
            schema=MULTIMODAL_SCHEMA,
        )
        result.steps.append(
            {"name": "llm_multimodal_verification", "status": "success", "details": settings.multimodal_model}
        )
        if result.structured_result is None:
            result.structured_result = StructuredResult()
        for item in multimodal_payload["visual_findings"]:
            result.structured_result.visual_findings.append(
                VisualFinding(
                    id=str(item["id"]).strip(),
                    finding=str(item["finding"]).strip(),
                    evidence_frame_paths=[str(p) for p in item.get("evidence_frame_paths", [])],
                )
            )
        for item in multimodal_payload["verification_adjustments"]:
            verification_item = VerificationItem(
                id=str(item["id"]).strip(),
                claim=str(item["claim"]).strip(),
                status=str(item["status"]).strip(),
                evidence_segment_ids=[],
                rationale=str(item["rationale"]).strip(),
                confidence=None,
            )
            result.structured_result.verification_items.append(verification_item)
            serialized = _serialize_verification_item(verification_item)
            serialized["evidence_frame_paths"] = [str(path) for path in item["evidence_frame_paths"]]
            result.verification_items.append(serialized)
        if result.structured_result.synthesis is None:
            result.structured_result.synthesis = SynthesisResult(
                final_answer=str(multimodal_payload["overall_assessment"]).strip(),
                next_steps=[],
                open_questions=[],
            )
        if not result.synthesis:
            result.synthesis = str(multimodal_payload["overall_assessment"]).strip()

    # === Visual Summary Card ===
    insight_card_path = None
    if settings.image_card_model:
        try:
            from google import genai
            from google.genai import types as genai_types
            image_api_key = settings.image_card_api_key or settings.openai_api_key
            image_base_url = settings.image_card_base_url or "https://zenmux.ai/api/vertex-ai"
            image_client = genai.Client(
                api_key=image_api_key,
                vertexai=True,
                http_options=genai_types.HttpOptions(
                    api_version="v1",
                    base_url=image_base_url,
                ),
            )
            card_output = job_dir / "analysis" / "insight_card.png"
            card_step = generate_visual_summary(
                client=image_client,
                model=settings.image_card_model,
                structured_result=structured_result,
                resolved_mode=resolved_mode,
                asset_title=asset.title or "",
                output_path=card_output,
            )
            result.steps.append(card_step)
            if card_step["status"] == "success":
                insight_card_path = card_output.relative_to(job_dir).as_posix()
        except Exception as exc:
            logger.warning("Visual summary card generation failed: %s", exc)
            result.steps.append({
                "name": "visual_summary_card",
                "status": "skipped",
                "details": f"generation failed: {exc}",
            })
            result.warnings.append(f"Visual summary card skipped: {exc}")

    output_path = analysis_dir / "analysis_result.json"
    output_path.write_text(
        json.dumps(
            {
                "status": result.status,
                "content_kind": result.content_kind,
                "author_stance": result.author_stance,
                "provider": result.provider,
                "base_url": result.base_url,
                "schema_mode": result.schema_mode,
                "content_policy_id": result.content_policy_id,
                "supported_input_modalities": result.supported_input_modalities,
                "text_input_modality": result.text_input_modality,
                "multimodal_input_modality": result.multimodal_input_modality,
                "task_intent": result.task_intent,
                "skip_reason": result.skip_reason,
                "requested_mode": result.requested_mode,
                "resolved_mode": result.resolved_mode,
                "mode_confidence": result.mode_confidence,
                "reader_result_path": result.reader_result_path,
                "synthesizer_result_path": result.synthesizer_result_path,
                "request_artifacts": result.request_artifacts,
                "summary": result.summary,
                "key_points": [_serialize_key_point(item) for item in result.key_points],
                "analysis_items": result.analysis_items,
                "verification_items": result.verification_items,
                "synthesis": result.synthesis,
                "result": _serialize_structured_result(result.structured_result),
                "analysis_model": result.analysis_model,
                "multimodal_model": result.multimodal_model,
                "warnings": result.warnings,
                "insight_card_path": insight_card_path,
                "steps": result.steps,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result.output_path = output_path.relative_to(job_dir).as_posix()
    return result


def openai_sdk_available() -> bool:
    return importlib.util.find_spec("openai") is not None


def _create_client(settings: Settings):
    module = importlib.import_module("openai")
    client_kwargs = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        client_kwargs["base_url"] = settings.openai_base_url
    return module.OpenAI(**client_kwargs)


def _call_structured_response(*, client, model: str, instructions: str, input_payload, schema_name: str, schema: dict):
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=input_payload,
        text={
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "schema": schema,
                "strict": True,
            }
        },
    )
    return json.loads(response.output_text)


def _repair_structured_result_payload(
    *,
    client,
    model: str,
    original_payload: dict[str, Any],
    valid_evidence_segment_ids: set[str],
    validation_warnings: list[str],
) -> dict[str, Any] | None:
    if not valid_evidence_segment_ids:
        return None
    repair_input = {
        "valid_evidence_segment_ids": sorted(valid_evidence_segment_ids),
        "validation_warnings": validation_warnings,
        "original_result": original_payload,
    }
    try:
        return _call_structured_response(
            client=client,
            model=model,
            instructions=_repair_instructions(),
            input_payload=json.dumps(repair_input, ensure_ascii=False, indent=2),
            schema_name="content_analysis_repair",
            schema=TEXT_ANALYSIS_SCHEMA,
        )
    except Exception as repair_exc:
        logger.warning("structured result repair attempt failed: %s", repair_exc)
        return None


def _collect_frame_paths(job_dir: Path, asset: ContentAsset) -> list[Path]:
    frame_paths: list[Path] = []
    for attachment in asset.attachments:
        if attachment.role != "analysis_frame":
            continue
        frame_path = job_dir.joinpath(*Path(attachment.path).parts)
        if frame_path.exists():
            frame_paths.append(frame_path)
    return frame_paths


def _reader_instructions() -> str:
    return """You are a structural analyst. Your only job is to identify the shape of the content — not to evaluate it.

DO NOT extract opinions, write summaries, or make quality judgments.

YOUR TASKS:
1. DOCUMENT TYPE — Classify the content type.
2. THESIS — State the author's core claim in 1-2 sentences based strictly on the text.
3. CHAPTER MAP — Identify 3-8 semantic sections. For each section:
   - summary: 1-2 sentences capturing what this section actually says (not evaluates).
   - block_ids: the block id values from the input that belong to this section.
   - role: setup / argument / evidence / counterpoint / conclusion / background.
   - weight: high (core to understanding) / medium / low (context or filler).
4. ARGUMENT SKELETON — For each chapter, state the main claim.
   - claim_type: fact (verifiable assertion) / interpretation (reading or inference) / implication (unstated consequence) / rhetoric (persuasion without direct claim).
5. CONTENT SIGNALS — Signal properties to guide downstream analysis.

RULES:
- block_ids must exactly match ids from the input document blocks.
- Chapter count must be between 3 and 8. If content is short, use 3.
- Chapter summaries must be based on what the section says, not your judgment of its quality.
- Do not skip any major section."""


def _synthesizer_instructions() -> str:
    return """You are a critical-thinking analyst. You receive a document plus a Reader's structural analysis.
Use the reader_output — especially chapter_map summaries and argument_skeleton — to focus your analysis.
You do not need to re-read all blocks in detail. Trust the Reader's structure.

GOAL 1 — VIEWPOINTS (key_points)
Focus on chapters with weight="high" in the Reader's chapter_map.
For each key chapter, extract 1-2 core arguments. Aim for 5-10 key_points total.
For each key_point, write details covering THREE dimensions:
  (a) What is the argument?
  (b) What logic and evidence does the author use to support it?
  (c) How does this argument relate to others in the piece (reinforces / contradicts / builds on)?
Never shorten the details to make room for evidence IDs. Evidence annotation is secondary.

GOAL 2 — CRITICAL CHECK (verification_items)
Flag claims that are questionable, unsupported, or in tension with established knowledge.
Explicitly label each as: "text directly states" or "analyst inference."
Status: supported / partial / unsupported / unclear.

GOAL 3 — DIVERGENT THINKING (analysis_items)
Generate 3-5 implications and alternative perspectives the content raises but does not address.
Label each: "implication" (logical consequence not stated) or "alternative" (different reading or counter-argument).

GOAL 4 — SYNTHESIS
final_answer: What should a reader take away as a judgment? Not a restatement of arguments.

what_is_new: What is genuinely novel in this content?
  Do NOT report what the author claims is new.
  DO identify: what information, perspective, or combination is actually new compared to common knowledge on this topic?
  If nothing is genuinely new, say so plainly.

tensions: List real tensions in the author's position. Three types to consider:
  - Internal tension: claims within the piece that contradict or undercut each other.
  - Evidence-judgment tension: places where the evidence cited does not fully support the conclusion drawn.
  - Expression-argument tension: where the rhetorical goal seems to conflict with the argument structure.
  If no real tensions exist, return an empty list. Do not manufacture tensions.

GENERAL RULES:
- Use only evidence_segment_ids from the evidence_segments list. Never invent IDs.
- content_kind: article / opinion / analysis / report / interview / tutorial / review / news.
- author_stance: objective / advocacy / critical / skeptical / promotional / explanatory / mixed.
- All analysis_items must have kind = "implication" or "alternative" only."""


def _analysis_instructions() -> str:
    return """You are a critical-thinking analyst. Analyze the provided content following four goals exactly.

GOAL 1 - OVERVIEW
Identify the central topic and the author's core position. Express this as a precise headline and one sentence capturing the author's core claim. Stay grounded in what the author actually says.
Also identify:
- content_kind: the type of content (choose one: article, opinion, analysis, report, interview, tutorial, review, news)
- author_stance: the author's rhetorical posture (choose one: objective, advocacy, critical, skeptical, promotional, explanatory, mixed)

GOAL 2 - VIEWPOINTS
Extract every distinct argument or claim the author makes. Aim for 5 to 10 viewpoints. For each:
- Write a concise title naming the argument.
- Write a detailed explanation of 3 to 5 sentences capturing the author's reasoning, supporting context, and implication.
Evidence annotation is secondary: never shorten an explanation to attach evidence IDs. If no evidence segment matches, use an empty list.

GOAL 3 - CRITICAL CHECK
Identify claims that are questionable, unsupported, or in tension with established knowledge. For each:
- State the exact claim.
- Assess its status: supported / partial / unsupported / unclear.
- Provide a rationale explaining your assessment.
Only flag claims that genuinely merit scrutiny. Do not manufacture doubts about well-supported statements.

GOAL 4 - DIVERGENT THINKING
Generate non-obvious implications and alternative perspectives the content raises but does not address. Produce at least 3 items. Each must be labeled:
- "implication": a logical consequence of the author's position not explicitly stated.
- "alternative": a different reading, counter-argument, or perspective that reframes the author's position.
Do not restate the author's content. Add analytical value beyond what is on the page.

GENERAL RULES
- Use only evidence segment IDs that appear in the evidence_segments list. Never invent IDs.
- If no segment matches, use an empty evidence_segment_ids list.
- Do not apply word limits to any field.
- All analysis_items must have kind equal to "implication" or "alternative". No other values are valid."""


def _resolve_mode(requested_mode: str, reader_payload: dict[str, object]) -> tuple[str, float]:
    if requested_mode in _VALID_V1_MODES:
        return requested_mode, 1.0
    suggested = str(reader_payload.get("suggested_mode") or "").strip()
    confidence = float(reader_payload.get("mode_confidence") or 0.5)
    if suggested in _VALID_V1_MODES:
        return suggested, confidence
    return "argument", 0.5


def _reader_instructions() -> str:
    return """You are a structural analyst. Your only job is to identify the shape of the content and suggest the best reading mode.

DO NOT extract opinions, write summaries, or make quality judgments.

YOUR TASKS:
1. DOCUMENT TYPE - Classify the content type.
2. THESIS - State the author's core claim in 1-2 sentences based strictly on the text.
3. CHAPTER MAP - Identify 3-8 semantic sections. For each section:
   - summary: 1-2 sentences capturing what this section actually says.
   - block_ids: the block id values from the input that belong to this section.
   - role: setup / argument / evidence / counterpoint / conclusion / background.
   - weight: high / medium / low.
4. ARGUMENT SKELETON - For each chapter, state the main claim.
   - claim_type: fact / interpretation / implication / rhetoric.
5. CONTENT SIGNALS - Signal properties to guide downstream analysis.
6. MODE SUGGESTION - Choose the best v1 analysis mode:
   - argument: commentary, issue analysis, debate, opinion, macro reading
   - guide: tutorial, walkthrough, advice, how-to, practical instructions
   - review: recommendation, curation, taste judgment, exhibition/album/product review
   Set mode_confidence between 0.0 and 1.0.
"""


def _synthesizer_instructions_argument() -> str:
    return """You are a critical analyst producing an argument-focused editorial result.
Use the Reader output to organize your synthesis instead of re-reading every block equally.

Required fields:
- core_summary
- bottom_line
- content_kind
- author_stance
- audience_fit
- save_worthy_points
- author_thesis
- evidence_backed_points
- interpretive_points
- what_is_new
- tensions
- uncertainties
- verification_items

Rules:
- Use only evidence_segment_ids from the evidence_segments list.
- Do not invent evidence ids.
- Keep interpretive points separate from evidence-backed points.

LANGUAGE: All text output fields (core_summary, bottom_line, author_thesis, evidence_backed_points titles/details, interpretive_points, what_is_new, tensions, uncertainties, audience_fit, save_worthy_points, verification_items claims/rationale) MUST be written in Simplified Chinese. Do not use English for any user-facing text field."""


def _synthesizer_instructions_guide() -> str:
    return """You are an editor producing a practical guide-oriented result.
Focus on usability, sequence, and practical value.

Required fields:
- core_summary
- bottom_line
- content_kind
- author_stance
- audience_fit
- save_worthy_points
- guide_goal
- recommended_steps
- tips
- pitfalls
- prerequisites
- quick_win

LANGUAGE: All text output fields MUST be written in Simplified Chinese. Do not use English for any user-facing text field."""


def _synthesizer_instructions_review() -> str:
    return """You are an editor producing a recommendation/review-oriented result.
Focus on judgment, highlights, style, and audience fit.

Required fields:
- core_summary
- bottom_line
- content_kind
- author_stance
- audience_fit
- save_worthy_points
- overall_judgment
- highlights
- style_and_mood
- what_stands_out
- who_it_is_for
- reservation_points

LANGUAGE: All text output fields MUST be written in Simplified Chinese. Do not use English for any user-facing text field."""


def _synthesizer_instructions_for_mode(resolved_mode: str) -> str:
    if resolved_mode == "guide":
        return _synthesizer_instructions_guide()
    if resolved_mode == "review":
        return _synthesizer_instructions_review()
    return _synthesizer_instructions_argument()


def _analysis_instructions() -> str:
    return """You are a critical-thinking analyst. Analyze the provided content following four goals exactly.

GOAL 1 — OVERVIEW
Identify the central topic and the author's core position. Express this as a precise headline and one sentence capturing the author's core claim. Stay grounded in what the author actually says.
Also identify:
- content_kind: the type of content (choose one: article, opinion, analysis, report, interview, tutorial, review, news)
- author_stance: the author's rhetorical posture (choose one: objective, advocacy, critical, skeptical, promotional, explanatory, mixed)

GOAL 2 — VIEWPOINTS
Extract every distinct argument or claim the author makes. Aim for 5 to 10 viewpoints. For each:
- Write a concise title naming the argument.
- Write a detailed explanation of 3 to 5 sentences capturing the author's reasoning, supporting context, and implication.
Evidence annotation is secondary: never shorten an explanation to attach evidence IDs. If no evidence segment matches, use an empty list.

GOAL 3 — CRITICAL CHECK
Identify claims that are questionable, unsupported, or in tension with established knowledge. For each:
- State the exact claim.
- Assess its status: supported / partial / unsupported / unclear.
- Provide a rationale explaining your assessment.
Only flag claims that genuinely merit scrutiny. Do not manufacture doubts about well-supported statements.

GOAL 4 — DIVERGENT THINKING
Generate non-obvious implications and alternative perspectives the content raises but does not address. Produce at least 3 items. Each must be labeled:
- "implication": a logical consequence of the author's position not explicitly stated.
- "alternative": a different reading, counter-argument, or perspective that reframes the author's position.
Do not restate the author's content. Add analytical value beyond what is on the page.

GENERAL RULES
- Use only evidence segment IDs that appear in the evidence_segments list. Never invent IDs.
- If no segment matches, use an empty evidence_segment_ids list.
- Do not apply word limits to any field.
- All analysis_items must have kind equal to "implication" or "alternative". No other values are valid."""


def _multimodal_instructions() -> str:
    return (
        "You are validating transcript-based analysis against extracted video frames. "
        "Return visual findings, verification adjustments, and an overall assessment. "
        "Do not invent claims that are not supported by the frames or transcript."
    )


def _repair_instructions() -> str:
    return (
        "You are repairing a structured analysis result. "
        "You will receive a previous JSON result, a list of valid evidence segment ids, and validation warnings. "
        "Return the same schema, but remove or replace invalid evidence references using only the valid ids provided. "
        "If a claim no longer has valid evidence, use an empty evidence list and prefer conservative outputs."
    )


def _build_structured_result(
    payload: dict[str, object],
    *,
    reader_payload: dict[str, object] | None = None,
    requested_mode: str,
    resolved_mode: str,
    mode_confidence: float | None,
    ) -> StructuredResult:
    content_kind = str(payload.get("content_kind") or "").strip() or None
    author_stance = str(payload.get("author_stance") or "").strip() or None
    chapter_map = []
    if reader_payload:
        chapter_map = [
            ChapterEntry(
                id=str(ch["id"]).strip(),
                title=str(ch["title"]).strip(),
                role=str(ch["role"]).strip(),
                summary=str(ch.get("summary") or "").strip(),
                block_ids=[str(bid).strip() for bid in ch.get("block_ids", [])],
                weight=str(ch.get("weight", "medium")).strip(),
            )
            for ch in reader_payload.get("chapter_map", [])
        ]
    editorial_base = EditorialBase(
        core_summary=str(payload.get("core_summary") or "").strip(),
        bottom_line=str(payload.get("bottom_line") or "").strip(),
        audience_fit=str(payload.get("audience_fit") or "").strip(),
        save_worthy_points=[str(item).strip() for item in payload.get("save_worthy_points", []) if str(item).strip()],
    )
    mode_payload = _build_editorial_mode_payload(resolved_mode, payload)
    product_view = _build_product_view(resolved_mode, editorial_base, mode_payload)
    return StructuredResult(
        content_kind=content_kind,
        author_stance=author_stance,
        summary=_build_legacy_summary(resolved_mode, editorial_base, mode_payload),
        key_points=_build_legacy_key_points(resolved_mode, mode_payload),
        analysis_items=_build_legacy_analysis_items(resolved_mode, mode_payload),
        verification_items=_build_legacy_verification_items(payload if resolved_mode == "argument" else {}),
        synthesis=_build_legacy_synthesis(resolved_mode, editorial_base, mode_payload),
        chapter_map=chapter_map,
        editorial=EditorialResult(
            requested_mode=requested_mode,
            resolved_mode=resolved_mode,
            mode_confidence=mode_confidence if mode_confidence is not None else 0.0,
            base=editorial_base,
            mode_payload=mode_payload,
        ),
        product_view=product_view,
    )


def _coerce_confidence(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _serialize_key_point(item: KeyPoint) -> dict[str, object]:
    return {
        "id": item.id,
        "title": item.title,
        "details": item.details,
        "evidence_segment_ids": item.evidence_segment_ids,
    }


def _serialize_verification_item(item: VerificationItem) -> dict[str, object]:
    return {
        "id": item.id,
        "claim": item.claim,
        "status": item.status,
        "evidence_segment_ids": item.evidence_segment_ids,
        "rationale": item.rationale,
        "confidence": item.confidence,
    }


def _serialize_warning_item(item: WarningItem) -> dict[str, object]:
    return {
        "code": item.code,
        "severity": item.severity,
        "message": item.message,
        "related_refs": [
            {
                "kind": ref.kind,
                "id": ref.id,
                "role": ref.role,
            }
            for ref in item.related_refs
        ],
    }


def _serialize_structured_result(result: StructuredResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "content_kind": result.content_kind,
        "author_stance": result.author_stance,
        "summary": None
        if result.summary is None
        else {
            "headline": result.summary.headline,
            "short_text": result.summary.short_text,
        },
        "key_points": [_serialize_key_point(item) for item in result.key_points],
        "analysis_items": [
            {
                "id": item.id,
                "kind": item.kind,
                "statement": item.statement,
                "evidence_segment_ids": item.evidence_segment_ids,
                "confidence": item.confidence,
            }
            for item in result.analysis_items
        ],
        "visual_findings": [
            {
                "id": item.id,
                "finding": item.finding,
                "evidence_frame_paths": item.evidence_frame_paths,
            }
            for item in result.visual_findings
        ],
        "verification_items": [_serialize_verification_item(item) for item in result.verification_items],
        "synthesis": None
        if result.synthesis is None
        else {
            "final_answer": result.synthesis.final_answer,
            "what_is_new": result.synthesis.what_is_new,
            "tensions": result.synthesis.tensions,
            "next_steps": result.synthesis.next_steps,
            "open_questions": result.synthesis.open_questions,
        },
        "chapter_map": [
            {
                "id": item.id,
                "title": item.title,
                "role": item.role,
                "summary": item.summary,
                "block_ids": item.block_ids,
                "weight": item.weight,
            }
            for item in result.chapter_map
        ],
        "warnings": [_serialize_warning_item(item) for item in result.warnings],
        "editorial": _serialize_editorial_result(result.editorial),
        "product_view": result.product_view,
    }


def _build_product_view(
    resolved_mode: str,
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> dict[str, object] | None:
    builders = {
        "argument": _build_argument_product_view,
        "guide": _build_guide_product_view,
        "review": _build_review_product_view,
    }
    builder = builders.get(resolved_mode)
    if builder is None:
        return None
    return builder(editorial_base, mode_payload)


def _paragraph_block(text: str) -> dict[str, object]:
    return {"type": "paragraph", "text": text}


def _bullet_list_block(items: list[str]) -> dict[str, object]:
    return {"type": "bullet_list", "items": items}


def _step_list_block(items: list[str]) -> dict[str, object]:
    return {"type": "step_list", "items": items}


def _reader_value_section(
    title: str,
    editorial_base: EditorialBase,
    extra_bits: list[str] | None = None,
) -> dict[str, object]:
    bits = [editorial_base.bottom_line.strip()]
    if editorial_base.audience_fit.strip():
        bits.append(editorial_base.audience_fit.strip())
    if editorial_base.save_worthy_points:
        bits.append(editorial_base.save_worthy_points[0])
    if extra_bits:
        bits.extend(extra_bits)
    body = " ".join(bit for bit in bits if bit).strip()
    if not body:
        body = editorial_base.core_summary.strip()
    return {
        "kind": "reader_value",
        "title": title,
        "blocks": [_paragraph_block(body)] if body else [],
    }


def _cap_sections(sections: list[dict[str, object]], max_body: int = 4) -> list[dict[str, object]]:
    if len(sections) <= max_body + 1:
        return sections
    return sections[:max_body] + [sections[-1]]


def _wrap_product_view(
    layout: str,
    hero_title: str,
    hero_dek: str,
    hero_bottom_line: str,
    sections: list[dict[str, object]],
) -> dict[str, object] | None:
    if not hero_title:
        return None
    return {
        "hero": {
            "title": hero_title,
            "dek": hero_dek,
            "bottom_line": hero_bottom_line,
        },
        "layout": layout,
        "sections": sections,
        "render_hints": {
            "layout_family": layout,
        },
    }


def _build_argument_product_view(
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> dict[str, object] | None:
    hero_title = str(mode_payload.get("author_thesis") or editorial_base.core_summary or editorial_base.bottom_line).strip()
    hero_dek = editorial_base.core_summary.strip()
    hero_bottom_line = editorial_base.bottom_line.strip()

    sections: list[dict[str, object]] = []

    for item in mode_payload.get("evidence_backed_points", []):
        title = str(item.get("title") or "").strip()
        details = str(item.get("details") or "").strip()
        if not title or not details:
            continue
        sections.append({"kind": "question_block", "title": title, "blocks": [_paragraph_block(details)]})
        if len(sections) == 2:
            break

    if not sections:
        fallback = hero_title or hero_dek or hero_bottom_line
        if fallback:
            sections.append({"kind": "question_block", "title": "核心判断是什么？", "blocks": [_paragraph_block(fallback)]})

    interpretive_points = mode_payload.get("interpretive_points", [])
    first_interpretive = interpretive_points[0] if interpretive_points else None
    interpretive_statement = ""
    if isinstance(first_interpretive, dict):
        interpretive_statement = str(first_interpretive.get("statement") or "").strip()
    if interpretive_statement:
        sections.append({"kind": "question_block", "title": "接下来会带来什么影响？", "blocks": [_paragraph_block(interpretive_statement)]})
    else:
        what_is_new = str(mode_payload.get("what_is_new") or "").strip()
        first_tension = next((str(item).strip() for item in mode_payload.get("tensions", []) if str(item).strip()), "")
        middle = what_is_new or first_tension or hero_dek or hero_title
        if middle:
            sections.append({"kind": "question_block", "title": "最值得注意的点是什么？", "blocks": [_paragraph_block(middle)]})

    sections.append(_reader_value_section("这对我意味着什么？", editorial_base))

    question_sections = [s for s in sections[:-1] if s["kind"] == "question_block"]
    if len(question_sections) < 2:
        filler = str(mode_payload.get("what_is_new") or "").strip() or hero_dek or hero_title
        if filler:
            sections.insert(max(len(sections) - 1, 0), {"kind": "question_block", "title": "为什么值得关注？", "blocks": [_paragraph_block(filler)]})

    sections = _cap_sections(sections)
    return _wrap_product_view("analysis_brief", hero_title, hero_dek, hero_bottom_line, sections)


def _build_guide_product_view(
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> dict[str, object] | None:
    guide_goal = str(mode_payload.get("guide_goal") or "").strip()
    hero_title = guide_goal or editorial_base.core_summary.strip()
    hero_dek = editorial_base.core_summary.strip()
    quick_win = str(mode_payload.get("quick_win") or "").strip()
    hero_bottom_line = quick_win or editorial_base.bottom_line.strip()

    sections: list[dict[str, object]] = []
    steps = [str(s).strip() for s in mode_payload.get("recommended_steps", []) if str(s).strip()]
    tips = [str(t).strip() for t in mode_payload.get("tips", []) if str(t).strip()]
    pitfalls = [str(p).strip() for p in mode_payload.get("pitfalls", []) if str(p).strip()]

    step_titles = ["第一步该怎么做？", "然后呢？", "还需要注意什么？"]
    if steps:
        chunk_size = max(1, len(steps) // min(3, len(steps)))
        for i in range(0, len(steps), chunk_size):
            chunk = steps[i:i + chunk_size]
            title = step_titles[min(i // chunk_size, len(step_titles) - 1)]
            sections.append({"kind": "action_step", "title": title, "blocks": [_step_list_block(chunk)]})
            if len(sections) >= 3:
                break
    elif tips:
        sections.append({"kind": "action_step", "title": "第一步该怎么做？", "blocks": [_bullet_list_block(tips[:3])]})

    if not sections:
        fallback = editorial_base.core_summary.strip() or hero_title
        if fallback:
            sections.append({"kind": "action_step", "title": "核心要点是什么？", "blocks": [_paragraph_block(fallback)]})

    if tips and steps:
        sections.append({"kind": "tip_block", "title": "有什么实用技巧？", "blocks": [_bullet_list_block(tips[:5])]})

    if pitfalls:
        sections.append({"kind": "pitfall_warning", "title": "容易踩什么坑？", "blocks": [_bullet_list_block(pitfalls[:5])]})

    extra = [quick_win] if quick_win else []
    sections.append(_reader_value_section("这对我意味着什么？", editorial_base, extra))

    sections = _cap_sections(sections)
    return _wrap_product_view("practical_guide", hero_title, hero_dek, hero_bottom_line, sections)


def _build_review_product_view(
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> dict[str, object] | None:
    overall_judgment = str(mode_payload.get("overall_judgment") or "").strip()
    hero_title = overall_judgment or editorial_base.core_summary.strip()
    hero_dek = editorial_base.core_summary.strip()
    hero_bottom_line = editorial_base.bottom_line.strip()

    sections: list[dict[str, object]] = []
    highlights = [str(h).strip() for h in mode_payload.get("highlights", []) if str(h).strip()]
    what_stands_out = str(mode_payload.get("what_stands_out") or "").strip()
    style_and_mood = str(mode_payload.get("style_and_mood") or "").strip()
    reservation_points = [str(r).strip() for r in mode_payload.get("reservation_points", []) if str(r).strip()]
    who_it_is_for = str(mode_payload.get("who_it_is_for") or "").strip()

    if highlights:
        if len(highlights) == 1:
            sections.append({"kind": "highlight_block", "title": "最值得关注的亮点是什么？", "blocks": [_paragraph_block(highlights[0])]})
        else:
            sections.append({"kind": "highlight_block", "title": "最值得关注的亮点是什么？", "blocks": [_bullet_list_block(highlights[:5])]})
    elif what_stands_out:
        sections.append({"kind": "highlight_block", "title": "最值得关注的亮点是什么？", "blocks": [_paragraph_block(what_stands_out)]})

    standout_text = " ".join(part for part in [what_stands_out, style_and_mood] if part).strip()
    if standout_text and highlights:
        sections.append({"kind": "standout_block", "title": "最让人印象深刻的是什么？", "blocks": [_paragraph_block(standout_text)]})

    if reservation_points:
        sections.append({"kind": "reservation_block", "title": "有什么保留意见？", "blocks": [_bullet_list_block(reservation_points[:5])]})

    if not sections:
        fallback = editorial_base.core_summary.strip() or hero_title
        if fallback:
            sections.append({"kind": "highlight_block", "title": "最值得关注的亮点是什么？", "blocks": [_paragraph_block(fallback)]})

    extra = [who_it_is_for] if who_it_is_for else []
    sections.append(_reader_value_section("这适合什么样的人？", editorial_base, extra))

    sections = _cap_sections(sections)
    return _wrap_product_view("review_curation", hero_title, hero_dek, hero_bottom_line, sections)


def _build_editorial_mode_payload(resolved_mode: str, payload: dict[str, object]) -> dict[str, object]:
    if resolved_mode == "guide":
        return {
            "guide_goal": str(payload.get("guide_goal") or "").strip(),
            "recommended_steps": [str(item).strip() for item in payload.get("recommended_steps", []) if str(item).strip()],
            "tips": [str(item).strip() for item in payload.get("tips", []) if str(item).strip()],
            "pitfalls": [str(item).strip() for item in payload.get("pitfalls", []) if str(item).strip()],
            "prerequisites": [str(item).strip() for item in payload.get("prerequisites", []) if str(item).strip()],
            "quick_win": str(payload.get("quick_win") or "").strip() or None,
        }
    if resolved_mode == "review":
        return {
            "overall_judgment": str(payload.get("overall_judgment") or "").strip(),
            "highlights": [str(item).strip() for item in payload.get("highlights", []) if str(item).strip()],
            "style_and_mood": str(payload.get("style_and_mood") or "").strip(),
            "what_stands_out": str(payload.get("what_stands_out") or "").strip(),
            "who_it_is_for": str(payload.get("who_it_is_for") or "").strip(),
            "reservation_points": [str(item).strip() for item in payload.get("reservation_points", []) if str(item).strip()],
        }
    return {
        "author_thesis": str(payload.get("author_thesis") or "").strip(),
        "evidence_backed_points": [
            {
                "id": str(item.get("id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "details": str(item.get("details") or "").strip(),
                "evidence_segment_ids": [
                    str(value).strip()
                    for value in item.get("evidence_segment_ids", [])
                    if str(value).strip()
                ],
            }
            for item in payload.get("evidence_backed_points", [])
        ],
        "interpretive_points": [
            {
                "id": str(item.get("id") or "").strip(),
                "statement": str(item.get("statement") or "").strip(),
                "kind": str(item.get("kind") or "").strip(),
                "evidence_segment_ids": [
                    str(value).strip()
                    for value in item.get("evidence_segment_ids", [])
                    if str(value).strip()
                ],
            }
            for item in payload.get("interpretive_points", [])
        ],
        "what_is_new": str(payload.get("what_is_new") or "").strip(),
        "tensions": [str(item).strip() for item in payload.get("tensions", []) if str(item).strip()],
        "uncertainties": [str(item).strip() for item in payload.get("uncertainties", []) if str(item).strip()],
        "verification_items": [
            _serialize_verification_item(
                VerificationItem(
                    id=str(item.get("id") or "").strip(),
                    claim=str(item.get("claim") or "").strip(),
                    status=str(item.get("status") or "").strip(),
                    evidence_segment_ids=[
                        str(value).strip()
                        for value in item.get("evidence_segment_ids", [])
                        if str(value).strip()
                    ],
                    rationale=str(item.get("rationale")).strip() if item.get("rationale") is not None else None,
                    confidence=_coerce_confidence(item.get("confidence")),
                )
            )
            for item in payload.get("verification_items", [])
        ],
    }


def _build_legacy_summary(
    resolved_mode: str,
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> ResultSummary:
    if resolved_mode == "guide":
        headline = str(mode_payload.get("guide_goal") or editorial_base.core_summary).strip()
    elif resolved_mode == "review":
        headline = str(mode_payload.get("overall_judgment") or editorial_base.core_summary).strip()
    else:
        headline = str(mode_payload.get("author_thesis") or editorial_base.core_summary).strip()
    return ResultSummary(
        headline=headline or editorial_base.core_summary,
        short_text=editorial_base.core_summary,
    )


def _build_legacy_key_points(resolved_mode: str, mode_payload: dict[str, object]) -> list[KeyPoint]:
    if resolved_mode == "guide":
        return [
            KeyPoint(id=f"step-{index}", title=f"Step {index}", details=str(item).strip())
            for index, item in enumerate(mode_payload.get("recommended_steps", []), start=1)
        ]
    if resolved_mode == "review":
        return [
            KeyPoint(id=f"highlight-{index}", title=f"Highlight {index}", details=str(item).strip())
            for index, item in enumerate(mode_payload.get("highlights", []), start=1)
        ]
    return [
        KeyPoint(
            id=str(item.get("id") or f"kp-{index}").strip(),
            title=str(item.get("title") or "").strip(),
            details=str(item.get("details") or "").strip(),
            evidence_segment_ids=[
                str(value).strip()
                for value in item.get("evidence_segment_ids", [])
                if str(value).strip()
            ],
        )
        for index, item in enumerate(mode_payload.get("evidence_backed_points", []), start=1)
    ]


def _build_legacy_analysis_items(resolved_mode: str, mode_payload: dict[str, object]) -> list[AnalysisItem]:
    if resolved_mode == "guide":
        tips = [
            AnalysisItem(id=f"tip-{index}", kind="tip", statement=str(item).strip())
            for index, item in enumerate(mode_payload.get("tips", []), start=1)
        ]
        pitfalls = [
            AnalysisItem(id=f"pitfall-{index}", kind="pitfall", statement=str(item).strip())
            for index, item in enumerate(mode_payload.get("pitfalls", []), start=1)
        ]
        return tips + pitfalls
    if resolved_mode == "review":
        items: list[AnalysisItem] = []
        standout = str(mode_payload.get("what_stands_out") or "").strip()
        if standout:
            items.append(AnalysisItem(id="review-standout", kind="highlight", statement=standout))
        items.extend(
            AnalysisItem(id=f"reservation-{index}", kind="reservation", statement=str(item).strip())
            for index, item in enumerate(mode_payload.get("reservation_points", []), start=1)
        )
        return items
    return [
        AnalysisItem(
            id=str(item.get("id") or f"analysis-{index}").strip(),
            kind=str(item.get("kind") or "implication").strip(),
            statement=str(item.get("statement") or "").strip(),
            evidence_segment_ids=[
                str(value).strip()
                for value in item.get("evidence_segment_ids", [])
                if str(value).strip()
            ],
        )
        for index, item in enumerate(mode_payload.get("interpretive_points", []), start=1)
    ]


def _build_legacy_verification_items(payload: dict[str, object]) -> list[VerificationItem]:
    return [
        VerificationItem(
            id=str(item.get("id") or "").strip(),
            claim=str(item.get("claim") or "").strip(),
            status=str(item.get("status") or "").strip(),
            evidence_segment_ids=[
                str(value).strip()
                for value in item.get("evidence_segment_ids", [])
                if str(value).strip()
            ],
            rationale=str(item.get("rationale")).strip() if item.get("rationale") is not None else None,
            confidence=_coerce_confidence(item.get("confidence")),
        )
        for item in payload.get("verification_items", [])
    ]


def _build_legacy_synthesis(
    resolved_mode: str,
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> SynthesisResult:
    what_is_new = str(mode_payload.get("what_is_new") or "").strip() or None
    tensions = [str(item).strip() for item in mode_payload.get("tensions", []) if str(item).strip()]
    next_steps: list[str] = []
    open_questions: list[str] = []
    if resolved_mode == "guide":
        next_steps = [str(item).strip() for item in mode_payload.get("prerequisites", []) if str(item).strip()]
    elif resolved_mode == "review":
        open_questions = [str(item).strip() for item in mode_payload.get("reservation_points", []) if str(item).strip()]
    else:
        open_questions = [str(item).strip() for item in mode_payload.get("uncertainties", []) if str(item).strip()]
    return SynthesisResult(
        final_answer=editorial_base.bottom_line,
        next_steps=next_steps,
        open_questions=open_questions,
        what_is_new=what_is_new,
        tensions=tensions,
    )


def _serialize_editorial_result(editorial: EditorialResult | None) -> dict[str, object] | None:
    if editorial is None:
        return None
    return {
        "requested_mode": editorial.requested_mode,
        "resolved_mode": editorial.resolved_mode,
        "mode_confidence": editorial.mode_confidence,
        "base": {
            "core_summary": editorial.base.core_summary,
            "bottom_line": editorial.base.bottom_line,
            "audience_fit": editorial.base.audience_fit,
            "save_worthy_points": editorial.base.save_worthy_points,
        },
        "mode_payload": editorial.mode_payload,
    }


def _validate_structured_result_evidence(
    result: StructuredResult,
    *,
    valid_evidence_segment_ids: set[str],
) -> list[WarningItem]:
    warnings: list[WarningItem] = []
    for item in result.key_points:
        item.evidence_segment_ids = _filter_valid_evidence_ids(
            item.evidence_segment_ids,
            valid_evidence_segment_ids=valid_evidence_segment_ids,
            warnings=warnings,
            label="key_point",
            item_id=item.id,
        )
    for item in result.analysis_items:
        item.evidence_segment_ids = _filter_valid_evidence_ids(
            item.evidence_segment_ids,
            valid_evidence_segment_ids=valid_evidence_segment_ids,
            warnings=warnings,
            label="analysis_item",
            item_id=item.id,
        )
    for item in result.verification_items:
        item.evidence_segment_ids = _filter_valid_evidence_ids(
            item.evidence_segment_ids,
            valid_evidence_segment_ids=valid_evidence_segment_ids,
            warnings=warnings,
            label="verification_item",
            item_id=item.id,
        )
        if item.status in {"supported", "partial"} and not item.evidence_segment_ids:
            item.status = "unclear"
            rationale = item.rationale or ""
            suffix = "Evidence references were invalid or missing."
            item.rationale = f"{rationale} {suffix}".strip()
            warnings.append(
                WarningItem(
                    code="verification_downgraded",
                    severity="warn",
                    message=f"verification item {item.id} downgraded to unclear because no valid evidence ids remained",
                    related_refs=[
                        RelatedRef(kind="verification_item", id=item.id, role="downgraded_item"),
                    ],
                )
            )
    result.warnings.extend(warnings)
    return warnings


def _filter_valid_evidence_ids(
    evidence_ids: list[str],
    *,
    valid_evidence_segment_ids: set[str],
    warnings: list[WarningItem],
    label: str,
    item_id: str,
) -> list[str]:
    filtered: list[str] = []
    seen: set[str] = set()
    for evidence_id in evidence_ids:
        normalized = evidence_id.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized not in valid_evidence_segment_ids:
            warnings.append(
                WarningItem(
                    code="invalid_evidence_reference",
                    severity="warn",
                    message=f"{label}:{item_id} referenced unknown evidence id: {normalized}",
                    related_refs=[
                        RelatedRef(kind=label, id=item_id, role="source_item"),
                        RelatedRef(kind="evidence_segment", id=normalized, role="missing_reference"),
                    ],
                )
            )
            continue
        filtered.append(normalized)
    return filtered
