from pathlib import Path

from content_ingestion.core.models import ContentAsset
from content_ingestion.normalize.cleaning import clean_markdown_text
from content_ingestion.raw.common import optional_datetime, optional_str
from content_ingestion.raw.structure import build_attachment_inventory, build_evidence_segments, build_text_blocks


def parse_markdown(
    payload_path: Path,
    metadata: dict[str, object],
    *,
    capture_manifest: dict[str, object] | None = None,
) -> ContentAsset:
    markdown = payload_path.read_text(encoding="utf-8")
    title = optional_str(metadata.get("title_hint")) or _extract_title(markdown) or "Untitled"
    source_url = str(metadata["source_url"])
    cleaned_markdown = clean_markdown_text(markdown)
    blocks = build_text_blocks(cleaned_markdown, title=title)
    attachments = build_attachment_inventory(payload_path.parent, capture_manifest)
    evidence_segments = build_evidence_segments(job_dir=payload_path.parent, blocks=blocks, attachments=attachments)
    return ContentAsset(
        source_platform=str(metadata.get("platform") or "generic"),
        source_url=source_url,
        canonical_url=str(metadata.get("final_url") or source_url),
        content_shape=optional_str(metadata.get("content_shape")) or "markdown",
        title=title,
        author=optional_str(metadata.get("author_hint")),
        published_at=optional_datetime(metadata.get("published_at_hint")),
        content_text=cleaned_markdown,
        content_markdown=markdown.strip(),
        blocks=blocks,
        attachments=attachments,
        evidence_segments=evidence_segments,
        metadata={"job_id": metadata["job_id"], "content_type": metadata["content_type"]},
    )


def _extract_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return None
