from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from content_ingestion.core.evidence import build_evidence_segment_id
from content_ingestion.core.models import ContentAttachment, ContentBlock, EvidenceSegment
from content_ingestion.normalize.cleaning import clean_text


def build_blocks_from_records(
    records: list[dict[str, Any]],
    *,
    title: str | None = None,
) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    if title:
        blocks.append(
            ContentBlock(
                id="heading-1",
                kind="heading",
                text=title,
                heading_level=1,
                source="title",
            )
        )
    for index, record in enumerate(records, start=1):
        kind = _optional_str(record.get("kind")) or "paragraph"
        text = clean_text(str(record.get("text") or ""))
        if not text:
            continue
        heading_level = _optional_int(record.get("heading_level"))
        block_id = f"{kind}-{index}"
        blocks.append(
            ContentBlock(
                id=block_id,
                kind=kind,
                text=text,
                heading_level=heading_level,
                source=_optional_str(record.get("source")) or "html",
            )
        )
    return blocks


def build_text_blocks(text: str, *, title: str | None = None) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    if title:
        blocks.append(
            ContentBlock(
                id="heading-1",
                kind="heading",
                text=title,
                heading_level=1,
                source="title",
            )
        )
    for index, part in enumerate(_split_paragraphs(text), start=1):
        blocks.append(
            ContentBlock(
                id=f"paragraph-{index}",
                kind="paragraph",
                text=part,
                source="content_text",
            )
        )
    return blocks


def build_attachment_inventory(job_dir: Path, capture_manifest: dict[str, Any] | None) -> list[ContentAttachment]:
    if not capture_manifest:
        return []
    attachments: list[ContentAttachment] = []
    for index, artifact in enumerate(capture_manifest.get("artifacts", []), start=1):
        if not isinstance(artifact, dict):
            continue
        if artifact.get("is_primary"):
            continue
        relative_path = artifact.get("path")
        role = artifact.get("role")
        media_type = artifact.get("media_type")
        if not isinstance(relative_path, str) or not isinstance(role, str) or not isinstance(media_type, str):
            continue
        normalized = PurePosixPath(relative_path)
        resolved_path = job_dir.joinpath(*normalized.parts)
        attachments.append(
            ContentAttachment(
                id=f"attachment-{index}",
                path=relative_path,
                role=role,
                media_type=media_type,
                kind=_classify_attachment_kind(role=role, media_type=media_type, path=relative_path),
                size_bytes=_optional_int(artifact.get("size_bytes")),
                description=_optional_str(artifact.get("description")),
            )
        )
    return attachments


def build_evidence_segments(
    *,
    job_dir: Path,
    blocks: list[ContentBlock],
    attachments: list[ContentAttachment],
) -> list[EvidenceSegment]:
    segments: list[EvidenceSegment] = []
    for block_index, block in enumerate(blocks, start=1):
        if block.kind not in {"paragraph", "list_item", "image_caption", "table_row"} or not block.text.strip():
            continue
        evidence_kind = "text_block" if block.kind in {"paragraph", "list_item"} else block.kind
        segments.append(
            EvidenceSegment(
                id=build_evidence_segment_id(
                    kind=evidence_kind,
                    source=block.id,
                    text=block.text,
                    sequence=block_index,
                ),
                kind=evidence_kind,
                text=block.text,
                source=block.id,
            )
        )

    for attachment in attachments:
        if attachment.kind not in {"subtitle", "transcript", "danmaku"}:
            continue
        attachment_path = job_dir.joinpath(*PurePosixPath(attachment.path).parts)
        for item_index, item in enumerate(_read_transcript_segments(attachment_path), start=1):
            segments.append(
                EvidenceSegment(
                    id=build_evidence_segment_id(
                        kind=attachment.kind,
                        source=attachment.path,
                        text=str(item["text"]),
                        sequence=item_index,
                        start_ms=_optional_int(item.get("start_ms")),
                        end_ms=_optional_int(item.get("end_ms")),
                    ),
                    kind=attachment.kind,
                    text=item["text"],
                    source=attachment.path,
                    start_ms=item.get("start_ms"),
                    end_ms=item.get("end_ms"),
                )
            )
    return segments


