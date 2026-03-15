from dataclasses import dataclass

from content_ingestion.core.config import Settings, load_settings
from content_ingestion.pipeline.openclaw_adapter import OpenClawAdapter
from content_ingestion.session.session_service import SessionService
from content_ingestion.session.session_store import SessionStore
from content_ingestion.sources.registry import ConnectorRegistry
from content_ingestion.storage.artifact_store import ArtifactStore

from .service import IngestionService


@dataclass(slots=True)
class AppContainer:
    settings: Settings
    service: IngestionService


def build_app() -> AppContainer:
    settings = load_settings()
    session_store = SessionStore(settings.sessions_dir)
    session_service = SessionService(session_store)
    artifact_store = ArtifactStore(settings.output_dir)
    connector_registry = ConnectorRegistry.default()
    openclaw_adapter = OpenClawAdapter()
    service = IngestionService(
        settings=settings,
        connector_registry=connector_registry,
        session_service=session_service,
        artifact_store=artifact_store,
        openclaw_adapter=openclaw_adapter,
    )
    return AppContainer(settings=settings, service=service)
