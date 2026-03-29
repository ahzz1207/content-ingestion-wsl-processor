import json
import logging
from html import unescape
import re
from pathlib import Path

from content_ingestion.core.models import ContentAsset
from content_ingestion.normalize.cleaning import clean_text
from content_ingestion.raw.common import optional_datetime, optional_str
from content_ingestion.raw.structure import (
    build_attachment_inventory,
    build_blocks_from_records,
    build_evidence_segments,
    build_text_blocks,
)


def _marker_variants(value: str) -> tuple[str, ...]:
    variants = [value]
    try:
        mojibake = value.encode("utf-8").decode("latin1")
    except UnicodeError:
        mojibake = ""
    if mojibake and mojibake != value:
        variants.append(mojibake)
    return tuple(variants)


_WECHAT_BODY_CONTAINER_ID = "img-content"
_WECHAT_FOOTER_MARKERS_RAW = (
    "\u9884\u89c8\u65f6\u6807\u7b7e\u4e0d\u53ef\u70b9",
    "\u7559\u8a00\u6682\u65e0\u7559\u8a00",
    "\u7ee7\u7eed\u6ed1\u52a8\u770b\u4e0b\u4e00\u4e2a",
    "\u8f7b\u89e6\u9605\u8bfb\u539f\u6587",
    "\u5f53\u524d\u5185\u5bb9\u53ef\u80fd\u5b58\u5728\u672a\u7ecf\u5ba1\u6838\u7684\u7b2c\u4e09\u65b9\u5546\u4e1a\u8425\u9500\u4fe1\u606f",
    "\u5fae\u4fe1\u626b\u4e00\u626b",
    "\u4f7f\u7528\u5c0f\u7a0b\u5e8f",
    "\u5199\u7559\u8a00",
    "\u8d5e\u8d4f\u4f5c\u8005",
    "\u5df2\u5173\u6ce8\u8d5e\u5206\u4eab\u63a8\u8350 \u5199\u7559\u8a00",
)
_WECHAT_NOISE_LINES_RAW = {
    "\u539f\u521b",
    "\u5728\u5c0f\u8bf4\u9605\u8bfb\u5668\u4e2d\u6c89\u6d78\u9605\u8bfb",
    "\u5206\u6790",
    "\u89c6\u9891",
    "\u5c0f\u7a0b\u5e8f",
    "\u8d5e",
    "\u5728\u770b",
    "\u5206\u4eab",
    "\u7559\u8a00",
    "\u6536\u85cf",
    "\u542c\u8fc7",
    "\u5173\u95ed\u66f4\u591a",
    "\u53d6\u6d88",
    "\u5141\u8bb8",
    "\u77e5\u9053\u4e86",
}
_WECHAT_NOISE_PREFIXES_RAW = (
    "\u516c\u4f17\u53f7\u8bb0\u5f97\u52a0\u661f\u6807",
    "\u641c\u7d22\u300c",
    "\u9009\u62e9\u7559\u8a00\u8eab\u4efd",
    "\u8be5\u8d26\u53f7\u56e0\u8fdd\u89c4\u65e0\u6cd5\u8df3\u8f6c",
    "\u53ef\u5728\u300c\u516c\u4f17\u53f7",
)
_GENERIC_CONTAINER_SIGNALS = (
    "article",
    "content",
    "post-content",
    "entry-content",
    "article-content",
    "rich_media_content",
    "story-body",
    "main-content",
    "note-text",
    "desc",
)
_GENERIC_SHELL_PATTERNS = (
    re.compile(r"^\s*(home|about|menu|search|sign in|sign up)\s*$", re.I),
    re.compile(r"^\s*(copyright|all rights reserved)\b", re.I),
    re.compile(r"^\s*(related articles|recommended|you may also like)\b", re.I),
)
_XHS_INTERACTION_KEYWORDS = frozenset({
    "姐妹们", "宝子们", "点个赞", "关注一下", "收藏备用",
    "双击屏幕", "快来看", "赶快冲", "必收藏",
})
_XHS_HASHTAG_RE = re.compile(r"^#\S+(\s+#\S+)*\s*$")
_XHS_EMOJI_RE = re.compile(r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF]")
_XHS_INTERACTION_TAIL_THRESHOLD = 4

