from pathlib import Path

from content_ingestion.core.models import ContentAsset
from content_ingestion.normalize.cleaning import clean_plaintext
from content_ingestion.raw.common import optional_datetime, optional_str
from content_ingestion.raw.structure import build_attachment_inventory, build_evidence_segments, build_text_blocks


def parse_text(
    payload_path: Path,
    metadata: dict[str, object],
    *,
    capture_manifest: dict[str, object] | None = None,
) -> ContentAsset:
    body = clean_plaintext(payload_path.read_text(encoding="utf-8"))
    title = optional_str(metadata.get("title_hint")) or _first_line(body) or "Untitled"
    source_url = str(metadata["source_url"])
    blocks = build_text_blocks(body, title=title)
    attachments = build_attachment_inventory(payload_path.parent, capture_manifest)
    evidence_segments = build_evidence_segments(job_dir=payload_path.parent, blocks=blocks, attachments=attachments)
    return ContentAsset(
        source_platform=str(metadata.get("platform") or "generic"),
        source_url=source_url,
        canonical_url=str(metadata.get("final_url") or source_url),
        content_shape=optional_str(metadata.get("content_shape")) or "plaintext",
        title=title,
        author=optional_str(metadata.get("author_hint")),
        published_at=optional_datetime(metadata.get("published_at_hint")),
        content_text=body,
        blocks=blocks,
        attachments=attachments,
        evidence_segments=evidence_segments,
        metadata={"job_id": metadata["job_id"], "content_type": metadata["content_type"]},
    )


def _first_line(value: str) -> str | None:
    for line in value.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return None
