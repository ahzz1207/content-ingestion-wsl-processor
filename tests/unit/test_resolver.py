from content_ingestion.sources.registry import ConnectorRegistry
from content_ingestion.sources.resolver import resolve_platform


def test_resolve_platform_for_wechat_url() -> None:
    registry = ConnectorRegistry.default()
    platform = resolve_platform("https://mp.weixin.qq.com/s/example", registry)
    assert platform == "wechat"
