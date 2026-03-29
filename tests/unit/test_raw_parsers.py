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


def test_parse_generic_article_prefers_content_container_over_full_body(tmp_path: Path) -> None:
    payload = tmp_path / "payload.html"
    payload.write_text(
        """
        <html>
          <head><title>Generic Story</title></head>
          <body>
            <nav>Home Search Sign in</nav>
            <article class="post-content">
              <h1>Generic Story</h1>
              <p>Lead paragraph.</p>
              <p>Main article body.</p>
            </article>
            <aside>Recommended stories</aside>
            <footer>Copyright Example Media</footer>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    asset = parse_payload(
        payload,
        {
            "job_id": "job-generic",
            "source_url": "https://example.com/story",
            "platform": "generic",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "html",
        },
    )

    assert "Lead paragraph." in asset.content_text
    assert "Main article body." in asset.content_text
    assert "Home Search Sign in" not in asset.content_text
    assert "Recommended stories" not in asset.content_text
    assert "Copyright Example Media" not in asset.content_text


def test_parse_html_preserves_image_caption_and_table_rows_as_blocks(tmp_path: Path) -> None:
    payload = tmp_path / "payload.html"
    payload.write_text(
        """
        <html>
          <head><title>Chip Story</title></head>
          <body>
            <article class="article-content">
              <h2>Supply shift</h2>
              <p>Paragraph body.</p>
              <figure>
                <img src="demo.jpg" alt="Factory floor image" />
                <figcaption>Production line in Wuxi.</figcaption>
              </figure>
              <table>
                <tr><th>Quarter</th><th>Revenue</th></tr>
                <tr><td>Q1</td><td>10</td></tr>
              </table>
            </article>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    asset = parse_payload(
        payload,
        {
            "job_id": "job-structured-html",
            "source_url": "https://example.com/chip-story",
            "platform": "generic",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "html",
        },
    )

    block_kinds = [block.kind for block in asset.blocks]
    assert "heading" in block_kinds
    assert "paragraph" in block_kinds
    assert "image_caption" in block_kinds
    assert "table_row" in block_kinds
    assert any("Production line in Wuxi." == block.text for block in asset.blocks)
    assert any("Quarter | Revenue" == block.text for block in asset.blocks)
    assert any("Q1 | 10" == block.text for block in asset.blocks)
    assert any(segment.kind == "image_caption" for segment in asset.evidence_segments)
    assert any(segment.kind == "table_row" for segment in asset.evidence_segments)


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
            "published_at_hint": "2026年3月14日 12:58",
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


def test_parse_wechat_html_payload_trims_shell_text(tmp_path: Path) -> None:
    payload = tmp_path / "payload.html"
    payload.write_text(
        """
        <html>
          <head><title>存储涨完，MLCC要接力了吗？</title></head>
          <body>
            <div id="img-content">
              <h1>存储涨完，MLCC要接力了吗？</h1>
              <p>第一段正文。</p>
              <p>第二段正文。</p>
              <p>预览时标签不可点</p>
              <p>关闭更多</p>
              <p>留言暂无留言</p>
              <p>微信扫一扫</p>
            </div>
          </body>
        </html>
        """,
        encoding="utf-8",
    )

    asset = parse_payload(
        payload,
        {
            "job_id": "job-wechat",
            "source_url": "https://mp.weixin.qq.com/s/demo",
            "platform": "wechat",
            "collector": "windows-client",
            "collected_at": "2026-03-12T15:30:00+08:00",
            "content_type": "html",
            "title_hint": "存储涨完，MLCC要接力了吗？",
        },
    )

    assert "第一段正文" in asset.content_text
    assert "第二段正文" in asset.content_text
    assert "预览时标签不可点" not in asset.content_text
    assert "留言暂无留言" not in asset.content_text
    assert "微信扫一扫" not in asset.content_text


def test_optional_datetime_parses_localized_numeric_timestamp() -> None:
    parsed = optional_datetime("2026年3月13日 13:30")

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
    assert len({segment.id for segment in asset.evidence_segments}) == len(asset.evidence_segments)
    assert any(segment.id.startswith("text-block-") for segment in asset.evidence_segments)
    assert any(segment.id.startswith("subtitle-") for segment in asset.evidence_segments)

    asset_again = parse_payload(
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

    assert [segment.id for segment in asset.evidence_segments] == [segment.id for segment in asset_again.evidence_segments]


def test_xiaohongshu_denoise_removes_hashtag_lines(tmp_path: Path) -> None:
    from content_ingestion.raw.html_parser import _trim_xiaohongshu_block_records

    records = [
        {"text": "This is real content about the topic."},
        {"text": "#hashtag1 #hashtag2 #hashtag3"},
        {"text": "More real content here."},
    ]
    cleaned, stats = _trim_xiaohongshu_block_records(records)

    assert len(cleaned) == 2
    assert cleaned[0]["text"] == "This is real content about the topic."
    assert cleaned[1]["text"] == "More real content here."
    assert stats["hashtag_lines"] == 1
    assert stats["removed_count"] == 1


def test_xiaohongshu_denoise_removes_interaction_keywords_and_truncates(tmp_path: Path) -> None:
    from content_ingestion.raw.html_parser import _trim_xiaohongshu_block_records

    records = [
        {"text": "Real content here."},
        {"text": "姐妹们"},
        {"text": "宝子们"},
        {"text": "点个赞"},
        {"text": "关注一下"},
        {"text": "This should be cut off."},
    ]
    cleaned, stats = _trim_xiaohongshu_block_records(records)

    assert len(cleaned) == 1
    assert cleaned[0]["text"] == "Real content here."
    assert stats["interaction_lines"] >= 4
    assert stats["tail_truncated"] == 1


def test_xiaohongshu_denoise_truncates_excess_emoji_but_keeps_line(tmp_path: Path) -> None:
    from content_ingestion.raw.html_parser import _trim_xiaohongshu_block_records

    records = [
        {"text": "Good content 😀😀😀😀😀 emoji overload here"},
    ]
    cleaned, stats = _trim_xiaohongshu_block_records(records)

    assert len(cleaned) == 1
    # Line kept but emoji tail trimmed (first 4 emojis mark the truncation point)
    assert "Good content" in cleaned[0]["text"]
    assert "emoji overload here" not in cleaned[0]["text"]
    assert stats["removed_count"] == 0


def test_xiaohongshu_denoise_returns_correct_stats(tmp_path: Path) -> None:
    from content_ingestion.raw.html_parser import _trim_xiaohongshu_block_records

    records = [
        {"text": "Normal content."},
        {"text": "#tag1"},
        {"text": "#tag2"},
        {"text": "姐妹们"},
    ]
    cleaned, stats = _trim_xiaohongshu_block_records(records)

    assert stats["removed_count"] == 3
    assert stats["hashtag_lines"] == 2
    assert stats["interaction_lines"] == 1


def test_xiaohongshu_denoise_writes_artifact(tmp_path: Path) -> None:
    import json
    payload = tmp_path / "payload.html"
    payload.write_text(
        "<html><body><p>Real content about the topic.</p><p>#tag1 #tag2</p><p>姐妹们</p></body></html>",
        encoding="utf-8",
    )

    asset = parse_payload(
        payload,
        {
            "job_id": "job-xhs",
            "source_url": "https://xiaohongshu.com/explore/abc",
            "platform": "xiaohongshu",
            "collector": "windows-client",
            "collected_at": "2026-03-29T10:00:00+08:00",
            "content_type": "html",
        },
    )

    denoise_report = tmp_path / "denoise_report.json"
    assert denoise_report.exists(), "denoise_report.json should be written for xiaohongshu"
    report = json.loads(denoise_report.read_text(encoding="utf-8"))
    assert report["platform"] == "xiaohongshu"
    assert "denoise_stats" in report
    assert report["denoise_stats"]["removed_count"] >= 2
    assert report["denoise_stats"]["original_block_count"] >= 3
    assert report["denoise_stats"]["retained_block_count"] < report["denoise_stats"]["original_block_count"]
