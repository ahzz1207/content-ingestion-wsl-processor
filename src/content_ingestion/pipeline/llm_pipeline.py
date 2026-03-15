from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path

from content_ingestion.core.config import Settings
from content_ingestion.core.models import ContentAsset


TEXT_ANALYSIS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "analysis_items": {"type": "array", "items": {"type": "string"}},
        "verification_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "mixed", "uncertain"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["claim", "status", "evidence"],
            },
        },
        "synthesis": {"type": "string"},
    },
    "required": ["summary", "analysis_items", "verification_items", "synthesis"],
}

MULTIMODAL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "visual_findings": {"type": "array", "items": {"type": "string"}},
        "verification_adjustments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "claim": {"type": "string"},
                    "status": {"type": "string", "enum": ["supported", "mixed", "uncertain"]},
                    "rationale": {"type": "string"},
                },
                "required": ["claim", "status", "rationale"],
            },
        },
        "overall_assessment": {"type": "string"},
    },
    "required": ["visual_findings", "verification_adjustments", "overall_assessment"],
}


@dataclass(slots=True)
class LlmAnalysisResult:
    status: str
    summary: str | None = None
    analysis_items: list[str] = field(default_factory=list)
    verification_items: list[dict[str, object]] = field(default_factory=list)
    synthesis: str | None = None
    analysis_model: str | None = None
    multimodal_model: str | None = None
    steps: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    output_path: str | None = None


def analyze_asset(*, job_dir: Path, asset: ContentAsset, settings: Settings) -> LlmAnalysisResult:
    if not settings.openai_api_key:
        return LlmAnalysisResult(
            status="skipped",
            warnings=["OPENAI_API_KEY is not configured"],
            steps=[{"name": "resolve_openai_api_key", "status": "skipped", "details": "missing OPENAI_API_KEY"}],
        )
    if not openai_sdk_available():
        return LlmAnalysisResult(
            status="skipped",
            warnings=["openai SDK is not installed"],
            steps=[{"name": "load_openai_sdk", "status": "skipped", "details": "missing openai package"}],
        )

    client = _create_client(settings)
    analysis_dir = job_dir / "analysis" / "llm"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    result = LlmAnalysisResult(
        status="pass",
        analysis_model=settings.analysis_model,
        multimodal_model=settings.multimodal_model,
        steps=[
            {"name": "resolve_openai_api_key", "status": "success", "details": "api key available"},
            {"name": "load_openai_sdk", "status": "success", "details": "openai package available"},
        ],
    )

    text_payload = _call_structured_response(
        client=client,
        model=settings.analysis_model,
        instructions=_analysis_instructions(),
        input_payload=_build_text_input(asset, settings=settings),
        schema_name="content_analysis",
        schema=TEXT_ANALYSIS_SCHEMA,
    )
    result.steps.append({"name": "llm_text_analysis", "status": "success", "details": settings.analysis_model})
    result.summary = str(text_payload["summary"]).strip()
    result.analysis_items = [str(item).strip() for item in text_payload["analysis_items"] if str(item).strip()]
    result.verification_items = list(text_payload["verification_items"])
    result.synthesis = str(text_payload["synthesis"]).strip()

    frame_paths = _collect_frame_paths(job_dir, asset)
    if frame_paths:
        multimodal_payload = _call_structured_response(
            client=client,
            model=settings.multimodal_model,
            instructions=_multimodal_instructions(),
            input_payload=_build_multimodal_input(asset, frame_paths=frame_paths),
            schema_name="content_multimodal_verification",
            schema=MULTIMODAL_SCHEMA,
        )
        result.steps.append(
            {"name": "llm_multimodal_verification", "status": "success", "details": settings.multimodal_model}
        )
        result.analysis_items.extend(
            [str(item).strip() for item in multimodal_payload["visual_findings"] if str(item).strip()]
        )
        result.verification_items.extend(
            [
                {
                    "claim": item["claim"],
                    "status": item["status"],
                    "evidence": [item["rationale"]],
                }
                for item in multimodal_payload["verification_adjustments"]
            ]
        )
        if not result.synthesis:
            result.synthesis = str(multimodal_payload["overall_assessment"]).strip()

    output_path = analysis_dir / "analysis_result.json"
    output_path.write_text(
        json.dumps(
            {
                "status": result.status,
                "summary": result.summary,
                "analysis_items": result.analysis_items,
                "verification_items": result.verification_items,
                "synthesis": result.synthesis,
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


def _build_text_input(asset: ContentAsset, *, settings: Settings) -> str:
    evidence_lines: list[str] = []
    for segment in asset.evidence_segments[: settings.llm_max_evidence_segments]:
        evidence_lines.append(f"- [{segment.kind}] {segment.text}")
    blocks = "\n".join(f"- [{block.kind}] {block.text}" for block in asset.blocks[:20])
    parts = [
        f"Platform: {asset.source_platform}",
        f"Source URL: {asset.source_url}",
        f"Title: {asset.title}",
        f"Author: {asset.author or 'unknown'}",
        f"Published At: {asset.published_at.isoformat() if asset.published_at else 'unknown'}",
        "",
        "Captured content:",
        asset.content_text or "",
    ]
    if asset.transcript_text:
        parts.extend(["", "Transcript:", asset.transcript_text])
    if blocks:
        parts.extend(["", "Blocks:", blocks])
    if evidence_lines:
        parts.extend(["", "Evidence segments:", "\n".join(evidence_lines)])
    return "\n".join(parts).strip()


def _build_multimodal_input(asset: ContentAsset, *, frame_paths: list[Path]):
    content = [
        {
            "type": "input_text",
            "text": (
                "Review these extracted video frames together with the transcript context. "
                f"Title: {asset.title}\nSummary: {asset.summary or ''}\nTranscript: {asset.transcript_text or ''}"
            ),
        }
    ]
    for frame_path in frame_paths:
        content.append({"type": "input_image", "image_url": _image_data_url(frame_path)})
    return [{"role": "user", "content": content}]


def _collect_frame_paths(job_dir: Path, asset: ContentAsset) -> list[Path]:
    frame_paths: list[Path] = []
    for attachment in asset.attachments:
        if attachment.role != "analysis_frame":
            continue
        frame_path = job_dir.joinpath(*Path(attachment.path).parts)
        if frame_path.exists():
            frame_paths.append(frame_path)
    return frame_paths


def _image_data_url(path: Path) -> str:
    import base64

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _analysis_instructions() -> str:
    return (
        "You are analyzing captured web, audio, and video content. "
        "Return a concise structured summary, key analysis points, and verification checks. "
        "Only use claims grounded in the provided content and evidence segments."
    )


def _multimodal_instructions() -> str:
    return (
        "You are validating transcript-based analysis against extracted video frames. "
        "Return visual findings, verification adjustments, and an overall assessment. "
        "Do not invent claims that are not supported by the frames or transcript."
    )
