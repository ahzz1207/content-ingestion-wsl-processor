from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_ingestion.core.config import Settings
from content_ingestion.core.models import ContentAsset

SUPPORTED_INPUT_MODALITIES = ("text", "image", "text_image")


@dataclass(slots=True)
class LlmContentPolicy:
    policy_id: str
    content_shape: str | None
    supported_input_modalities: list[str]
    default_task_intent: str
    text_analysis_input_modality: str = "text"
    multimodal_input_modality: str = "text_image"
    article_representation: str | None = None
    audio_representation: str | None = None
    video_representation: str | None = None
    table_representation: str | None = "image"

    def to_serializable_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "content_shape": self.content_shape,
            "supported_input_modalities": self.supported_input_modalities,
            "default_task_intent": self.default_task_intent,
            "text_analysis_input_modality": self.text_analysis_input_modality,
            "multimodal_input_modality": self.multimodal_input_modality,
            "article_representation": self.article_representation,
            "audio_representation": self.audio_representation,
            "video_representation": self.video_representation,
            "table_representation": self.table_representation,
        }


@dataclass(slots=True)
class LlmTaskSpec:
    task_id: str
    stage: str
    goal: str
    output_schema_name: str
    schema_mode: str = "json_schema"
    requires_multimodal: bool = False
    input_modality: str = "text"


@dataclass(slots=True)
class LlmRequestEnvelope:
    provider: str
    base_url: str | None
    model: str
    task: LlmTaskSpec
    content_shape: str | None
    content_policy: LlmContentPolicy
    source: dict[str, Any]
    task_intent: str | None
    document: dict[str, Any]
    image_paths: list[str] = field(default_factory=list)

    def to_serializable_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "task": {
                "task_id": self.task.task_id,
                "stage": self.task.stage,
                "goal": self.task.goal,
                "output_schema_name": self.task.output_schema_name,
                "schema_mode": self.task.schema_mode,
                "requires_multimodal": self.task.requires_multimodal,
                "input_modality": self.task.input_modality,
            },
            "content_shape": self.content_shape,
            "content_policy": self.content_policy.to_serializable_dict(),
            "source": self.source,
            "task_intent": self.task_intent,
            "document": self.document,
            "image_paths": self.image_paths,
        }

    def to_model_input(self):
        if self.task.input_modality == "text":
            return json.dumps(self.to_serializable_dict(), ensure_ascii=False, indent=2)
        text_context = json.dumps(self.to_serializable_dict(), ensure_ascii=False, indent=2)
        content: list[dict[str, Any]] = [{"type": "input_text", "text": text_context}]
        for image_path in self.image_paths:
            content.append({"type": "input_image", "image_url": _image_data_url(Path(image_path))})
        return [{"role": "user", "content": content}]


def build_text_analysis_envelope(
    *,
    asset: ContentAsset,
    job_dir: Path | None = None,
    settings: Settings,
    model: str,
    output_schema_name: str,
) -> LlmRequestEnvelope:
    content_policy = resolve_content_policy(asset)
    image_paths = _collect_llm_image_paths(asset, job_dir=job_dir)
    task = LlmTaskSpec(
        task_id="text_analysis_v1",
        stage="summarize_analyze_verify",
        goal="Produce source-grounded summary, key points, analysis items, verification items, and synthesis.",
        output_schema_name=output_schema_name,
        input_modality=content_policy.text_analysis_input_modality,
    )
    return LlmRequestEnvelope(
        provider=settings.llm_provider,
        base_url=settings.openai_base_url,
        model=model,
        task=task,
        content_shape=asset.content_shape,
        content_policy=content_policy,
        source=_build_source_payload(asset),
        task_intent=_task_intent(asset, content_policy),
        document={
            "title": asset.title,
            "author": asset.author,
            "published_at": asset.published_at.isoformat() if asset.published_at else None,
            "content_text": asset.content_text,
            "transcript_text": asset.transcript_text,
            "blocks": [
                {
                    "id": block.id,
                    "kind": block.kind,
                    "text": block.text,
                    "heading_level": block.heading_level,
                    "source": block.source,
                }
                for block in asset.blocks[:80]
            ],
            "attachments": [
                {
                    "id": attachment.id,
                    "kind": attachment.kind,
                    "role": attachment.role,
                    "media_type": attachment.media_type,
                    "path": attachment.path,
                    "description": attachment.description,
                }
                for attachment in asset.attachments[:40]
            ],
            "image_inputs": [_display_image_input_path(path) for path in image_paths],
            "allowed_evidence_ids": [segment.id for segment in asset.evidence_segments[: settings.llm_max_evidence_segments]],
            "evidence_segments": [
                {
                    "id": segment.id,
                    "kind": segment.kind,
                    "source": segment.source,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": segment.text,
                }
                for segment in asset.evidence_segments[: settings.llm_max_evidence_segments]
            ],
        },
        image_paths=image_paths,
    )


