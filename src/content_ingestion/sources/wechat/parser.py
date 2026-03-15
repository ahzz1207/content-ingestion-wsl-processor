from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


def supports_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "weixin.qq.com" in host


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"scene", "from", "clicktime", "enterid", "chksm"}
    ]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(filtered_query),
            "",
        )
    )
