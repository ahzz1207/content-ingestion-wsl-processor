import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


FAKE_METADATA = {
    "job_id": "test_job",
    "source_url": "file:///tmp/report.pdf",
    "platform": "local",
    "collector": "windows-client-local",
    "collected_at": "2026-04-12T00:00:00+00:00",
    "content_type": "pdf",
    "content_shape": "document",
    "requested_mode": "auto",
}


def _make_mock_doc(num_pages: int, text_per_page: str = "Page text"):
    pages = []
    for i in range(num_pages):
        page = MagicMock()
        page.get_text.return_value = f"{text_per_page} {i + 1}"
        pix = MagicMock()
        pix.save = MagicMock()
        page.get_pixmap.return_value = pix
        pages.append(page)
    doc = MagicMock()
    doc.__len__ = lambda self: num_pages
    doc.__iter__ = lambda self: iter(pages)
    doc.__getitem__ = lambda self, idx: pages[idx]
    return doc


def test_parse_pdf_extracts_text(tmp_path):
    payload = tmp_path / "payload.pdf"
    payload.write_bytes(b"%PDF")
    mock_doc = _make_mock_doc(3, "Hello page")
    with patch("content_ingestion.raw.pdf_parser.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock(return_value=MagicMock())
        from content_ingestion.raw.pdf_parser import parse_pdf
        asset = parse_pdf(payload, FAKE_METADATA)
    assert "Hello page 1" in asset.content_text
    assert "Hello page 3" in asset.content_text


def test_parse_pdf_creates_page_frames(tmp_path):
    payload = tmp_path / "payload.pdf"
    payload.write_bytes(b"%PDF")
    mock_doc = _make_mock_doc(3)
    with patch("content_ingestion.raw.pdf_parser.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock(return_value=MagicMock())
        from content_ingestion.raw.pdf_parser import parse_pdf
        asset = parse_pdf(payload, FAKE_METADATA)
    frames = [a for a in asset.attachments if a.role == "analysis_frame"]
    assert len(frames) == 3


def test_parse_pdf_caps_frames_at_20(tmp_path):
    payload = tmp_path / "payload.pdf"
    payload.write_bytes(b"%PDF")
    mock_doc = _make_mock_doc(50)
    with patch("content_ingestion.raw.pdf_parser.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock(return_value=MagicMock())
        from content_ingestion.raw.pdf_parser import parse_pdf
        asset = parse_pdf(payload, FAKE_METADATA)
    frames = [a for a in asset.attachments if a.role == "analysis_frame"]
    assert len(frames) == 20


def test_parse_pdf_content_shape(tmp_path):
    payload = tmp_path / "payload.pdf"
    payload.write_bytes(b"%PDF")
    mock_doc = _make_mock_doc(1)
    with patch("content_ingestion.raw.pdf_parser.fitz") as mock_fitz:
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock(return_value=MagicMock())
        from content_ingestion.raw.pdf_parser import parse_pdf
        asset = parse_pdf(payload, FAKE_METADATA)
    assert asset.content_shape == "document"
    assert asset.source_platform == "local"


def test_parse_pdf_missing_fitz_raises(tmp_path):
    payload = tmp_path / "payload.pdf"
    payload.write_bytes(b"%PDF")
    with patch("content_ingestion.raw.pdf_parser.fitz", None):
        from content_ingestion.raw.pdf_parser import parse_pdf
        with pytest.raises(ImportError, match="PyMuPDF"):
            parse_pdf(payload, FAKE_METADATA)
