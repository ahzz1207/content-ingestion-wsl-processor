from __future__ import annotations

import hashlib
import re


def build_evidence_segment_id(
    *,
    kind: str,
    source: str,
    text: str,
    sequence: int,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> str:
    kind_token = _slugify(kind, fallback="segment", max_length=16)
    source_token = _slugify(source, fallback="source", max_length=24)
    span_token = _span_token(sequence=sequence, start_ms=start_ms, end_ms=end_ms)
    text_token = hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:8]
    return f"{kind_token}-{source_token}-{span_token}-{text_token}"


def _span_token(*, sequence: int, start_ms: int | None, end_ms: int | None) -> str:
    if start_ms is not None or end_ms is not None:
        start_token = _ms_token(start_ms)
        end_token = _ms_token(end_ms)
        return f"{start_token}-{end_token}"
    return f"seq{sequence:04d}"


def _ms_token(value: int | None) -> str:
    if value is None:
        return "na"
    return f"{value:07d}"


def _slugify(value: str, *, fallback: str, max_length: int) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not normalized:
        return fallback
    return normalized[:max_length].rstrip("-") or fallback
