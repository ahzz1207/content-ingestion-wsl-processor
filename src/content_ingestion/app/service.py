from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from typing import Iterable

from content_ingestion.core.config import Settings
from content_ingestion.core.enums import FetchStatus
from content_ingestion.core.exceptions import UnsupportedSourceError
from content_ingestion.core.models import ContentAsset, EvidenceSegment, FetchResult, SessionStatus
from content_ingestion.inbox.processor import JobProcessor
from content_ingestion.inbox.protocol import JobPaths, ensure_shared_inbox, inspect_job, iter_incoming_jobs
from content_ingestion.inbox.watcher import InboxWatcher
from content_ingestion.normalize.markdown import render_markdown
from content_ingestion.pipeline.llm_pipeline import analyze_asset, openai_sdk_available
from content_ingestion.pipeline.media_pipeline import command_available
from content_ingestion.session.browser_runtime import BrowserRuntime
from content_ingestion.session.session_service import SessionService
from content_ingestion.sources.registry import ConnectorRegistry
from content_ingestion.storage.artifact_store import ArtifactStore


class IngestionService:
    def __init__(
        self,
        *,
        settings: Settings,
        connector_registry: ConnectorRegistry,
        session_service: SessionService,
        artifact_store: ArtifactStore,
        openclaw_adapter,
    ) -> None:
        self.settings = settings
        self.connector_registry = connector_registry
        self.session_service = session_service
        self.artifact_store = artifact_store
        self.openclaw_adapter = openclaw_adapter

    def login(
        self,
        platform: str,
        start_url: str | None = None,
        profile_dir: Path | None = None,
        browser_channel: str | None = None,
    ) -> SessionStatus:
        connector = self.connector_registry.get_by_platform(platform)
        target_profile_dir = profile_dir or (self.settings.profiles_dir / platform)
        with BrowserRuntime(
            headless=False,
            timeout_ms=self.settings.browser_timeout_ms,
            user_agent=self.settings.user_agent,
            browser_channel=browser_channel,
        ) as runtime:
            status, storage_state = connector.login(
                runtime,
                profile_dir=target_profile_dir,
                start_url=start_url,
            )
            if status.is_available and storage_state:
                self.session_service.save(platform, storage_state)
            return status

    def get_session_status(self, platform: str) -> SessionStatus:
        return self.session_service.get_status(platform)

    def clear_session(self, platform: str) -> None:
        self.session_service.clear(platform)

    def fetch(
        self,
        url: str,
        output_dir: Path | None = None,
        profile_dir: Path | None = None,
        browser_channel: str | None = None,
    ) -> FetchResult:
        connector = self.connector_registry.resolve(url)
        if profile_dir:
            with BrowserRuntime(
                headless=self.settings.headless,
                timeout_ms=self.settings.browser_timeout_ms,
                user_agent=self.settings.user_agent,
                browser_channel=browser_channel,
            ) as runtime:
                context = runtime.launch_persistent_context(profile_dir)
                try:
                    result = connector.fetch_with_context(context, url)
                finally:
                    context.close()
            if result.content:
                result.content.content_markdown = render_markdown(result.content)
                self.artifact_store.write(result, output_dir=output_dir)
            return result

        storage_state = self.session_service.load(connector.platform)
        if not storage_state:
            return FetchResult(
                success=False,
                status=FetchStatus.AUTH_REQUIRED.value,
                platform=connector.platform,
                url=url,
                error_code="session_required",
                error_message=f"Session required for platform: {connector.platform}",
            )

        with BrowserRuntime(
            headless=self.settings.headless,
            timeout_ms=self.settings.browser_timeout_ms,
            user_agent=self.settings.user_agent,
            browser_channel=browser_channel,
        ) as runtime:
            if not connector.validate_session(runtime, storage_state):
                return FetchResult(
                    success=False,
                    status=FetchStatus.AUTH_REQUIRED.value,
                    platform=connector.platform,
                    url=url,
                    error_code="session_expired",
                    error_message=f"Session expired or invalid for platform: {connector.platform}",
                )
            result = connector.fetch(runtime, url, storage_state)

        if result.content:
            result.content.content_markdown = render_markdown(result.content)
            self.artifact_store.write(result, output_dir=output_dir)
        return result

    def ingest(
        self,
        url: str,
        profile_dir: Path | None = None,
        browser_channel: str | None = None,
    ) -> str:
        result = self.fetch(url, profile_dir=profile_dir, browser_channel=browser_channel)
        if not result.content:
            raise UnsupportedSourceError(result.error_message or f"Unable to ingest URL: {url}")
        return self.openclaw_adapter.ingest(result.content)

    def process_job(self, job_dir: Path) -> Path:
        processor = JobProcessor()
        return processor.process(job_dir)

    def validate_job(self, job_dir: Path) -> dict[str, object]:
        if job_dir.parent.name not in {"incoming", "processing", "processed", "failed"}:
            raise ValueError(f"Unsupported job directory location: {job_dir}")
        job = JobPaths(shared_root=job_dir.parents[1], stage_dir=job_dir.parent, job_id=job_dir.name)
        result = inspect_job(job)
        return {
            "job_id": result.job_id,
            "job_dir": str(result.job_dir),
            "is_valid": result.is_valid,
            "payload_filename": result.payload_filename,
            "content_type": result.content_type,
            "source_url": result.source_url,
            "errors": result.errors or [],
        }

    def validate_inbox(self, shared_root: Path) -> list[dict[str, object]]:
        ensure_shared_inbox(shared_root)
        results = []
        for job in iter_incoming_jobs(shared_root):
            inspected = inspect_job(job)
            results.append(
                {
                    "job_id": inspected.job_id,
                    "job_dir": str(inspected.job_dir),
                    "is_valid": inspected.is_valid,
                    "payload_filename": inspected.payload_filename,
                    "content_type": inspected.content_type,
                    "source_url": inspected.source_url,
                    "errors": inspected.errors or [],
                }
            )
        return results

    def watch_inbox(
        self,
        shared_root: Path,
        *,
        once: bool = False,
        interval_seconds: float = 5.0,
    ) -> list[Path]:
        ensure_shared_inbox(shared_root)
        watcher = InboxWatcher(shared_root, JobProcessor())
        if once:
            return watcher.scan_once()
        try:
            watcher.watch(interval_seconds=interval_seconds)
        except KeyboardInterrupt:
            return []
        return []

    def llm_smoke(self, text: str | None = None) -> dict[str, object]:
        smoke_text = (text or "This is a smoke test paragraph for structured evidence-grounded analysis.").strip()
        smoke_dir = self.settings.cache_dir / "llm_smoke" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        smoke_dir.mkdir(parents=True, exist_ok=True)
        evidence_id = f"smoke-evidence-{uuid4().hex[:8]}"
        asset = ContentAsset(
            source_platform="smoke",
            source_url="about:llm-smoke",
            canonical_url="about:llm-smoke",
            content_shape="article",
            title="LLM Smoke Test",
            author="system",
            content_text=smoke_text,
            content_markdown=smoke_text,
            evidence_segments=[
                EvidenceSegment(
                    id=evidence_id,
                    kind="text_block",
                    text=smoke_text,
                    source="smoke/input",
                )
            ],
        )
        result = analyze_asset(job_dir=smoke_dir, asset=asset, settings=self.settings)
        structured_result = result.structured_result
        return {
            "status": result.status,
            "provider": self.settings.llm_provider,
            "analysis_model": result.analysis_model,
            "multimodal_model": result.multimodal_model,
            "summary": result.summary,
            "key_point_count": len(result.key_points),
            "analysis_item_count": len(result.analysis_items),
            "verification_item_count": len(result.verification_items),
            "structured_result_available": structured_result is not None,
            "output_path": None if result.output_path is None else str(smoke_dir / Path(result.output_path)),
            "warnings": result.warnings,
        }

    def doctor(self) -> Iterable[str]:
        report = [
            f"project_root={self.settings.project_root}",
            f"sessions_dir={self.settings.sessions_dir}",
            f"profiles_dir={self.settings.profiles_dir}",
            f"output_dir={self.settings.output_dir}",
            f"shared_inbox_root={self.settings.shared_inbox_root}",
            f"shared_inbox_exists={self.settings.shared_inbox_root.exists()}",
            f"registered_connectors={','.join(self.connector_registry.platforms())}",
            f"ffmpeg_available={command_available(self.settings.ffmpeg_command, fallback='ffmpeg')}",
            f"whisper_available={command_available(self.settings.whisper_command, fallback='whisper')}",
            f"whisper_model={self.settings.whisper_model}",
            f"openai_sdk_available={openai_sdk_available()}",
            f"llm_provider={self.settings.llm_provider}",
            f"openai_api_key_present={bool(self.settings.openai_api_key)}",
            f"openai_base_url={self.settings.openai_base_url}",
            f"analysis_model={self.settings.analysis_model}",
            f"multimodal_model={self.settings.multimodal_model}",
        ]
        try:
            import playwright  # noqa: F401

            report.append("playwright=ok")
        except ImportError:
            report.append("playwright=missing")
        return report
