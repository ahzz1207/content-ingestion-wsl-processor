from abc import ABC, abstractmethod

from content_ingestion.core.models import FetchResult, SessionStatus


class BaseConnector(ABC):
    platform: str

    @abstractmethod
    def supports(self, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def login(self, runtime, *, profile_dir=None, start_url: str | None = None) -> tuple[SessionStatus, dict | None]:
        raise NotImplementedError

    @abstractmethod
    def validate_session(self, runtime, storage_state: dict) -> bool:
        raise NotImplementedError

    @abstractmethod
    def fetch(self, runtime, url: str, storage_state: dict) -> FetchResult:
        raise NotImplementedError

    @abstractmethod
    def fetch_with_context(self, context, url: str) -> FetchResult:
        raise NotImplementedError
