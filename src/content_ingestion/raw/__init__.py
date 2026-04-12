from pathlib import Path

from content_ingestion.core.models import ContentAsset

from .html_parser import parse_html
from .markdown_parser import parse_markdown
from .text_parser import parse_text

_IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})


def parse_payload(
    payload_path: Path,
    metadata: dict[str, object],
    *,
    capture_manifest: dict[str, object] | None = None,
) -> ContentAsset:
    suffix = payload_path.suffix.lower()
    if suffix == ".html":
        return parse_html(payload_path, metadata, capture_manifest=capture_manifest)
    if suffix in (".txt",):
        return parse_text(payload_path, metadata, capture_manifest=capture_manifest)
    if suffix == ".md":
        return parse_markdown(payload_path, metadata, capture_manifest=capture_manifest)
    if suffix == ".pdf":
        from .pdf_parser import parse_pdf
        return parse_pdf(payload_path, metadata, capture_manifest=capture_manifest)
    if suffix in _IMAGE_SUFFIXES:
        from .image_parser import parse_image
        return parse_image(payload_path, metadata, capture_manifest=capture_manifest)
    raise ValueError(f"Unsupported payload type: {payload_path.name}")
