from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_ingestion.core.config import Settings
from content_ingestion.core.models import (
    AnalysisItem,
    ChapterEntry,
    ContentAsset,
    EditorialBase,
    EditorialResult,
    KeyPoint,
    ProductSection,
    ProductView,
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
        "suggested_reading_goal": {"type": "string", "enum": ["argument", "guide", "review", "narrative"]},
        "goal_confidence": {"type": "number"},
        "suggested_domain_template": {
            "type": "string",
            "enum": ["politics_public_issue", "macro_business", "game_guide", "personal_narrative", "generic"],
        },
        "domain_confidence": {"type": "number"},
    },
    "required": [
        "document_type",
        "thesis",
        "chapter_map",
        "argument_skeleton",
        "content_signals",
        "suggested_reading_goal",
        "goal_confidence",
        "suggested_domain_template",
        "domain_confidence",
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
    requested_reading_goal: str | None = None
    resolved_reading_goal: str | None = None
    goal_confidence: float | None = None
    requested_domain_template: str | None = None
    resolved_domain_template: str | None = None
    domain_confidence: float | None = None
    route_key: str | None = None
    request_artifacts: dict[str, str] = field(default_factory=dict)


_VALID_V1_MODES = {"argument", "guide", "review"}
_VALID_READING_GOALS = {"argument", "guide", "review", "narrative"}
_VALID_DOMAIN_TEMPLATES = {"politics_public_issue", "macro_business", "game_guide", "personal_narrative", "generic"}
_DOMAIN_CONFIDENCE_THRESHOLD = 0.5
_SUPPORTED_ROUTE_TEMPLATES = {
    "argument": {"politics_public_issue", "macro_business", "generic"},
    "guide": {"game_guide", "generic"},
    "review": {"generic"},
    "narrative": {"personal_narrative", "generic"},
}
_MODE_SCHEMA = {
    "argument": ARGUMENT_ANALYSIS_SCHEMA,
    "guide": GUIDE_ANALYSIS_SCHEMA,
    "review": REVIEW_ANALYSIS_SCHEMA,
}
_PRODUCT_VIEW_LAYOUTS = {
    "argument.politics_public_issue": "analysis_brief",
    "argument.macro_business": "analysis_brief",
    "guide.game_guide": "practical_guide",
    "narrative.personal_narrative": "narrative_digest",
    "review.generic": "review_curation",
}


@dataclass(slots=True)
class RoutingDecision:
    reading_goal: str
    domain_template: str
    route_key: str
    goal_confidence: float
    domain_confidence: float
    requested_reading_goal: str | None
    requested_domain_template: str | None


def analyze_asset(
    *,
    job_dir: Path,
    asset: ContentAsset,
    settings: Settings,
    requested_mode: str = "auto",
    requested_reading_goal: str | None = None,
    requested_domain_template: str | None = None,
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
    routing = _resolve_routing(
        requested_reading_goal=requested_reading_goal,
        requested_domain_template=requested_domain_template,
        requested_mode=requested_mode,
        reader_payload=reader_payload,
    )
    resolved_mode = _reading_goal_to_mode(routing.reading_goal)
    mode_confidence = routing.goal_confidence
    result.requested_mode = requested_mode
    result.resolved_mode = resolved_mode
    result.mode_confidence = mode_confidence
    result.requested_reading_goal = routing.requested_reading_goal
    result.resolved_reading_goal = routing.reading_goal
    result.goal_confidence = routing.goal_confidence
    result.requested_domain_template = routing.requested_domain_template
    result.resolved_domain_template = routing.domain_template
    result.domain_confidence = routing.domain_confidence
    result.route_key = routing.route_key
    result.steps.append(
        {
            "name": "mode_routing",
            "status": "success",
            "details": f"{routing.requested_reading_goal} -> {routing.route_key} ({routing.goal_confidence:.2f}/{routing.domain_confidence:.2f})",
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
        instructions=_synthesizer_instructions_for_mode(resolved_mode, routing.route_key),
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
        routing=routing,
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
                routing=routing,
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
                "requested_reading_goal": result.requested_reading_goal,
                "resolved_reading_goal": result.resolved_reading_goal,
                "goal_confidence": result.goal_confidence,
                "requested_domain_template": result.requested_domain_template,
                "resolved_domain_template": result.resolved_domain_template,
                "domain_confidence": result.domain_confidence,
                "route_key": result.route_key,
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


def _resolve_routing(
    requested_reading_goal: str | None = None,
    requested_domain_template: str | None = None,
    reader_payload: dict[str, object] | None = None,
    requested_mode: str | None = None,
) -> RoutingDecision:
    payload = reader_payload or {}
    explicit_requested_goal = str(requested_reading_goal or "").strip() or None
    if explicit_requested_goal in _VALID_READING_GOALS:
        reading_goal = explicit_requested_goal
        goal_confidence = 1.0
    elif requested_mode in _VALID_V1_MODES:
        reading_goal = requested_mode
        goal_confidence = 1.0
    else:
        suggested_goal = str(
            payload.get("suggested_reading_goal") or payload.get("suggested_mode") or ""
        ).strip()
        if suggested_goal in _VALID_READING_GOALS:
            reading_goal = suggested_goal
            goal_confidence = _coerce_confidence(payload.get("goal_confidence"))
            if goal_confidence is None:
                goal_confidence = _coerce_confidence(payload.get("mode_confidence"))
            if goal_confidence is None:
                goal_confidence = 0.5
        else:
            reading_goal = "argument"
            goal_confidence = 0.5

    if requested_domain_template is not None:
        candidate_domain = str(requested_domain_template).strip() or "generic"
        domain_confidence = 1.0
    else:
        suggested_domain = str(payload.get("suggested_domain_template") or "").strip()
        candidate_domain = suggested_domain if suggested_domain in _VALID_DOMAIN_TEMPLATES else "generic"
        domain_confidence = _coerce_confidence(payload.get("domain_confidence"))
        if domain_confidence is None:
            domain_confidence = 0.0
        if domain_confidence < _DOMAIN_CONFIDENCE_THRESHOLD:
            candidate_domain = "generic"

    if candidate_domain not in _VALID_DOMAIN_TEMPLATES:
        candidate_domain = "generic"

    supported_templates = _SUPPORTED_ROUTE_TEMPLATES.get(reading_goal, {"generic"})
    domain_template = candidate_domain if candidate_domain in supported_templates else "generic"
    return RoutingDecision(
        reading_goal=reading_goal,
        domain_template=domain_template,
        route_key=f"{reading_goal}.{domain_template}",
        goal_confidence=goal_confidence,
        domain_confidence=domain_confidence,
        requested_reading_goal=explicit_requested_goal,
        requested_domain_template=requested_domain_template,
    )


def _reading_goal_to_mode(reading_goal: str) -> str:
    if reading_goal in _VALID_V1_MODES:
        return reading_goal
    return "argument"


def _reader_instructions() -> str:
    return """You are a structural analyst. Your only job is to identify the shape of the content and suggest the best routing.

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
6. ROUTING SUGGESTION - Choose the best reading goal and domain template:
   - suggested_reading_goal: argument / guide / review / narrative
   - suggested_domain_template: politics_public_issue / macro_business / game_guide / personal_narrative / generic
   - goal_confidence: confidence in the reading goal, between 0.0 and 1.0
   - domain_confidence: confidence in the domain template, between 0.0 and 1.0
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
- Keep interpretive points separate from evidence-backed points."""


def _synthesizer_instructions_politics_public_issue() -> str:
    return """You are a critical analyst producing an argument-focused result for a public issue or politics piece.
Use the Reader output to organize the synthesis around the author's case, the public stakes, and the missing tradeoffs.

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
- evidence_backed_points should surface the strongest policy claims, evidence, and institutional constraints.
- interpretive_points should focus on downstream implications, counter-pressures, or unaddressed alternatives.
- verification_items should prioritize claims about outcomes, costs, timing, and scope.
- tensions should emphasize tradeoffs, internal contradictions, or evidence-to-conclusion gaps.
- Use only evidence_segment_ids from the evidence_segments list.
- Do not invent evidence ids."""


def _synthesizer_instructions_macro_business() -> str:
    return """You are a critical analyst producing an argument-focused result for a macro business or macroeconomic piece.
Use the Reader output to organize the synthesis around the cycle, causal logic, and the indicators that matter most.

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
- evidence_backed_points should center on indicators, causal claims, and timing arguments.
- interpretive_points should focus on second-order implications, alternative cycle readings, or market consequences.
- verification_items should prioritize claims about macro direction, timing, policy response, and business impact.
- tensions should capture where indicators, confidence, or conclusions do not line up cleanly.
- uncertainties should call out what would change the macro read.
- Use only evidence_segment_ids from the evidence_segments list.
- Do not invent evidence ids."""


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
- quick_win"""


def _synthesizer_instructions_game_guide() -> str:
    return """You are an editor producing a practical game-guide result.
Focus on what helps a player act: route order, build choices, prerequisites, quick wins, and avoidable mistakes.

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

Rules:
- recommended_steps should be concrete actions a player can follow in sequence.
- tips should highlight efficiency, survivability, shortcuts, or build advantages.
- pitfalls should warn about dead ends, wasted resources, or common player mistakes.
- prerequisites should note unlocks, gear, level gates, or setup the player needs first.
- quick_win should give the fastest meaningful payoff for a player starting now."""


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
- reservation_points"""


def _synthesizer_instructions_narrative() -> str:
    return """You are an editor producing a narrative-focused result.
Focus on story shape, emotional movement, and reflective meaning while keeping the same argument-mode schema.

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
- Treat evidence_backed_points as story beats or scene anchors.
- Treat interpretive_points as themes, implied meaning, or reflective readings.
- Use verification_items sparingly; narrative writing may have none.
- Use only evidence_segment_ids from the evidence_segments list."""


def _synthesizer_instructions_for_mode(resolved_mode: str, route_key: str | None = None) -> str:
    if route_key == "argument.politics_public_issue":
        return _synthesizer_instructions_politics_public_issue()
    if route_key == "argument.macro_business":
        return _synthesizer_instructions_macro_business()
    if route_key == "guide.game_guide":
        return _synthesizer_instructions_game_guide()
    if route_key == "narrative.personal_narrative":
        return _synthesizer_instructions_narrative()
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
    routing: RoutingDecision,
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
    product_view = _build_product_view(
        routing=routing,
        resolved_mode=resolved_mode,
        editorial_base=editorial_base,
        mode_payload=mode_payload,
    )
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
            requested_reading_goal=routing.requested_reading_goal,
            resolved_reading_goal=routing.reading_goal,
            goal_confidence=routing.goal_confidence,
            requested_domain_template=routing.requested_domain_template,
            resolved_domain_template=routing.domain_template,
            domain_confidence=routing.domain_confidence,
            route_key=routing.route_key,
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
        "product_view": _serialize_product_view(result.product_view),
    }


def _serialize_product_view(product_view: ProductView | None) -> dict[str, object] | None:
    if product_view is None:
        return None
    return {
        "layout": product_view.layout,
        "template": product_view.template,
        "title": product_view.title,
        "dek": product_view.dek,
        "sections": [
            {
                "kind": section.kind,
                "title": section.title,
                "body": section.body,
                "items": section.items,
            }
            for section in product_view.sections
        ],
    }


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


def _build_product_view(
    *,
    routing: RoutingDecision,
    resolved_mode: str,
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> ProductView:
    route_key = routing.route_key
    if route_key == "argument.politics_public_issue":
        return _build_analysis_brief_product_view(
            template=route_key,
            title=str(mode_payload.get("author_thesis") or editorial_base.core_summary).strip() or editorial_base.core_summary,
            dek=editorial_base.bottom_line,
            summary_title="Public issue overview",
            mode_payload=mode_payload,
            include_verification=True,
            final_section_kind="tensions",
            final_section_title="Core tensions",
            final_section_items=[str(item).strip() for item in mode_payload.get("tensions", []) if str(item).strip()],
        )
    if route_key == "argument.macro_business":
        return _build_analysis_brief_product_view(
            template=route_key,
            title=str(mode_payload.get("author_thesis") or editorial_base.core_summary).strip() or editorial_base.core_summary,
            dek=editorial_base.bottom_line,
            summary_title="Macro setup",
            mode_payload=mode_payload,
            include_verification=False,
            final_section_kind="uncertainties",
            final_section_title="Open uncertainties",
            final_section_items=[str(item).strip() for item in mode_payload.get("uncertainties", []) if str(item).strip()],
        )
    if route_key == "guide.game_guide":
        return _build_game_guide_product_view(editorial_base=editorial_base, mode_payload=mode_payload)
    if route_key == "narrative.personal_narrative":
        return _build_personal_narrative_product_view(editorial_base=editorial_base, mode_payload=mode_payload)
    if route_key == "review.generic":
        return _build_review_product_view(template=route_key, editorial_base=editorial_base, mode_payload=mode_payload)
    return _build_generic_product_view(
        route_key=route_key,
        resolved_mode=resolved_mode,
        editorial_base=editorial_base,
        mode_payload=mode_payload,
    )


def _build_analysis_brief_product_view(
    *,
    template: str,
    title: str,
    dek: str,
    summary_title: str,
    mode_payload: dict[str, object],
    include_verification: bool,
    final_section_kind: str,
    final_section_title: str,
    final_section_items: list[str],
) -> ProductView:
    sections = [
        ProductSection(
            kind="summary",
            title=summary_title,
            body=str(mode_payload.get("what_is_new") or "").strip() or dek,
        ),
        ProductSection(
            kind="key_points",
            title="Key points",
            items=[
                {
                    "id": str(item.get("id") or "").strip(),
                    "title": str(item.get("title") or "").strip(),
                    "body": str(item.get("details") or "").strip(),
                    "evidence_segment_ids": [
                        str(value).strip() for value in item.get("evidence_segment_ids", []) if str(value).strip()
                    ],
                }
                for item in mode_payload.get("evidence_backed_points", [])
            ],
        ),
    ]
    if include_verification:
        sections.append(
            ProductSection(
                kind="verification",
                title="Verification",
                items=[
                    {
                        "id": str(item.get("id") or "").strip(),
                        "claim": str(item.get("claim") or "").strip(),
                        "status": str(item.get("status") or "").strip(),
                        "rationale": str(item.get("rationale") or "").strip(),
                    }
                    for item in mode_payload.get("verification_items", [])
                ],
            )
        )
    else:
        sections.append(
            ProductSection(
                kind="implications",
                title="Implications",
                items=[
                    {
                        "id": str(item.get("id") or "").strip(),
                        "kind": str(item.get("kind") or "").strip(),
                        "statement": str(item.get("statement") or "").strip(),
                    }
                    for item in mode_payload.get("interpretive_points", [])
                ],
            )
        )
    sections.append(
        ProductSection(
            kind=final_section_kind,
            title=final_section_title,
            items=[{"text": item} for item in final_section_items],
        )
    )
    return ProductView(
        layout=_PRODUCT_VIEW_LAYOUTS[template],
        template=template,
        title=title,
        dek=dek,
        sections=sections,
    )


def _build_game_guide_product_view(*, editorial_base: EditorialBase, mode_payload: dict[str, object]) -> ProductView:
    template = "guide.game_guide"
    return ProductView(
        layout=_PRODUCT_VIEW_LAYOUTS[template],
        template=template,
        title=str(mode_payload.get("guide_goal") or editorial_base.core_summary).strip() or editorial_base.core_summary,
        dek=editorial_base.bottom_line,
        sections=[
            ProductSection(
                kind="quick_win",
                title="Quick win",
                body=str(mode_payload.get("quick_win") or editorial_base.bottom_line).strip() or editorial_base.bottom_line,
            ),
            ProductSection(
                kind="steps",
                title="Recommended steps",
                items=[{"text": str(item).strip()} for item in mode_payload.get("recommended_steps", []) if str(item).strip()],
            ),
            ProductSection(
                kind="tips",
                title="Tips",
                items=[{"text": str(item).strip()} for item in mode_payload.get("tips", []) if str(item).strip()],
            ),
            ProductSection(
                kind="pitfalls",
                title="Pitfalls",
                items=[{"text": str(item).strip()} for item in mode_payload.get("pitfalls", []) if str(item).strip()],
            ),
        ],
    )


def _build_personal_narrative_product_view(*, editorial_base: EditorialBase, mode_payload: dict[str, object]) -> ProductView:
    template = "narrative.personal_narrative"
    return ProductView(
        layout=_PRODUCT_VIEW_LAYOUTS[template],
        template=template,
        title=str(mode_payload.get("author_thesis") or editorial_base.core_summary).strip() or editorial_base.core_summary,
        dek=editorial_base.bottom_line,
        sections=[
            ProductSection(kind="summary", title="Summary", body=editorial_base.core_summary),
            ProductSection(
                kind="story_beats",
                title="Story beats",
                items=[
                    {
                        "id": str(item.get("id") or "").strip(),
                        "title": str(item.get("title") or "").strip(),
                        "body": str(item.get("details") or "").strip(),
                    }
                    for item in mode_payload.get("evidence_backed_points", [])
                ],
            ),
            ProductSection(
                kind="themes",
                title="Themes",
                items=[
                    {"id": str(item.get("id") or "").strip(), "statement": str(item.get("statement") or "").strip()}
                    for item in mode_payload.get("interpretive_points", [])
                ],
            ),
            ProductSection(kind="takeaway", title="Takeaway", body=editorial_base.bottom_line),
        ],
    )


def _build_review_product_view(
    *,
    template: str,
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> ProductView:
    return ProductView(
        layout=_PRODUCT_VIEW_LAYOUTS[template],
        template=template,
        title=str(mode_payload.get("overall_judgment") or editorial_base.core_summary).strip() or editorial_base.core_summary,
        dek=editorial_base.bottom_line,
        sections=[
            ProductSection(kind="summary", title="Summary", body=editorial_base.core_summary),
            ProductSection(
                kind="highlights",
                title="Highlights",
                items=[{"text": str(item).strip()} for item in mode_payload.get("highlights", []) if str(item).strip()],
            ),
            ProductSection(kind="audience", title="Who it's for", body=str(mode_payload.get("who_it_is_for") or editorial_base.audience_fit).strip()),
            ProductSection(
                kind="reservations",
                title="Reservations",
                items=[{"text": str(item).strip()} for item in mode_payload.get("reservation_points", []) if str(item).strip()],
            ),
        ],
    )


def _build_generic_product_view(
    *,
    route_key: str,
    resolved_mode: str,
    editorial_base: EditorialBase,
    mode_payload: dict[str, object],
) -> ProductView:
    if resolved_mode == "guide":
        template = route_key if route_key in _PRODUCT_VIEW_LAYOUTS else "guide.generic"
        takeaway_items = [
            {"text": str(item).strip()}
            for item in mode_payload.get("recommended_steps", [])
            if str(item).strip()
        ][:5]
        remember_this = str(mode_payload.get("quick_win") or editorial_base.bottom_line).strip() or editorial_base.bottom_line
        return ProductView(
            layout="practical_guide",
            template=template,
            title=str(mode_payload.get("guide_goal") or editorial_base.core_summary).strip() or editorial_base.core_summary,
            dek=editorial_base.bottom_line,
            sections=[
                ProductSection(kind="one_line_summary", title="一句话总结", body=editorial_base.core_summary),
                ProductSection(
                    kind="core_takeaways",
                    title="核心要点",
                    items=takeaway_items,
                ),
                ProductSection(kind="remember_this", title="记住这件事", body=remember_this),
            ],
        )
    if resolved_mode == "review":
        template = route_key if route_key in _PRODUCT_VIEW_LAYOUTS else "review.generic"
        return _build_review_product_view(template=template, editorial_base=editorial_base, mode_payload=mode_payload)
    template = route_key
    argument_items = [
        {
            "id": str(item.get("id") or "").strip(),
            "title": str(item.get("title") or "").strip(),
            "body": str(item.get("details") or "").strip(),
        }
        for item in mode_payload.get("evidence_backed_points", [])
    ]
    evidence_items = [
        {
            "id": str(item.get("id") or "").strip(),
            "text": str(item.get("details") or item.get("title") or "").strip(),
            "evidence_segment_ids": [
                str(value).strip() for value in item.get("evidence_segment_ids", []) if str(value).strip()
            ],
        }
        for item in mode_payload.get("evidence_backed_points", [])
    ]
    tension_items = [
        {"text": str(item).strip()}
        for item in mode_payload.get("tensions", [])
        if str(item).strip()
    ]
    verification_items = [
        {
            "id": str(item.get("id") or "").strip(),
            "claim": str(item.get("claim") or "").strip(),
            "status": str(item.get("status") or "").strip(),
            "rationale": str(item.get("rationale") or "").strip(),
        }
        for item in mode_payload.get("verification_items", [])
    ]
    return ProductView(
        layout="analysis_brief",
        template=template,
        title=str(mode_payload.get("author_thesis") or editorial_base.core_summary).strip() or editorial_base.core_summary,
        dek=editorial_base.bottom_line,
        sections=[
            ProductSection(
                kind="core_judgment",
                title="核心判断",
                body=str(mode_payload.get("what_is_new") or editorial_base.core_summary).strip() or editorial_base.core_summary,
            ),
            ProductSection(
                kind="main_arguments",
                title="主要论点",
                items=argument_items,
            ),
            ProductSection(kind="evidence", title="关键论据", items=evidence_items),
            ProductSection(kind="tensions", title="张力与漏洞", items=tension_items),
            ProductSection(kind="verification", title="验证与保留意见", items=verification_items),
        ],
    )


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
        "requested_reading_goal": editorial.requested_reading_goal,
        "resolved_reading_goal": editorial.resolved_reading_goal,
        "goal_confidence": editorial.goal_confidence,
        "requested_domain_template": editorial.requested_domain_template,
        "resolved_domain_template": editorial.resolved_domain_template,
        "domain_confidence": editorial.domain_confidence,
        "route_key": editorial.route_key,
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
    _sync_editorial_and_product_view_evidence(result)
    return warnings


def _sync_editorial_and_product_view_evidence(result: StructuredResult) -> None:
    if result.editorial is not None:
        mode_payload = result.editorial.mode_payload
        _sync_payload_items(
            payload_items=mode_payload.get("evidence_backed_points", []),
            result_items=result.key_points,
            apply=lambda payload_item, result_item: payload_item.__setitem__(
                "evidence_segment_ids", list(result_item.evidence_segment_ids)
            ),
        )
        _sync_payload_items(
            payload_items=mode_payload.get("interpretive_points", []),
            result_items=result.analysis_items,
            apply=lambda payload_item, result_item: payload_item.__setitem__(
                "evidence_segment_ids", list(result_item.evidence_segment_ids)
            ),
        )
        _sync_payload_items(
            payload_items=mode_payload.get("verification_items", []),
            result_items=result.verification_items,
            apply=lambda payload_item, result_item: payload_item.update(
                {
                    "evidence_segment_ids": list(result_item.evidence_segment_ids),
                    "status": result_item.status,
                    "rationale": result_item.rationale,
                }
            ),
        )

    if result.product_view is None:
        return
    for section in result.product_view.sections:
        if section.kind != "key_points":
            continue
        _sync_payload_items(
            payload_items=section.items,
            result_items=result.key_points,
            apply=lambda payload_item, result_item: payload_item.__setitem__(
                "evidence_segment_ids", list(result_item.evidence_segment_ids)
            ),
        )


def _sync_payload_items(payload_items: list[dict[str, object]], result_items: list[object], apply) -> None:
    payload_id_counts = _count_nonempty_ids(payload_items)
    result_id_counts = _count_nonempty_ids(result_items)
    result_items_by_id = {
        item.id: item
        for item in result_items
        if getattr(item, "id", "") and result_id_counts.get(item.id, 0) == 1
    }

    for index, payload_item in enumerate(payload_items):
        payload_id = str(payload_item.get("id") or "").strip()
        matched_item = None
        if payload_id and payload_id_counts.get(payload_id, 0) == 1:
            matched_item = result_items_by_id.get(payload_id)
        if matched_item is None and index < len(result_items):
            matched_item = result_items[index]
        if matched_item is not None:
            apply(payload_item, matched_item)


def _count_nonempty_ids(items: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        item_id = item.get("id") if isinstance(item, dict) else getattr(item, "id", "")
        normalized = str(item_id or "").strip()
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


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
