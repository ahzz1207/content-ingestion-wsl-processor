from pathlib import Path
from content_ingestion.raw.image_parser import parse_image

FAKE_METADATA = {
    "job_id": "test_job",
    "source_url": "local://image/test_job",
    "platform": "local",
    "collector": "windows-client-local",
    "collected_at": "2026-04-12T00:00:00+00:00",
    "content_type": "image",
    "content_shape": "image",
    "requested_mode": "auto",
}


def test_parse_image_content_shape(tmp_path):
    img = tmp_path / "payload.png"
    img.write_bytes(b"PNG-fake")
    asset = parse_image(img, FAKE_METADATA)
    assert asset.content_shape == "image"


def test_parse_image_content_text_empty(tmp_path):
    img = tmp_path / "payload.png"
    img.write_bytes(b"PNG-fake")
    asset = parse_image(img, FAKE_METADATA)
    assert asset.content_text == ""


def test_parse_image_has_analysis_frame_attachment(tmp_path):
    img = tmp_path / "payload.png"
    img.write_bytes(b"PNG-fake")
    asset = parse_image(img, FAKE_METADATA)
    frames = [a for a in asset.attachments if a.role == "analysis_frame"]
    assert len(frames) == 1
    assert frames[0].media_type == "image/png"


def test_parse_image_copies_file(tmp_path):
    img = tmp_path / "payload.png"
    img.write_bytes(b"PNG-real")
    parse_image(img, FAKE_METADATA)
    copied = tmp_path / "attachments" / "image" / "source.png"
    assert copied.exists()
    assert copied.read_bytes() == b"PNG-real"


def test_parse_image_jpeg(tmp_path):
    img = tmp_path / "payload.jpg"
    img.write_bytes(b"JPEG-fake")
    asset = parse_image(img, FAKE_METADATA)
    frames = [a for a in asset.attachments if a.role == "analysis_frame"]
    assert frames[0].media_type == "image/jpeg"


def test_parse_image_source_platform(tmp_path):
    img = tmp_path / "payload.png"
    img.write_bytes(b"PNG")
    asset = parse_image(img, FAKE_METADATA)
    assert asset.source_platform == "local"
