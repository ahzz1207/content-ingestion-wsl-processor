from pathlib import Path

from content_ingestion.core.models import ContentAsset

from .html_parser import parse_html
from .markdown_parser import parse_markdown
from .text_parser import parse_text


def parse_payload(
    payload_path: Path,
    metadata: dict[str, object],
    *,
    capture_manifest: dict[str, object] | None = None,
) -> ContentAsset:
    suffix = payload_path.suffix.lower()
    if suffix == ".html":
        return parse_html(payload_path, metadata, capture_manifest=capture_manifest)
    if suffix == ".txt":
        return parse_text(payload_path, metadata, capture_manifest=capture_manifest)
    if suffix == ".md":
        return parse_markdown(payload_path, metadata, capture_manifest=capture_manifest)
    raise ValueError(f"Unsupported payload type: {payload_path.name}")
