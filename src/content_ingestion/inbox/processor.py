import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from content_ingestion import __version__
from content_ingestion.core.config import Settings, load_settings
from content_ingestion.core.models import ContentAsset
from content_ingestion.inbox.protocol import (
    CAPTURE_MANIFEST_FILENAME,
    ERROR_FILENAME,
    JobProtocolError,
    NORMALIZED_JSON_FILENAME,
    NORMALIZED_MD_FILENAME,
    PIPELINE_FILENAME,
    READY_FILENAME,
    STATUS_FILENAME,
    get_processing_job,
    load_capture_manifest,
    validate_job,
)
from content_ingestion.normalize.markdown import render_markdown
from content_ingestion.pipeline.llm_pipeline import analyze_asset
from content_ingestion.pipeline.media_pipeline import process_media_asset
from content_ingestion.raw import parse_payload

logger = logging.getLogger(__name__)


class JobProcessor:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or load_settings()

    def process(self, job_dir: Path) -> Path:
        job = get_processing_job(job_dir)
        started_at = datetime.now(timezone.utc)
        try:
            metadata = validate_job(job)
            payload_path = job.payload_path
            if payload_path is None:
                raise JobProtocolError("No supported payload file found.")
            capture_manifest = None
            if job.capture_manifest_path.exists():
                capture_manifest = load_capture_manifest(
                    job.capture_manifest_path,
                    expected_payload_filename=payload_path.name,
                )
            asset = parse_payload(payload_path, metadata, capture_manifest=capture_manifest)
            if not asset.content_markdown:
                asset.content_markdown = render_markdown(asset)
            target_dir = self._move_job(job.job_dir, job.processed_dir)
            self._write_success_outputs(
                target_dir=target_dir,
                asset=asset,
                metadata=metadata,
                payload_path=payload_path,
                capture_manifest=capture_manifest,
                started_at=started_at,
            )
            return target_dir
        except Exception as exc:
            return self._handle_failure(job, exc, started_at)

    def _move_job(self, source_dir: Path, target_dir: Path) -> Path:
        if target_dir.exists():
            raise JobProtocolError(f"Target directory already exists: {target_dir}")
        return Path(shutil.move(str(source_dir), str(target_dir)))

    def _write_success_outputs(
        self,
        *,
        target_dir: Path,
        asset: ContentAsset,
        metadata: dict[str, object],
        payload_path: Path,
        capture_manifest: dict[str, Any] | None,
        started_at: datetime,
    ) -> None:
        self._cleanup_transient_files(target_dir)
        processed_at = datetime.now(timezone.utc)
        artifact_count = len(capture_manifest.get("artifacts", [])) if capture_manifest else 0
        capture_validation = self._load_capture_validation_summary(target_dir, capture_manifest)
        media_processing = process_media_asset(job_dir=target_dir, asset=asset, settings=self.settings)
        llm_analysis = analyze_asset(job_dir=target_dir, asset=asset, settings=self.settings)
        asset.summary = llm_analysis.summary or asset.summary
        asset.analysis_items = llm_analysis.analysis_items
        asset.verification_items = llm_analysis.verification_items
        asset.synthesis = llm_analysis.synthesis
        (target_dir / NORMALIZED_MD_FILENAME).write_text(
            asset.content_markdown or "",
            encoding="utf-8",
        )
        normalized_payload = {
            "job_id": metadata["job_id"],
            "status": "success",
            "content_type": metadata["content_type"],
            "asset": {
                "source_platform": asset.source_platform,
                "source_url": asset.source_url,
                "canonical_url": asset.canonical_url,
                "content_shape": asset.content_shape,
                "title": asset.title,
                "author": asset.author,
                "published_at": asset.published_at.isoformat() if asset.published_at else None,
                "content_text": asset.content_text,
                "content_markdown": asset.content_markdown,
                "transcript_text": asset.transcript_text,
                "analysis_text": asset.analysis_text,
                "summary": asset.summary,
                "analysis_items": asset.analysis_items,
                "verification_items": asset.verification_items,
                "synthesis": asset.synthesis,
                "language": asset.language,
                "blocks": [self._serialize_block(block) for block in asset.blocks],
                "attachments": [self._serialize_attachment(attachment) for attachment in asset.attachments],
                "evidence_segments": [self._serialize_evidence_segment(segment) for segment in asset.evidence_segments],
                "metadata": self._build_asset_metadata(
                    asset,
                    metadata,
                    capture_manifest,
                    capture_validation,
                    media_processing,
                    llm_analysis,
                ),
            },
        }
        (target_dir / NORMALIZED_JSON_FILENAME).write_text(
            json.dumps(normalized_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pipeline = {
            "job_id": metadata["job_id"],
            "status": "success",
            "started_at": started_at.isoformat(),
            "finished_at": processed_at.isoformat(),
            "payload_filename": payload_path.name,
            "content_type": metadata["content_type"],
            "artifact_count": artifact_count,
            "capture_manifest_filename": CAPTURE_MANIFEST_FILENAME if capture_manifest else None,
            "capture_validation_status": capture_validation.get("status") if capture_validation else None,
            "media_processing_status": media_processing.status,
            "llm_processing_status": llm_analysis.status,
            "steps": [
                {"name": "load_metadata", "status": "success"},
                {"name": "load_capture_manifest", "status": "success" if capture_manifest else "skipped"},
                {"name": "load_capture_validation", "status": "success" if capture_validation else "skipped"},
                {"name": "parse_payload", "status": "success"},
                *media_processing.steps,
                *llm_analysis.steps,
                {"name": "write_outputs", "status": "success"},
            ],
        }
        (target_dir / PIPELINE_FILENAME).write_text(
            json.dumps(pipeline, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        status = {
            "job_id": metadata["job_id"],
            "status": "success",
            "stage": "normalized",
            "processor": "wsl-processor",
            "processor_version": __version__,
            "content_type": metadata["content_type"],
            "payload_filename": payload_path.name,
            "source_url": metadata["source_url"],
            "artifact_count": artifact_count,
            "capture_manifest_filename": CAPTURE_MANIFEST_FILENAME if capture_manifest else None,
            "capture_validation_status": capture_validation.get("status") if capture_validation else None,
            "media_processing_status": media_processing.status,
            "llm_processing_status": llm_analysis.status,
            "started_at": started_at.isoformat(),
            "processed_at": processed_at.isoformat(),
        }
        (target_dir / STATUS_FILENAME).write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_failure_outputs(
        self,
        target_dir: Path,
        job_id: str,
        exc: Exception,
        *,
        started_at: datetime,
        payload_filename: str | None = None,
        content_type: str | None = None,
        source_url: str | None = None,
    ) -> None:
        self._cleanup_transient_files(target_dir)
        processed_at = datetime.now(timezone.utc)
        error = {
            "job_id": job_id,
            "stage": "process",
            "error_code": self._error_code(exc),
            "error_message": str(exc),
            "processor": "wsl-processor",
            "processor_version": __version__,
            "payload_filename": payload_filename,
            "content_type": content_type,
            "source_url": source_url,
            "started_at": started_at.isoformat(),
            "failed_at": processed_at.isoformat(),
        }
        (target_dir / ERROR_FILENAME).write_text(
            json.dumps(error, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        status = {
            "job_id": job_id,
            "status": "failed",
            "stage": "process",
            "processor": "wsl-processor",
            "processor_version": __version__,
            "payload_filename": payload_filename,
            "content_type": content_type,
            "source_url": source_url,
            "started_at": started_at.isoformat(),
            "processed_at": processed_at.isoformat(),
        }
        (target_dir / STATUS_FILENAME).write_text(
            json.dumps(status, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_asset_metadata(
        self,
        asset: ContentAsset,
        metadata: dict[str, object],
        capture_manifest: dict[str, Any] | None,
        capture_validation: dict[str, Any] | None,
        media_processing,
        llm_analysis,
    ) -> dict[str, object]:
        normalized_metadata = dict(asset.metadata)
        handoff_context = {
            key: value
            for key in (
                "collector",
                "collected_at",
                "collection_mode",
                "video_download_mode",
                "browser_channel",
                "profile_slug",
                "wait_until",
                "wait_for_selector",
                "wait_for_selector_state",
                "primary_payload_role",
                "content_shape",
                "capture_manifest_filename",
            )
            if (value := metadata.get(key)) not in (None, "")
        }
        if handoff_context:
            normalized_metadata["handoff"] = handoff_context
        if capture_manifest:
            normalized_metadata["capture"] = {
                "content_shape": capture_manifest.get("content_shape") or metadata.get("content_shape"),
                "video_download_mode": metadata.get("video_download_mode"),
                "primary_payload": capture_manifest.get("primary_payload"),
                "artifacts": capture_manifest.get("artifacts", []),
            }
            if capture_validation:
                normalized_metadata["capture"]["validation"] = capture_validation
        normalized_metadata["media_processing"] = {
            "status": media_processing.status,
            "media_kind": media_processing.media_kind,
            "source_attachment_path": media_processing.source_attachment_path,
            "transcript_text_available": bool(media_processing.transcript_text),
            "transcript_segment_count": len(media_processing.transcript_segments),
            "multimodal_frame_paths": media_processing.multimodal_frame_paths,
            "warnings": media_processing.warnings,
        }
        normalized_metadata["llm_processing"] = {
            "status": llm_analysis.status,
            "analysis_model": llm_analysis.analysis_model,
            "multimodal_model": llm_analysis.multimodal_model,
            "summary_available": bool(llm_analysis.summary),
            "analysis_item_count": len(llm_analysis.analysis_items),
            "verification_item_count": len(llm_analysis.verification_items),
            "output_path": llm_analysis.output_path,
            "warnings": llm_analysis.warnings,
        }
        return normalized_metadata

    def _load_capture_validation_summary(
        self,
        target_dir: Path,
        capture_manifest: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        if not capture_manifest:
            return None
        for artifact in capture_manifest.get("artifacts", []):
            if not isinstance(artifact, dict):
                continue
            if artifact.get("role") != "capture_validation":
                continue
            relative_path = artifact.get("path")
            if not isinstance(relative_path, str) or not relative_path:
                continue
            validation_path = target_dir.joinpath(*Path(relative_path).parts)
            if not validation_path.exists():
                continue
            try:
                payload = json.loads(validation_path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("failed to read capture validation artifact: %s", validation_path)
                return None
            summary = payload.get("summary")
            if not isinstance(summary, dict):
                return None
            return {
                "status": summary.get("status"),
                "passed": summary.get("passed"),
                "warned": summary.get("warned"),
                "failed": summary.get("failed"),
                "artifact_path": relative_path,
            }
        return None

    def _serialize_block(self, block) -> dict[str, Any]:
        return {
            "id": block.id,
            "kind": block.kind,
            "text": block.text,
            "heading_level": block.heading_level,
            "source": block.source,
        }

    def _serialize_attachment(self, attachment) -> dict[str, Any]:
        return {
            "id": attachment.id,
            "path": attachment.path,
            "role": attachment.role,
            "media_type": attachment.media_type,
            "kind": attachment.kind,
            "size_bytes": attachment.size_bytes,
            "description": attachment.description,
        }

    def _serialize_evidence_segment(self, segment) -> dict[str, Any]:
        return {
            "id": segment.id,
            "kind": segment.kind,
            "text": segment.text,
            "source": segment.source,
            "start_ms": segment.start_ms,
            "end_ms": segment.end_ms,
        }

    def _error_code(self, exc: Exception) -> str:
        if isinstance(exc, JobProtocolError):
            return "job_protocol_error"
        return "processing_failed"

    def _cleanup_transient_files(self, target_dir: Path) -> None:
        ready_path = target_dir / READY_FILENAME
        if ready_path.exists():
            ready_path.unlink()

    def _handle_failure(self, job, exc: Exception, started_at: datetime) -> Path:
        payload_filename = job.payload_path.name if job.payload_path else None
        content_type = None
        source_url = None
        try:
            if job.metadata_path.exists():
                metadata = json.loads(job.metadata_path.read_text(encoding="utf-8"))
                content_type = metadata.get("content_type")
                source_url = metadata.get("source_url")
        except Exception:
            logger.warning("failed to read metadata during failure handling for job %s", job.job_id)
        try:
            target_dir = self._move_job(job.job_dir, job.failed_dir)
        except Exception as move_exc:
            logger.exception(
                "failed to move job %s into failed/: original=%s move=%s",
                job.job_id,
                exc,
                move_exc,
            )
            raise move_exc from exc

        try:
            self._write_failure_outputs(
                target_dir,
                job.job_id,
                exc,
                started_at=started_at,
                payload_filename=payload_filename,
                content_type=content_type,
                source_url=source_url,
            )
        except Exception as write_exc:
            logger.exception(
                "failed to write failure outputs for job %s: original=%s write=%s",
                job.job_id,
                exc,
                write_exc,
            )
            raise write_exc from exc
        return target_dir
