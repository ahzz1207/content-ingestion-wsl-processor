from __future__ import annotations
from pathlib import Path

try:
    import fitz
except ImportError:
    fitz = None

from content_ingestion.core.models import ContentAttachment, ContentAsset

MAX_FRAMES = 20
PAGE_RENDER_DPI = 150


def parse_pdf(payload_path: Path, metadata: dict, capture_manifest=None) -> ContentAsset:
    if fitz is None:
        raise ImportError("PyMuPDF is required for PDF parsing. Install it with: pip install pymupdf")
    doc = fitz.open(str(payload_path))
    total_pages = len(doc)
    pages_text = []
    for page in doc:
        pages_text.append(page.get_text())
    content_text = chr(10).join(pages_text)
    if total_pages <= MAX_FRAMES:
        frame_indices = list(range(total_pages))
    else:
        step = total_pages / MAX_FRAMES
        frame_indices = [int(i * step) for i in range(MAX_FRAMES)]
    frames_dir = payload_path.parent / "attachments" / "pages"
    frames_dir.mkdir(parents=True, exist_ok=True)
    attachments = []
    mat = fitz.Matrix(PAGE_RENDER_DPI / 72, PAGE_RENDER_DPI / 72)
    for idx in frame_indices:
        page = doc[idx]
        pix = page.get_pixmap(matrix=mat)
        frame_path = frames_dir / f"page_{idx:04d}.png"
        pix.save(str(frame_path))
        rel_path = frame_path.relative_to(payload_path.parent).as_posix()
        attachments.append(ContentAttachment(
            id=f"frame-page-{idx:04d}",
            kind="image",
            role="analysis_frame",
            media_type="image/png",
            path=rel_path,
            description=f"Page {idx + 1} of {total_pages}",
        ))
    title = metadata.get("title_hint") or payload_path.stem
    return ContentAsset(
        source_url=metadata.get("source_url", ""),
        source_platform=metadata.get("platform", "local"),
        content_shape="document",
        title=title,
        content_text=content_text,
        attachments=attachments,
    )
