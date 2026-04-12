from pathlib import Path
from unittest.mock import MagicMock, patch
from content_ingestion.core.models import ContentAsset, ContentAttachment
from content_ingestion.pipeline.llm_pipeline import analyze_asset


def _make_image_asset(job_dir: Path) -> ContentAsset:
    img_dir = job_dir / "attachments" / "image"
    img_dir.mkdir(parents=True)
    img_file = img_dir / "source.png"
    img_file.write_bytes(b"PNG")
    return ContentAsset(
        source_url="local://image/test",
        source_platform="local",
        content_shape="image",
        title="Test Image",
        content_text="",
        attachments=[ContentAttachment(
            id="frame-source-image",
            kind="image",
            role="analysis_frame",
            media_type="image/png",
            path="attachments/image/source.png",
            description="Source image",
        )],
    )


def _fake_payload():
    return {
        "core_summary": "这是测试图片摘要",
        "bottom_line": "底线结论",
        "content_kind": "analysis",
        "author_stance": "objective",
        "audience_fit": "通用读者",
        "save_worthy_points": ["要点一", "要点二"],
        "resolved_mode": "argument",
        "author_thesis": "核心论点",
    }


def _make_settings():
    s = MagicMock()
    s.openai_api_key = "sk-test"
    s.analysis_model = "gpt-5.2"
    s.multimodal_model = "gpt-5.2"
    s.image_card_model = None
    s.openai_base_url = None
    s.llm_provider = "zenmux"
    return s


def test_analyze_asset_takes_image_branch(tmp_path):
    asset = _make_image_asset(tmp_path)
    settings = _make_settings()
    with patch("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", return_value=True),          patch("content_ingestion.pipeline.llm_pipeline._create_client"),          patch("content_ingestion.pipeline.llm_pipeline._call_structured_response", return_value=_fake_payload()),          patch("content_ingestion.pipeline.llm_pipeline._image_data_url", return_value="data:image/png;base64,fake"):
        result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)
    assert result.status == "pass"
    assert result.resolved_mode == "argument"
    assert result.summary == "这是测试图片摘要"


def test_analyze_image_single_llm_call(tmp_path):
    asset = _make_image_asset(tmp_path)
    settings = _make_settings()
    call_count = {"n": 0}
    def fake_call(**kwargs):
        call_count["n"] += 1
        return _fake_payload()
    with patch("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", return_value=True),          patch("content_ingestion.pipeline.llm_pipeline._create_client"),          patch("content_ingestion.pipeline.llm_pipeline._call_structured_response", side_effect=fake_call),          patch("content_ingestion.pipeline.llm_pipeline._image_data_url", return_value="data:image/png;base64,fake"):
        analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)
    assert call_count["n"] == 1


def test_analyze_image_no_frame_returns_skipped(tmp_path):
    asset = ContentAsset(
        source_url="local://image/test",
        source_platform="local",
        content_shape="image",
        title="Empty",
        content_text="",
        attachments=[],
    )
    settings = _make_settings()
    with patch("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", return_value=True),          patch("content_ingestion.pipeline.llm_pipeline._create_client"):
        result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)
    assert result.status == "skipped"


def test_analyze_image_produces_product_view(tmp_path):
    asset = _make_image_asset(tmp_path)
    settings = _make_settings()
    with patch("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", return_value=True),          patch("content_ingestion.pipeline.llm_pipeline._create_client"),          patch("content_ingestion.pipeline.llm_pipeline._call_structured_response", return_value=_fake_payload()),          patch("content_ingestion.pipeline.llm_pipeline._image_data_url", return_value="data:image/png;base64,fake"):
        result = analyze_asset(job_dir=tmp_path, asset=asset, settings=settings)
    assert result.structured_result is not None
    assert result.structured_result.product_view is not None