_WECHAT_FOOTER_MARKERS = tuple(item for marker in _WECHAT_FOOTER_MARKERS_RAW for item in _marker_variants(marker))
_WECHAT_NOISE_LINES = {item for marker in _WECHAT_NOISE_LINES_RAW for item in _marker_variants(marker)}
_WECHAT_NOISE_PREFIXES = tuple(item for marker in _WECHAT_NOISE_PREFIXES_RAW for item in _marker_variants(marker))


def parse_html(
    payload_path: Path,
    metadata: dict[str, object],
    *,
    capture_manifest: dict[str, object] | None = None,
) -> ContentAsset:
    html = payload_path.read_text(encoding="utf-8")
    platform = str(metadata.get("platform") or "generic")
    title = optional_str(metadata.get("title_hint")) or _extract_title(html) or "Untitled"
    body_html, body = _extract_body_content(html, platform=platform, title=title)
    source_url = str(metadata["source_url"])
    block_records = _extract_html_block_records(body_html or html, title=title)
    if platform == "wechat":
        block_records = _trim_wechat_block_records(block_records, title=title)
    elif platform == "xiaohongshu":
        original_block_count = len(block_records)
        block_records, xhs_denoise_stats = _trim_xiaohongshu_block_records(block_records)
        xhs_denoise_stats["original_block_count"] = original_block_count
        xhs_denoise_stats["retained_block_count"] = len(block_records)
        logging.getLogger(__name__).debug(
            "xiaohongshu denoise: removed %d blocks", xhs_denoise_stats["removed_count"]
        )
        try:
            denoise_report_path = payload_path.parent / "denoise_report.json"
            denoise_report_path.write_text(
                json.dumps({"platform": "xiaohongshu", "denoise_stats": xhs_denoise_stats}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
    blocks = build_blocks_from_records(block_records, title=title) if block_records else build_text_blocks(body, title=title)
    attachments = build_attachment_inventory(payload_path.parent, capture_manifest)
    evidence_segments = build_evidence_segments(job_dir=payload_path.parent, blocks=blocks, attachments=attachments)
    return ContentAsset(
        source_platform=platform,
        source_url=source_url,
        canonical_url=str(metadata.get("final_url") or source_url),
        content_shape=optional_str(metadata.get("content_shape")) or "webpage",
        title=title,
        author=optional_str(metadata.get("author_hint")),
        published_at=optional_datetime(metadata.get("published_at_hint")),
        content_text=_build_content_text_from_blocks(blocks, fallback=body, title=title),
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


def _extract_body_content(html: str, *, platform: str, title: str) -> tuple[str | None, str]:
    if platform == "wechat":
        return _extract_wechat_body_text(html, title=title)
    return _extract_generic_body_text(html, title=title)


def _extract_wechat_body_text(html: str, *, title: str) -> tuple[str | None, str]:
    article_html = _extract_element_html_by_id(html, element_id=_WECHAT_BODY_CONTAINER_ID, tag_name="div")
    body_text = _strip_html(article_html or html)
    return article_html, _trim_wechat_shell_text(body_text, title=title)


def _extract_generic_body_text(html: str, *, title: str) -> tuple[str | None, str]:
    body_html = _extract_body_html(html)
    candidate_html = _extract_best_generic_container_html(body_html or html)
    body_text = _strip_html(candidate_html or body_html or html)
    return candidate_html or body_html, _trim_generic_shell_text(body_text, title=title)


def _extract_body_html(html: str) -> str | None:
    match = re.search(r"<body[^>]*>(?P<value>.*?)</body>", html, re.I | re.S)
    if match:
        return match.group("value")
    return None


def _extract_best_generic_container_html(html: str) -> str | None:
    candidates: list[str] = []
    for tag_name in ("article", "main", "section", "div"):
        pattern = re.compile(
            rf"<{tag_name}\b(?P<attrs>[^>]*)>(?P<content>.*?)</{tag_name}>",
            re.I | re.S,
        )
        for match in pattern.finditer(html):
            attrs = match.group("attrs") or ""
            attrs_lower = attrs.lower()
            if tag_name in {"article", "main"}:
                candidates.append(match.group(0))
                continue
            if any(signal in attrs_lower for signal in _GENERIC_CONTAINER_SIGNALS):
                candidates.append(match.group(0))
    if not candidates:
        return None
    candidates.sort(key=lambda item: len(_strip_html(item)), reverse=True)
    return candidates[0]


def _extract_element_html_by_id(html: str, *, element_id: str, tag_name: str) -> str | None:
    markers = (f'id="{element_id}"', f"id='{element_id}'")
    index = -1
    for marker in markers:
        index = html.find(marker)
        if index != -1:
            break
    if index == -1:
        return None
    start = html.rfind(f"<{tag_name}", 0, index)
    if start == -1:
        return None

    open_pattern = re.compile(rf"<{tag_name}\b", re.I)
    close_pattern = re.compile(rf"</{tag_name}>", re.I)
    depth = 0
    cursor = start
    while cursor < len(html):
        open_match = open_pattern.search(html, cursor)
        close_match = close_pattern.search(html, cursor)
        if close_match is None:
            return None
        if open_match is not None and open_match.start() < close_match.start():
            depth += 1
            cursor = open_match.end()
            continue
        depth -= 1
        cursor = close_match.end()
        if depth == 0:
            return html[start:cursor]
    return None


def _trim_wechat_shell_text(text: str, *, title: str) -> str:
    for marker in _WECHAT_FOOTER_MARKERS:
        position = text.find(marker)
        if position != -1:
            text = text[:position]
            break

    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    title_seen = False
    for line in lines:
        if not line:
            continue
        if line == title:
            if title_seen:
                continue
            title_seen = True
        if line in _WECHAT_NOISE_LINES:
            continue
        if any(line.startswith(prefix) for prefix in _WECHAT_NOISE_PREFIXES):
            continue
        if line.endswith("\u7f51\u7edc\u7ed3\u679c"):
            continue
        cleaned.append(line)
    return clean_text("\n".join(cleaned))


def _trim_wechat_block_records(records: list[dict[str, object]], *, title: str) -> list[dict[str, object]]:
    cleaned: list[dict[str, object]] = []
    title_seen = False
    for record in records:
        text = clean_text(str(record.get("text") or ""))
        if not text:
            continue
        if text == title:
            if title_seen:
                continue
            title_seen = True
        if text in _WECHAT_NOISE_LINES:
            continue
        if any(text.startswith(prefix) for prefix in _WECHAT_NOISE_PREFIXES):
            continue
        if text.endswith("\u7f51\u7edc\u7ed3\u679c") or text.endswith("ç½‘ç»œç»“æžœ"):
            continue
        if any(marker in text for marker in _WECHAT_FOOTER_MARKERS):
            break
        cleaned.append(record)
    return cleaned


def _trim_xiaohongshu_block_records(
    records: list[dict[str, object]],
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Remove XHS platform noise. Returns (cleaned_records, stats)."""
    cleaned: list[dict[str, object]] = []
    stats: dict[str, int] = {"removed_count": 0, "hashtag_lines": 0, "interaction_lines": 0, "tail_truncated": 0}
    interaction_streak = 0
    for record in records:
        text = clean_text(str(record.get("text") or "")).strip()
        if not text:
            continue
        if _XHS_HASHTAG_RE.match(text):
            stats["hashtag_lines"] += 1
            stats["removed_count"] += 1
            continue
        if text in _XHS_INTERACTION_KEYWORDS:
            interaction_streak += 1
            stats["interaction_lines"] += 1
            stats["removed_count"] += 1
            if interaction_streak >= _XHS_INTERACTION_TAIL_THRESHOLD:
                stats["tail_truncated"] = 1
                break
            continue
        interaction_streak = 0
        emojis = _XHS_EMOJI_RE.findall(text)
        if len(emojis) > 4:
            positions = [m.start() for m in _XHS_EMOJI_RE.finditer(text)]
            trimmed_text = text[:positions[4]].rstrip()
            record = dict(record)
            record["text"] = trimmed_text
        cleaned.append(record)
    return cleaned, stats


def _trim_generic_shell_text(text: str, *, title: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    title_seen = False
    for line in lines:
        if not line:
            continue
        if line == title:
            if title_seen:
                continue
            title_seen = True
        if any(pattern.match(line) for pattern in _GENERIC_SHELL_PATTERNS):
            continue
        cleaned.append(line)
    return clean_text("\n".join(cleaned))


def _extract_html_block_records(html: str, *, title: str) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    pattern = re.compile(
        r"<(?P<tag>h[1-6]|p|li|figcaption|caption|img|tr)\b(?P<attrs>[^>]*)>(?P<content>.*?)</(?P=tag)>"
        r"|<img\b(?P<img_attrs>[^>]*)/?>",
        re.I | re.S,
    )
    for match in pattern.finditer(html):
        tag = (match.group("tag") or "img").lower()
        attrs = match.group("attrs") or match.group("img_attrs") or ""
        content = match.group("content") or ""
        record = _build_block_record_from_tag(tag=tag, attrs=attrs, content=content, title=title)
        if record is not None:
            records.append(record)
    return records


def _build_block_record_from_tag(*, tag: str, attrs: str, content: str, title: str) -> dict[str, object] | None:
    if tag.startswith("h"):
        text = _strip_html(content)
        if not text or text == title:
            return None
        return {
            "kind": "heading",
            "text": text,
            "heading_level": int(tag[1]),
            "source": tag,
        }
    if tag == "p":
        text = _strip_html(content)
        if not text:
            return None
        return {"kind": "paragraph", "text": text, "source": "p"}
    if tag == "li":
        text = _strip_html(content)
        if not text:
            return None
        return {"kind": "list_item", "text": text, "source": "li"}
    if tag in {"figcaption", "caption"}:
        text = _strip_html(content)
        if not text:
            return None
        return {"kind": "image_caption" if tag == "figcaption" else "table_row", "text": text, "source": tag}
    if tag == "img":
        description = _extract_attr(attrs, "alt") or _extract_attr(attrs, "title")
        if not description:
            return None
        return {"kind": "image_caption", "text": clean_text(description), "source": "img"}
    if tag == "tr":
        cells = re.findall(r"<(?:td|th)\b[^>]*>(.*?)</(?:td|th)>", content, re.I | re.S)
        row_text = " | ".join(filter(None, (_strip_html(cell) for cell in cells)))
        if not row_text:
            return None
        return {"kind": "table_row", "text": row_text, "source": "tr"}
    return None


def _extract_attr(attrs: str, name: str) -> str | None:
    match = re.search(rf"""\b{name}\s*=\s*(['"])(?P<value>.*?)\1""", attrs, re.I | re.S)
    if not match:
        return None
    value = clean_text(unescape(match.group("value")))
    return value or None


def _build_content_text_from_blocks(blocks, *, fallback: str, title: str) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.kind == "heading" and block.text == title:
            continue
        if not block.text.strip():
            continue
        parts.append(block.text)
    if not parts:
        return fallback
    return clean_text("\n\n".join(parts))


def _strip_html(value: str) -> str:
    normalized = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    normalized = re.sub(r"</p>", "\n\n", normalized, flags=re.I)
    normalized = re.sub(r"<script.*?</script>", "", normalized, flags=re.I | re.S)
    normalized = re.sub(r"<style.*?</style>", "", normalized, flags=re.I | re.S)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    return clean_text(unescape(normalized))