def _split_paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def _classify_attachment_kind(*, role: str, media_type: str, path: str) -> str:
    lowered_path = path.lower()
    lowered_role = role.lower()
    if media_type.startswith("video/") or lowered_role == "video_file":
        return "video"
    if media_type.startswith("audio/") or lowered_role == "audio_file":
        return "audio"
    if media_type.startswith("image/") or lowered_role == "thumbnail":
        return "image"
    if lowered_role == "subtitle":
        return "subtitle"
    if lowered_path.endswith(".xml") and "danmaku" in lowered_path:
        return "danmaku"
    if media_type == "application/json":
        return "metadata"
    if media_type.startswith("text/"):
        return "text"
    if media_type == "text/html":
        return "html"
    return "other"


def _read_transcript_segments(path: Path) -> list[dict[str, int | str | None]]:
    if not path.exists():
        return []
    if path.suffix.lower() == ".xml":
        return _parse_xml_comments(path.read_text(encoding="utf-8", errors="replace"))
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() == ".vtt":
        return _parse_vtt(text)
    if path.suffix.lower() == ".srt":
        return _parse_srt(text)
    if path.suffix.lower() == ".lrc":
        return _parse_lrc(text)
    cleaned = clean_text(text)
    if not cleaned:
        return []
    return [{"text": cleaned, "start_ms": None, "end_ms": None}]


def _parse_vtt(text: str) -> list[dict[str, int | str | None]]:
    segments: list[dict[str, int | str | None]] = []
    chunks = re.split(r"\n\s*\n", text)
    for chunk in chunks:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines or lines[0] == "WEBVTT":
            continue
        time_line = next((line for line in lines if "-->" in line), None)
        body_lines = [line for line in lines if "-->" not in line and not line.isdigit()]
        cleaned = clean_text("\n".join(body_lines))
        if not cleaned:
            continue
        start_ms, end_ms = _parse_time_range(time_line) if time_line else (None, None)
        segments.append({"text": cleaned, "start_ms": start_ms, "end_ms": end_ms})
    return segments


def _parse_srt(text: str) -> list[dict[str, int | str | None]]:
    return _parse_vtt(text.replace(",", "."))


def _parse_lrc(text: str) -> list[dict[str, int | str | None]]:
    segments: list[dict[str, int | str | None]] = []
    for line in text.splitlines():
        match = re.match(r"\[(\d+):(\d+)(?:\.(\d+))?\](.*)", line.strip())
        if not match:
            continue
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        millis = int((match.group(3) or "0").ljust(3, "0")[:3])
        cleaned = clean_text(match.group(4))
        if not cleaned:
            continue
        segments.append(
            {
                "text": cleaned,
                "start_ms": minutes * 60_000 + seconds * 1_000 + millis,
                "end_ms": None,
            }
        )
    return segments


def _parse_xml_comments(text: str) -> list[dict[str, int | str | None]]:
    segments: list[dict[str, int | str | None]] = []
    for index, match in enumerate(re.finditer(r"<d\b[^>]*p=\"([^\"]+)\"[^>]*>(.*?)</d>", text, re.S), start=1):
        payload = match.group(1).split(",")
        seconds = _safe_float(payload[0]) if payload else None
        cleaned = clean_text(_strip_xml(match.group(2)))
        if not cleaned:
            continue
        segments.append(
            {
                "text": cleaned,
                "start_ms": int(seconds * 1000) if seconds is not None else None,
                "end_ms": None,
            }
        )
        if index >= 200:
            break
    return segments


def _strip_xml(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value)


def _parse_time_range(value: str) -> tuple[int | None, int | None]:
    if not value or "-->" not in value:
        return None, None
    start_raw, end_raw = [part.strip() for part in value.split("-->", 1)]
    return _parse_timestamp(start_raw), _parse_timestamp(end_raw)


def _parse_timestamp(value: str) -> int | None:
    match = re.match(r"(?:(\d+):)?(\d+):(\d+)\.(\d+)", value)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4).ljust(3, "0")[:3])
    return (((hours * 60) + minutes) * 60 + seconds) * 1000 + millis


def _safe_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
