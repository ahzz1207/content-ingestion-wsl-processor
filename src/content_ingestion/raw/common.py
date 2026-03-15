from __future__ import annotations

from datetime import datetime
import re


def optional_str(value: object) -> str | None:
    return str(value) if value else None


def optional_datetime(value: object) -> datetime | None:
    if not value:
        return None

    raw = str(value).strip()
    if not raw:
        return None

    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y?%m?%d? %H:%M:%S",
        "%Y?%m?%d? %H:%M",
        "%Y?%m?%d?",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue

    numeric_parts = [int(part) for part in re.findall(r"\d+", raw)]
    if len(numeric_parts) in {3, 5, 6}:
        year, month, day = numeric_parts[:3]
        hour = numeric_parts[3] if len(numeric_parts) >= 5 else 0
        minute = numeric_parts[4] if len(numeric_parts) >= 5 else 0
        second = numeric_parts[5] if len(numeric_parts) >= 6 else 0
        try:
            return datetime(year, month, day, hour, minute, second)
        except ValueError:
            return None
    return None
