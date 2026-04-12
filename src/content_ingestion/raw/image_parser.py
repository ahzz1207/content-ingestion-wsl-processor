from __future__ import annotations
import shutil
from pathlib import Path
from content_ingestion.core.models import ContentAttachment, ContentAsset

_MEDIA_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def parse_image(payload_path: Path, metadata: dict, capture_manifest=None) -> ContentAsset:
    suffix = payload_path.suffix.lower()
    media_type = _MEDIA_TYPES.get(suffix, "image/png")
    dest_dir = payload_path.parent / "attachments" / "image"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"source{suffix}"
    shutil.copy2(payload_path, dest)
    rel_path = dest.relative_to(payload_path.parent).as_posix()
    attachment = ContentAttachment(
        id="frame-source-image",
        kind="image",
        role="analysis_frame",
        media_type=media_type,
        path=rel_path,
        description="Source image",
    )
    title = metadata.get("title_hint") or payload_path.stem
    return ContentAsset(
        source_url=metadata.get("source_url", ""),
        source_platform=metadata.get("platform", "local"),
        content_shape="image",
        title=title,
        content_text="",
        attachments=[attachment],
    )
