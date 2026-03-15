class BrowserRuntime:
    def __init__(
        self,
        *,
        headless: bool,
        timeout_ms: int,
        user_agent: str,
        browser_channel: str | None = None,
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.user_agent = user_agent
        self.browser_channel = browser_channel
        self.playwright = None
        self.browser = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self.playwright = sync_playwright().start()
        launch_kwargs = {"headless": self.headless}
        if self.browser_channel:
            launch_kwargs["channel"] = self.browser_channel
        self.browser = self.playwright.chromium.launch(**launch_kwargs)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def new_context(self, storage_state: dict | None = None):
        context = self.browser.new_context(
            storage_state=storage_state,
            user_agent=self.user_agent,
            viewport={"width": 1440, "height": 960},
        )
        context.set_default_timeout(self.timeout_ms)
        return context

    def launch_persistent_context(self, user_data_dir):
        launch_kwargs = {
            "user_data_dir": str(user_data_dir),
            "headless": self.headless,
            "user_agent": self.user_agent,
            "viewport": {"width": 1440, "height": 960},
        }
        if self.browser_channel:
            launch_kwargs["channel"] = self.browser_channel
        context = self.playwright.chromium.launch_persistent_context(
            **launch_kwargs,
        )
        context.set_default_timeout(self.timeout_ms)
        return context
