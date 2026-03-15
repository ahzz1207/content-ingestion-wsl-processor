from html import unescape
import re
from pathlib import Path

from content_ingestion.core.models import ContentAsset
from content_ingestion.normalize.cleaning import clean_text
from content_ingestion.raw.common import optional_datetime, optional_str
from content_ingestion.raw.structure import build_attachment_inventory, build_evidence_segments, build_text_blocks


def parse_html(
    payload_path: Path,
    metadata: dict[str, object],
    *,
    capture_manifest: dict[str, object] | None = None,
) -> ContentAsset:
    html = payload_path.read_text(encoding="utf-8")
    title = optional_str(metadata.get("title_hint")) or _extract_title(html) or "Untitled"
    body = _extract_body_text(html)
    source_url = str(metadata["source_url"])
    blocks = build_text_blocks(body, title=title)
    attachments = build_attachment_inventory(payload_path.parent, capture_manifest)
    evidence_segments = build_evidence_segments(job_dir=payload_path.parent, blocks=blocks, attachments=attachments)
    return ContentAsset(
        source_platform=str(metadata.get("platform") or "generic"),
        source_url=source_url,
        canonical_url=str(metadata.get("final_url") or source_url),
        content_shape=optional_str(metadata.get("content_shape")) or "webpage",
        title=title,
        author=optional_str(metadata.get("author_hint")),
        published_at=optional_datetime(metadata.get("published_at_hint")),
        content_text=body,
        blocks=blocks,
        attachments=attachments,
        evidence_segments=evidence_segments,
        metadata={"job_id": metadata["job_id"], "content_type": metadata["content_type"]},
    )


def _extract_title(html: str) -> str | None:
    patterns = [
        re.compile(r"<title>(?P<value>.*?)</title>", re.I | re.S),
        re.compile(r"<h1[^>]*>(?P<value>.*?)</h1>", re.I | re.S),
    ]
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            title = _strip_html(match.group("value"))
            if title:
                return title
    return None


def _extract_body_text(html: str) -> str:
    match = re.search(r"<body[^>]*>(?P<value>.*?)</body>", html, re.I | re.S)
    body_html = match.group("value") if match else html
    return _strip_html(body_html)


def _strip_html(value: str) -> str:
    normalized = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    normalized = re.sub(r"</p>", "\n\n", normalized, flags=re.I)
    normalized = re.sub(r"<script.*?</script>", "", normalized, flags=re.I | re.S)
    normalized = re.sub(r"<style.*?</style>", "", normalized, flags=re.I | re.S)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    return clean_text(unescape(normalized))
