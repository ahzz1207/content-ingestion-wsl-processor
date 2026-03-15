from content_ingestion.core.exceptions import UnsupportedSourceError
from content_ingestion.sources.base import BaseConnector
from content_ingestion.sources.wechat.connector import WechatConnector


class ConnectorRegistry:
    def __init__(self, connectors: list[BaseConnector]) -> None:
        self._connectors = connectors

    @classmethod
    def default(cls) -> "ConnectorRegistry":
        return cls(connectors=[WechatConnector()])

    def get_by_platform(self, platform: str) -> BaseConnector:
        for connector in self._connectors:
            if connector.platform == platform:
                return connector
        raise UnsupportedSourceError(f"Unsupported platform: {platform}")

    def resolve(self, url: str) -> BaseConnector:
        for connector in self._connectors:
            if connector.supports(url):
                return connector
        raise UnsupportedSourceError(f"Unsupported source URL: {url}")

    def platforms(self) -> list[str]:
        return [connector.platform for connector in self._connectors]
