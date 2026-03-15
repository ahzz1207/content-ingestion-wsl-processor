from datetime import datetime
from html import unescape
import re

from content_ingestion.core.models import ContentAsset
from content_ingestion.normalize.cleaning import clean_text


class WechatExtractor:
    TITLE_PATTERNS = [
        re.compile(r'<h1[^>]*id="activity-name"[^>]*>(?P<value>.*?)</h1>', re.S),
        re.compile(r"<title>(?P<value>.*?)</title>", re.S),
    ]
    AUTHOR_PATTERNS = [
        re.compile(r'<span[^>]*id="js_name"[^>]*>(?P<value>.*?)</span>', re.S),
        re.compile(
            r'<meta[^>]*property="og:article:author"[^>]*content="(?P<value>.*?)"[^>]*>',
            re.S,
        ),
    ]
    BODY_PATTERN = re.compile(r'<div[^>]*id="js_content"[^>]*>(?P<value>.*?)</div>', re.S)
    PUBLISH_PATTERNS = [
        re.compile(r'var\s+publish_time\s*=\s*"(?P<value>[^"]+)"', re.S),
        re.compile(r'data-publish-time="(?P<value>[^"]+)"', re.S),
    ]

    def from_text(self, url: str, title: str, body: str) -> ContentAsset:
        return ContentAsset(
            source_platform="wechat",
            source_url=url,
            canonical_url=url,
            title=title,
            content_text=clean_text(body),
        )

    def from_html(self, url: str, html: str) -> ContentAsset:
        title = self._extract_first(html, self.TITLE_PATTERNS) or "Untitled WeChat Article"
        author = self._extract_first(html, self.AUTHOR_PATTERNS)
        body_html = self._extract_body_html(html)
        body_text = self._strip_html(body_html)
        published_at = self._parse_datetime(self._extract_first(html, self.PUBLISH_PATTERNS))
        return ContentAsset(
            source_platform="wechat",
            source_url=url,
            canonical_url=url,
            title=title,
            author=author,
            published_at=published_at,
            content_text=body_text,
            metadata={"source": "wechat"},
        )

    def _extract_first(self, html: str, patterns: list[re.Pattern[str]]) -> str | None:
        for pattern in patterns:
            match = pattern.search(html)
            if match:
                return clean_text(self._strip_html(match.group("value")))
        return None

    def _extract_body_html(self, html: str) -> str:
        match = self.BODY_PATTERN.search(html)
        if not match:
            return ""
        return match.group("value")

    def _strip_html(self, value: str) -> str:
        normalized = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        normalized = re.sub(r"</p>", "\n\n", normalized, flags=re.I)
        normalized = re.sub(r"<script.*?</script>", "", normalized, flags=re.I | re.S)
        normalized = re.sub(r"<style.*?</style>", "", normalized, flags=re.I | re.S)
        normalized = re.sub(r"<[^>]+>", "", normalized)
        return clean_text(unescape(normalized))

    def _parse_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue
        return None
