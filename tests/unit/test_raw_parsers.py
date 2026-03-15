from datetime import datetime
from pathlib import Path

from content_ingestion.raw import parse_payload
from content_ingestion.raw.common import optional_datetime


def test_parse_html_payload_extracts_title_and_text(tmp_path: Path) -> None:
    payload = tmp_path / "payload.html"
    payload.write_text(
        "<html><head><title>Hello</title></head><body><p>First</p><p>Second</p></body></html>",
        encoding="utf-8",
    )

    asset = parse_payload(
        payload,
        {
            "job_id": "job1",
            "source_url": "https://example.com/html",
            "platform": "generic",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "html",
        },
    )

    assert asset.title == "Hello"
    assert "First" in asset.content_text
    assert "Second" in asset.content_text
    assert asset.content_shape == "webpage"
    assert asset.blocks
    assert asset.evidence_segments


def test_parse_html_payload_prefers_hints_and_parses_published_at(tmp_path: Path) -> None:
    payload = tmp_path / "payload.html"
    payload.write_text(
        "<html><head><title>Payload Title</title></head><body><p>Body</p></body></html>",
        encoding="utf-8",
    )

    asset = parse_payload(
        payload,
        {
            "job_id": "job1b",
            "source_url": "https://example.com/html",
            "final_url": "https://example.com/final",
            "platform": "wechat",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "html",
            "title_hint": "Hint Title",
            "author_hint": "Hint Author",
            "published_at_hint": "2026\u5e743\u670814\u65e5 12:58",
        },
    )

    assert asset.title == "Hint Title"
    assert asset.author == "Hint Author"
    assert asset.canonical_url == "https://example.com/final"
    assert asset.published_at is not None
    assert asset.published_at.year == 2026
    assert asset.published_at.month == 3
    assert asset.published_at.day == 14
    assert asset.published_at.hour == 12
    assert asset.published_at.minute == 58


def test_optional_datetime_parses_localized_numeric_timestamp() -> None:
    parsed = optional_datetime("2026\u5e743\u670813\u65e5 13:30")

    assert parsed == datetime(2026, 3, 13, 13, 30)


def test_parse_markdown_payload_keeps_original_markdown(tmp_path: Path) -> None:
    payload = tmp_path / "payload.md"
    payload.write_text("# Hello\n\n- one\n- two\n", encoding="utf-8")

    asset = parse_payload(
        payload,
        {
            "job_id": "job2",
            "source_url": "https://example.com/md",
            "platform": "generic",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "md",
        },
    )

    assert asset.title == "Hello"
    assert asset.content_markdown == "# Hello\n\n- one\n- two"
    assert asset.content_text == "# Hello\n\n- one\n- two"
    assert asset.language is None
    assert asset.blocks


def test_parse_text_payload_sets_language_to_none(tmp_path: Path) -> None:
    payload = tmp_path / "payload.txt"
    payload.write_text("line 1\nline 2\n", encoding="utf-8")

    asset = parse_payload(
        payload,
        {
            "job_id": "job3",
            "source_url": "https://example.com/txt",
            "platform": "generic",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "txt",
        },
    )

    assert asset.content_text == "line 1\n\nline 2"
    assert asset.language is None
    assert asset.blocks


def test_parse_html_payload_builds_attachment_inventory_and_evidence_segments(tmp_path: Path) -> None:
    payload = tmp_path / "payload.html"
    payload.write_text("<html><head><title>Video</title></head><body><p>Body text</p></body></html>", encoding="utf-8")
    attachments_dir = tmp_path / "attachments" / "video"
    attachments_dir.mkdir(parents=True)
    subtitle_path = attachments_dir / "video.en.vtt"
    subtitle_path.write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello world\n\n00:00:01.000 --> 00:00:02.000\nsecond line\n",
        encoding="utf-8",
    )
    audio_path = attachments_dir / "video.mp3"
    audio_path.write_bytes(b"audio")

    asset = parse_payload(
        payload,
        {
            "job_id": "job4",
            "source_url": "https://example.com/video",
            "platform": "bilibili",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "html",
            "content_shape": "video",
        },
        capture_manifest={
            "primary_payload": {"path": "payload.html"},
            "artifacts": [
                {"path": "payload.html", "role": "focused_capture", "media_type": "text/html", "is_primary": True},
                {
                    "path": "attachments/video/video.mp3",
                    "role": "audio_file",
                    "media_type": "audio/mpeg",
                    "size_bytes": 5,
                    "is_primary": False,
                },
                {
                    "path": "attachments/video/video.en.vtt",
                    "role": "subtitle",
                    "media_type": "text/vtt",
                    "size_bytes": subtitle_path.stat().st_size,
                    "is_primary": False,
                },
            ],
        },
    )

    assert asset.content_shape == "video"
    assert [attachment.kind for attachment in asset.attachments] == ["audio", "subtitle"]
    assert any(segment.kind == "subtitle" for segment in asset.evidence_segments)
    assert any("hello world" in segment.text for segment in asset.evidence_segments)
