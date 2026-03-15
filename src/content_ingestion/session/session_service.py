from datetime import datetime, timezone

from content_ingestion.core.models import SessionStatus

from .session_store import SessionStore


class SessionService:
    def __init__(self, store: SessionStore) -> None:
        self.store = store

    def get_status(self, platform: str) -> SessionStatus:
        if not self.store.exists(platform):
            return SessionStatus(platform=platform, is_available=False)
        return SessionStatus(
            platform=platform,
            is_available=True,
            updated_at=datetime.now(timezone.utc),
        )

    def load(self, platform: str) -> dict | None:
        return self.store.load(platform)

    def save(self, platform: str, storage_state: dict) -> None:
        self.store.save(platform, storage_state)

    def clear(self, platform: str) -> None:
        self.store.delete(platform)
