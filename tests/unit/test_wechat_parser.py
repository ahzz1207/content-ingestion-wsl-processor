from content_ingestion.sources.wechat.parser import canonicalize_url, supports_url


def test_wechat_parser_supports_mp_weixin_url() -> None:
    assert supports_url("https://mp.weixin.qq.com/s/example") is True


def test_wechat_parser_canonicalizes_tracking_query_params() -> None:
    url = (
        "https://mp.weixin.qq.com/s/example"
        "?__biz=abc&mid=1&idx=1&scene=1&clicktime=12345&from=groupmessage"
    )
    canonical = canonicalize_url(url)
    assert canonical == "https://mp.weixin.qq.com/s/example?__biz=abc&mid=1&idx=1"
