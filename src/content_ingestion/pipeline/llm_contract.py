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
    _selected_blocks, _blocks_truncated, _trimmed_block_count = _select_blocks_within_budget(
        asset.blocks, settings.llm_max_content_chars
    )
    _selected_evidence = _select_evidence_within_budget(
        asset.evidence_segments, settings.llm_max_evidence_segments
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
            "content_text": _truncate_text(asset.content_text, settings.llm_max_content_chars),
            "transcript_text": _truncate_text(asset.transcript_text, settings.llm_max_content_chars),
            "transcript_truncated": bool(asset.transcript_text and len(asset.transcript_text) > settings.llm_max_content_chars),
            "blocks": [
                {
                    "id": block.id,
                    "kind": block.kind,
                    "text": block.text,
                    "heading_level": block.heading_level,
                    "source": block.source,
                }
                for block in _selected_blocks
            ],
            "content_truncated": _blocks_truncated,
            "trimmed_block_count": _trimmed_block_count,
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
            "allowed_evidence_ids": [segment.id for segment in _selected_evidence],
            "evidence_segments": [
                {
                    "id": segment.id,
                    "kind": segment.kind,
                    "source": segment.source,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "text": segment.text,
                }
                for segment in _selected_evidence
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

def _truncate_text(text: str | None, max_chars: int) -> str | None:
    """Truncate plain text to max_chars with head/tail coverage.

    Keeps the first 60% and last 40% so opening and closing context both survive.
    A visible marker is inserted at the cut point.
    """
    if not text or len(text) <= max_chars:
        return text
    head = int(max_chars * 0.6)
    tail = max_chars - head
    return text[:head] + "\n...[content truncated]...\n" + text[-tail:]


def _select_blocks_within_budget(
    blocks: list,
    max_chars: int,
) -> tuple[list, bool, int]:
    """Select blocks within a strict char budget using type-aware priority.

    Budget allocation:
      - Headings: always kept first; count against budget.
        If headings alone exceed budget, return only headings.
      - High-priority (quote, list_item): up to 35% of post-heading budget,
        selected proportionally across document positions.
      - Normal paragraphs (len >= 20): remaining budget split head 40% / tail 40% / middle 20%.
    Total selected chars is guaranteed to stay at or below max_chars (modulo integer rounding).
    """
    if not blocks:
        return blocks, False, 0
    total_chars = sum(len(b.text) for b in blocks)
    if total_chars <= max_chars:
        return blocks, False, 0

    # Phase 1: headings — always kept, count against budget
    selected: set[int] = set()
    heading_chars = 0
    for i, b in enumerate(blocks):
        if b.kind == "heading":
            selected.add(i)
            heading_chars += len(b.text)

    if heading_chars >= max_chars:
        # Edge case: headings alone fill the budget
        result = [blocks[i] for i in sorted(selected)]
        return result, True, len(blocks) - len(result)

    remaining = max_chars - heading_chars

    # Phase 2: high-priority non-heading blocks (quote, list_item)
    # Capped at 35% of remaining budget; selected with uniform step for coverage
    hp_candidates = [(i, blocks[i]) for i in range(len(blocks))
                     if i not in selected and blocks[i].kind in ("quote", "list_item")]
    hp_budget = int(remaining * 0.35)
    hp_used = 0
    if hp_candidates and hp_budget > 0:
        total_hp_chars = sum(len(b.text) for _, b in hp_candidates)
        if total_hp_chars <= hp_budget:
            for i, _ in hp_candidates:
                selected.add(i)
            hp_used = total_hp_chars
        else:
            # Uniform step across positions for coverage
            avg_hp = max(1, total_hp_chars // len(hp_candidates))
            step = max(1, len(hp_candidates) // max(1, hp_budget // avg_hp))
            for idx in range(0, len(hp_candidates), step):
                i, b = hp_candidates[idx]
                if hp_used + len(b.text) <= hp_budget:
                    selected.add(i)
                    hp_used += len(b.text)

    # Phase 3: normal paragraphs — head 40% / tail 40% / middle 20%
    normal_budget = remaining - hp_used
    head_budget = int(normal_budget * 0.4)
    tail_budget = int(normal_budget * 0.4)
    middle_budget = normal_budget - head_budget - tail_budget

    filtered_normal = [
        (i, blocks[i]) for i in range(len(blocks))
        if i not in selected and blocks[i].kind not in ("heading", "quote", "list_item") and len(blocks[i].text) >= 20
    ]

    # Head
    acc = 0
    for i, b in filtered_normal:
        if acc + len(b.text) > head_budget:
            break
        selected.add(i)
        acc += len(b.text)

    # Tail
    acc = 0
    for i, b in reversed(filtered_normal):
        if i in selected:
            continue
        if acc + len(b.text) > tail_budget:
            continue
        selected.add(i)
        acc += len(b.text)
        if acc >= tail_budget:
            break

    # Middle uniform sampling — with strict budget guard per block
    middle_candidates = [(i, b) for i, b in filtered_normal if i not in selected]
    if middle_candidates and middle_budget > 0:
        avg_len = max(1, sum(len(b.text) for _, b in middle_candidates) // len(middle_candidates))
        step = max(1, len(middle_candidates) // max(1, middle_budget // avg_len))
        middle_used = 0
        for idx in range(0, len(middle_candidates), step):
            i_m, b_m = middle_candidates[idx]
            if middle_used + len(b_m.text) <= middle_budget:
                selected.add(i_m)
                middle_used += len(b_m.text)

    result_blocks = [blocks[i] for i in sorted(selected)]
    trimmed_count = len(blocks) - len(result_blocks)
    return result_blocks, True, trimmed_count


def _select_evidence_within_budget(
    segments: list,
    max_count: int,
) -> list:
    if len(segments) <= max_count:
        return segments
    head_count = max_count // 3
    tail_count = max_count // 3
    middle_count = max_count - head_count - tail_count
    head = list(segments[:head_count])
    tail_start = max(head_count, len(segments) - tail_count)
    tail = list(segments[tail_start:])
    middle_pool = segments[head_count:tail_start]
    if middle_pool and middle_count > 0:
        step = max(1, len(middle_pool) // middle_count)
        middle = [middle_pool[i] for i in range(0, len(middle_pool), step)][:middle_count]
    else:
        middle = []
    return head + middle + tail


def build_reader_envelope(
    *,
    asset: ContentAsset,
    job_dir: Path | None = None,
    settings: Settings,
    model: str,
) -> LlmRequestEnvelope:
    content_policy = resolve_content_policy(asset)
    selected_blocks, blocks_truncated, trimmed_block_count = _select_blocks_within_budget(
        asset.blocks, settings.llm_max_content_chars
    )
    task = LlmTaskSpec(
        task_id="reader_pass_v1",
        stage="structure_recognition",
        goal="Identify document structure: chapter map, argument skeleton, content signals.",
        output_schema_name="reader_analysis",
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
        task_intent="structure_recognition",
        document={
            "title": asset.title,
            "content_text": _truncate_text(asset.content_text, settings.llm_max_content_chars),
            "transcript_text": _truncate_text(asset.transcript_text, settings.llm_max_content_chars),
            "transcript_truncated": bool(asset.transcript_text and len(asset.transcript_text) > settings.llm_max_content_chars),
            "blocks": [
                {
                    "id": b.id,
                    "kind": b.kind,
                    "text": b.text,
                    "heading_level": b.heading_level,
                }
                for b in selected_blocks
            ],
            "content_truncated": blocks_truncated,
            "selected_block_count": len(selected_blocks),
            "trimmed_block_count": trimmed_block_count,
        },
        image_paths=[],
    )


def build_synthesizer_envelope(
    *,
    asset: ContentAsset,
    reader_output: dict[str, Any],
    job_dir: Path | None = None,
    settings: Settings,
    model: str,
    output_schema_name: str,
) -> LlmRequestEnvelope:
    content_policy = resolve_content_policy(asset)
    image_paths = _collect_llm_image_paths(asset, job_dir=job_dir)
    selected_blocks, blocks_truncated, trimmed_block_count = _select_blocks_within_budget(
        asset.blocks, settings.llm_max_content_chars
    )
    selected_evidence = _select_evidence_within_budget(
        asset.evidence_segments, settings.llm_max_evidence_segments
    )
    task = LlmTaskSpec(
        task_id="synthesizer_pass_v1",
        stage="deep_analysis",
        goal="Based on reader structure, produce deep analysis, key points, verification, synthesis.",
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
            "content_text": _truncate_text(asset.content_text, settings.llm_max_content_chars),
            "transcript_text": _truncate_text(asset.transcript_text, settings.llm_max_content_chars),
            "transcript_truncated": bool(asset.transcript_text and len(asset.transcript_text) > settings.llm_max_content_chars),
            "blocks": [
                {
                    "id": b.id,
                    "kind": b.kind,
                    "text": b.text,
                    "heading_level": b.heading_level,
                    "source": b.source,
                }
                for b in selected_blocks
            ],
            "content_truncated": blocks_truncated,
            "selected_block_count": len(selected_blocks),
            "trimmed_block_count": trimmed_block_count,
            "selected_evidence_count": len(selected_evidence),
            "total_evidence_count": len(asset.evidence_segments),
            "attachments": [
                {
                    "id": a.id,
                    "kind": a.kind,
                    "role": a.role,
                    "media_type": a.media_type,
                    "path": a.path,
                    "description": a.description,
                }
                for a in asset.attachments[:40]
            ],
            "image_inputs": [_display_image_input_path(p) for p in image_paths],
            "allowed_evidence_ids": [s.id for s in selected_evidence],
            "evidence_segments": [
                {
                    "id": s.id,
                    "kind": s.kind,
                    "source": s.source,
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "text": s.text,
                }
                for s in selected_evidence
            ],
            "reader_output": reader_output,
        },
        image_paths=image_paths,
    )

