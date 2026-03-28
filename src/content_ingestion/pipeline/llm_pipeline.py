from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_ingestion.core.config import Settings
from content_ingestion.core.models import (
    VisualFinding,
    AnalysisItem,
    ContentAsset,
    KeyPoint,
    RelatedRef,
    ResultSummary,
    StructuredResult,
    SynthesisResult,
    VerificationItem,
    WarningItem,
)
from content_ingestion.pipeline.llm_contract import (
    build_multimodal_verification_envelope,
    build_text_analysis_envelope,
)


TEXT_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "headline": {"type": "string"},
                "short_text": {"type": "string"},
            },
            "required": ["headline", "short_text"],
        },
        "key_points": {
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
        "analysis_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string"},
                    "statement": {"type": "string"},
                    "evidence_segment_ids": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": ["number", "null"]},
                },
                "required": ["id", "kind", "statement", "evidence_segment_ids", "confidence"],
            },
        },
        "verification_items": {
            "type": "array",
            "items": {
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
            },
        },
        "content_kind": {"type": "string"},
        "author_stance": {"type": "string"},
        "synthesis": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "final_answer": {"type": "string"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["final_answer", "next_steps", "open_questions"],
        },
    },
    "required": ["content_kind", "author_stance", "summary", "key_points", "analysis_items", "verification_items", "synthesis"],
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
    request_artifacts: dict[str, str] = field(default_factory=dict)


def analyze_asset(*, job_dir: Path, asset: ContentAsset, settings: Settings) -> LlmAnalysisResult:
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
    text_request_path = analysis_dir / "text_request.json"
    text_request_path.write_text(
        json.dumps(text_envelope.to_serializable_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    result.request_artifacts["text"] = text_request_path.relative_to(job_dir).as_posix()
    text_payload = _call_structured_response(
        client=client,
        model=settings.analysis_model,
        instructions=_analysis_instructions(),
        input_payload=text_envelope.to_model_input(),
        schema_name="content_analysis",
        schema=TEXT_ANALYSIS_SCHEMA,
    )
    result.steps.append({"name": "llm_text_analysis", "status": "success", "details": settings.analysis_model})
    structured_result = _build_structured_result(text_payload)
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
            repaired_result = _build_structured_result(repaired_payload)
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


def _build_structured_result(payload: dict[str, object]) -> StructuredResult:
    summary_payload = payload["summary"]
    synthesis_payload = payload["synthesis"]
    content_kind = str(payload.get("content_kind") or "").strip() or None
    author_stance = str(payload.get("author_stance") or "").strip() or None
    return StructuredResult(
        content_kind=content_kind,
        author_stance=author_stance,
        summary=ResultSummary(
            headline=str(summary_payload["headline"]).strip(),
            short_text=str(summary_payload["short_text"]).strip(),
        ),
        key_points=[
            KeyPoint(
                id=str(item["id"]).strip(),
                title=str(item["title"]).strip(),
                details=str(item["details"]).strip(),
                evidence_segment_ids=[str(value).strip() for value in item["evidence_segment_ids"] if str(value).strip()],
            )
            for item in payload["key_points"]
        ],
        analysis_items=[
            AnalysisItem(
                id=str(item["id"]).strip(),
                kind=str(item["kind"]).strip(),
                statement=str(item["statement"]).strip(),
                evidence_segment_ids=[str(value).strip() for value in item["evidence_segment_ids"] if str(value).strip()],
                confidence=_coerce_confidence(item["confidence"]),
            )
            for item in payload["analysis_items"]
        ],
        verification_items=[
            VerificationItem(
                id=str(item["id"]).strip(),
                claim=str(item["claim"]).strip(),
                status=str(item["status"]).strip(),
                evidence_segment_ids=[str(value).strip() for value in item["evidence_segment_ids"] if str(value).strip()],
                rationale=str(item["rationale"]).strip() if item["rationale"] is not None else None,
                confidence=_coerce_confidence(item["confidence"]),
            )
            for item in payload["verification_items"]
        ],
        synthesis=SynthesisResult(
            final_answer=str(synthesis_payload["final_answer"]).strip(),
            next_steps=[str(item).strip() for item in synthesis_payload["next_steps"] if str(item).strip()],
            open_questions=[str(item).strip() for item in synthesis_payload["open_questions"] if str(item).strip()],
        ),
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
            "next_steps": result.synthesis.next_steps,
            "open_questions": result.synthesis.open_questions,
        },
        "warnings": [_serialize_warning_item(item) for item in result.warnings],
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