def build_multimodal_verification_envelope(
    *,
    asset: ContentAsset,
    settings: Settings,
    model: str,
    output_schema_name: str,
    frame_paths: list[Path],
) -> LlmRequestEnvelope:
    content_policy = resolve_content_policy(asset)
    task = LlmTaskSpec(
        task_id="multimodal_verification_v1",
        stage="multimodal_verify",
        goal="Validate transcript and analysis against extracted video frames and return visual findings.",
        output_schema_name=output_schema_name,
        requires_multimodal=True,
        input_modality=content_policy.multimodal_input_modality,
    )
    return LlmRequestEnvelope(
        provider=settings.llm_provider,
        base_url=settings.openai_base_url,
        model=model,
        task=task,
        content_shape=asset.content_shape,
        content_policy=content_policy,
        source=_build_source_payload(asset),
        task_intent=_task_intent(asset, content_policy),
        document={
            "title": asset.title,
            "summary": asset.summary,
            "transcript_text": asset.transcript_text,
            "analysis_text": asset.analysis_text,
            "frame_count": len(frame_paths),
            "image_inputs": [_display_image_input_path(path) for path in frame_paths],
        },
        image_paths=[str(path) for path in frame_paths],
    )


def resolve_content_policy(asset: ContentAsset) -> LlmContentPolicy:
    content_shape = asset.content_shape
    if content_shape == "audio":
        return LlmContentPolicy(
            policy_id="audio_text_only_v1",
            content_shape=content_shape,
            supported_input_modalities=["text", "text_image"],
            default_task_intent="summarize_and_verify_audio_transcript",
            text_analysis_input_modality="text_image",
            multimodal_input_modality="text_image",
            article_representation=None,
            audio_representation="whisper_transcript_text",
            video_representation=None,
            table_representation="image",
        )
    if content_shape == "video":
        return LlmContentPolicy(
            policy_id="video_text_first_v1",
            content_shape=content_shape,
            supported_input_modalities=["text", "text_image"],
            default_task_intent="summarize_video_from_subtitle_and_whisper_transcript",
            text_analysis_input_modality="text_image",
            multimodal_input_modality="text_image",
            article_representation=None,
            audio_representation="whisper_transcript_text",
            video_representation="subtitle_text_plus_whisper_transcript",
            table_representation="image",
        )
    return LlmContentPolicy(
        policy_id="article_text_first_v1",
        content_shape=content_shape,
        supported_input_modalities=["text", "image", "text_image"],
        default_task_intent="summarize_article_with_optional_image_grounding",
        text_analysis_input_modality="text_image",
        multimodal_input_modality="text_image",
        article_representation="body_text_blocks",
        audio_representation=None,
        video_representation=None,
        table_representation="image",
    )


def _task_intent(asset: ContentAsset, content_policy: LlmContentPolicy) -> str | None:
    value = asset.metadata.get("task_intent")
    if value in (None, ""):
        return content_policy.default_task_intent
    return str(value)


def _build_source_payload(asset: ContentAsset) -> dict[str, Any]:
    return {
        "platform": asset.source_platform,
        "source_url": asset.source_url,
        "canonical_url": asset.canonical_url,
        "title": asset.title,
        "author": asset.author,
    }


def _image_data_url(path: Path) -> str:
    import base64

    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/jpeg;base64,{encoded}"


def _display_image_input_path(path: str | Path) -> str:
    path = Path(path)
    parts = path.parts
    if "analysis" in parts:
        index = parts.index("analysis")
        return "/".join(parts[index:])
    return path.name


def _collect_llm_image_paths(asset: ContentAsset, *, job_dir: Path | None) -> list[str]:
    return [
        str((job_dir / Path(attachment.path)) if job_dir is not None else Path(attachment.path))
        for attachment in asset.attachments
        if attachment.kind == "image" and attachment.role != "analysis_frame"
    ]
