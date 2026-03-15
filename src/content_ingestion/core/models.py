from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class ContentBlock:
    id: str
    kind: str
    text: str
    heading_level: int | None = None
    source: str | None = None


@dataclass(slots=True)
class ContentAttachment:
    id: str
    path: str
    role: str
    media_type: str
    kind: str
    size_bytes: int | None = None
    description: str | None = None


@dataclass(slots=True)
class EvidenceSegment:
    id: str
    kind: str
    text: str
    source: str
    start_ms: int | None = None
    end_ms: int | None = None


@dataclass(slots=True)
class ContentAsset:
    source_platform: str
    source_url: str
    canonical_url: str | None = None
    content_shape: str | None = None
    title: str = ""
    author: str | None = None
    published_at: datetime | None = None
    summary: str | None = None
    content_text: str = ""
    content_markdown: str | None = None
    transcript_text: str | None = None
    analysis_text: str | None = None
    analysis_items: list[str] = field(default_factory=list)
    verification_items: list[dict[str, Any]] = field(default_factory=list)
    synthesis: str | None = None
    language: str | None = None
    tags: list[str] = field(default_factory=list)
    media_urls: list[str] = field(default_factory=list)
    blocks: list[ContentBlock] = field(default_factory=list)
    attachments: list[ContentAttachment] = field(default_factory=list)
    evidence_segments: list[EvidenceSegment] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FetchResult:
    success: bool
    status: str
    platform: str
    url: str
    content: ContentAsset | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(slots=True)
class SessionStatus:
    platform: str
    is_available: bool
    updated_at: datetime | None = None
    expires_at: datetime | None = None
    account_hint: str | None = None


def to_dict(value: ContentAsset | FetchResult | SessionStatus) -> dict[str, Any]:
    return asdict(value)
