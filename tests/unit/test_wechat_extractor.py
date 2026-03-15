from pathlib import Path

from content_ingestion.sources.wechat.extractor import WechatExtractor


def test_wechat_extractor_parses_article_fixture() -> None:
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "wechat_article.html"
    html = fixture.read_text(encoding="utf-8")

    asset = WechatExtractor().from_html("https://mp.weixin.qq.com/s/example", html)

    assert asset.title == "测试公众号文章标题"
    assert asset.author == "OpenClaw Weekly"
    assert asset.published_at is not None
    assert "第一段内容。" in asset.content_text
    assert "第二段内容，包含 加粗 文本。" in asset.content_text
