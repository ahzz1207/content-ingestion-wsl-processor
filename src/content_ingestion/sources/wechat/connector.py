from datetime import datetime, timezone

from content_ingestion.core.enums import FetchStatus
from content_ingestion.core.models import FetchResult, SessionStatus
from content_ingestion.sources.base import BaseConnector

from .extractor import WechatExtractor
from .parser import canonicalize_url, supports_url


class WechatConnector(BaseConnector):
    platform = "wechat"
    DEFAULT_START_URL = "https://mp.weixin.qq.com/"

    def __init__(self) -> None:
        self.extractor = WechatExtractor()

    def supports(self, url: str) -> bool:
        return supports_url(url)

    def login(
        self, runtime, *, profile_dir=None, start_url: str | None = None
    ) -> tuple[SessionStatus, dict | None]:
        if profile_dir is None:
            raise ValueError("Wechat reader mode requires a persistent profile directory.")

        context = runtime.launch_persistent_context(profile_dir)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(start_url or self.DEFAULT_START_URL, wait_until="domcontentloaded")
        print(
            "Use this dedicated browser profile to establish a usable WeChat reader session. "
            "After the target article can be opened in this browser, press Enter here."
        )
        input()
        storage_state = context.storage_state()
        context.close()
        has_session = self.validate_session(runtime, storage_state)
        return (
            SessionStatus(
                platform=self.platform,
                is_available=has_session,
                updated_at=datetime.now(timezone.utc),
            ),
            storage_state if has_session else None,
        )

    def validate_session(self, runtime, storage_state: dict) -> bool:
        if not storage_state:
            return False
        cookies = storage_state.get("cookies") or []
        return len(cookies) > 0

    def fetch(self, runtime, url: str, storage_state: dict) -> FetchResult:
        context = runtime.new_context(storage_state=storage_state)
        try:
            return self.fetch_with_context(context, url)
        finally:
            context.close()

    def fetch_with_context(self, context, url: str) -> FetchResult:
        canonical_url = canonicalize_url(url)
        page = context.new_page()
        try:
            page.goto(canonical_url, wait_until="domcontentloaded")
            html = page.content()
            asset = self.extractor.from_html(page.url or canonical_url, html)
            if not asset.content_text:
                return FetchResult(
                    success=False,
                    status=FetchStatus.FAILED.value,
                    platform=self.platform,
                    url=canonical_url,
                    error_code="extraction_failed",
                    error_message="Wechat article body could not be extracted.",
                )
            return FetchResult(
                success=True,
                status=FetchStatus.OK.value,
                platform=self.platform,
                url=canonical_url,
                content=asset,
            )
        finally:
            page.close()
