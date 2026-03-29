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
    METADATA_FILENAME,
    NORMALIZED_JSON_FILENAME,
    NORMALIZED_MD_FILENAME,
    PIPELINE_FILENAME,
    READY_FILENAME,
    STATUS_FILENAME,
    find_payload_file,
    get_processing_job,
    load_capture_manifest,
    validate_job,
)
from content_ingestion.normalize.markdown import render_markdown
from content_ingestion.pipeline.llm_pipeline import analyze_asset
from content_ingestion.pipeline.media_pipeline import process_media_asset
from content_ingestion.raw import parse_payload

logger = logging.getLogger(__name__)

REQUIRED_OUTPUT_FILES = (
    NORMALIZED_JSON_FILENAME,
    NORMALIZED_MD_FILENAME,
    PIPELINE_FILENAME,
    STATUS_FILENAME,
)


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
            # All processing and file writes happen while still in processing/
            self._write_success_outputs(
                target_dir=job.job_dir,
                asset=asset,
                metadata=metadata,
                payload_path=payload_path,
                capture_manifest=capture_manifest,
                started_at=started_at,
            )
            # Verify all required outputs exist before leaving processing/
            self._verify_required_outputs(job.job_dir)
            # Two-step atomic handoff: processing/ -> finalizing/ -> processed/
            finalizing_dir = self._move_job(job.job_dir, job.finalizing_dir)
            target_dir = self._move_job(finalizing_dir, job.processed_dir)
            return target_dir
        except Exception as exc:
            return self._handle_failure(job, exc, started_at)

    def _move_job(self, source_dir: Path, target_dir: Path) -> Path:
        if target_dir.exists():
            raise JobProtocolError(f"Target directory already exists: {target_dir}")
        return Path(shutil.move(str(source_dir), str(target_dir)))

    def _verify_required_outputs(self, job_dir: Path) -> None:
        missing = [f for f in REQUIRED_OUTPUT_FILES if not (job_dir / f).exists()]
        if missing:
            raise JobProtocolError(
                "Required output files missing after processing: " + ", ".join(missing)
            )

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
        asset.structured_result = llm_analysis.structured_result
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
                "result": self._serialize_structured_result(asset.structured_result, asset.evidence_segments),
                "analysis_items": asset.analysis_items,
                "verification_items": self._serialize_verification_items(asset.verification_items, asset.evidence_segments),
                "synthesis": asset.synthesis,
                "language": asset.language,
                "blocks": [self._serialize_block(block) for block in asset.blocks],
                "attachments": [self._serialize_attachment(attachment) for attachment in asset.attachments],
                "evidence_segments": [self._serialize_evidence_segment(segment) for segment in asset.evidence_segments],
                "evidence_index": self._build_evidence_index(asset.evidence_segments),
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
            "llm_provider": llm_analysis.provider,
            "llm_skip_reason": llm_analysis.skip_reason,
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
            "llm_provider": llm_analysis.provider,
            "llm_skip_reason": llm_analysis.skip_reason,
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
            "provider": llm_analysis.provider,
            "base_url": llm_analysis.base_url,
            "analysis_model": llm_analysis.analysis_model,
            "multimodal_model": llm_analysis.multimodal_model,
            "schema_mode": llm_analysis.schema_mode,
            "content_policy_id": llm_analysis.content_policy_id,
            "supported_input_modalities": llm_analysis.supported_input_modalities,
            "text_input_modality": llm_analysis.text_input_modality,
            "multimodal_input_modality": llm_analysis.multimodal_input_modality,
            "task_intent": llm_analysis.task_intent,
            "skip_reason": llm_analysis.skip_reason,
            "request_artifacts": llm_analysis.request_artifacts,
            "summary_available": bool(llm_analysis.summary),
            "key_point_count": len(llm_analysis.key_points),
            "analysis_item_count": len(llm_analysis.analysis_items),
            "verification_item_count": len(llm_analysis.verification_items),
            "structured_result_available": llm_analysis.structured_result is not None,
            "output_path": llm_analysis.output_path,
            "warnings": llm_analysis.warnings,
            "handshake": {
                "provider": llm_analysis.provider,
                "base_url": llm_analysis.base_url,
                "analysis_model": llm_analysis.analysis_model,
                "multimodal_model": llm_analysis.multimodal_model,
                "schema_mode": llm_analysis.schema_mode,
                "content_policy_id": llm_analysis.content_policy_id,
                "supported_input_modalities": llm_analysis.supported_input_modalities,
                "text_input_modality": llm_analysis.text_input_modality,
                "multimodal_input_modality": llm_analysis.multimodal_input_modality,
                "task_intent": llm_analysis.task_intent,
                "skip_reason": llm_analysis.skip_reason,
                "request_artifacts": llm_analysis.request_artifacts,
            },
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

    def _serialize_structured_result(self, result, evidence_segments) -> dict[str, Any] | None:
        if result is None:
            return None
        evidence_index = {segment.id: segment for segment in evidence_segments}
        summary_payload = (
            None
            if result.summary is None
            else {
                "id": "summary-primary",
                "headline": result.summary.headline,
                "short_text": result.summary.short_text,
                "display": self._build_display_payload(
                    kind="summary",
                    priority=0,
                    compact_text=result.summary.short_text,
                    label=result.summary.headline,
                    tone="hero",
                ),
            }
        )
        key_points_payload = [
            {
                "id": item.id,
                "title": item.title,
                "details": item.details,
                "evidence_segment_ids": item.evidence_segment_ids,
                "resolved_evidence": self._resolve_evidence_refs(item.evidence_segment_ids, evidence_index),
                "display": self._build_display_payload(
                    kind="key_point",
                    priority=100 + index,
                    compact_text=f"{item.title}: {item.details}",
                    label=item.title,
                    tone="accent",
                ),
            }
            for index, item in enumerate(result.key_points, start=1)
        ]
        analysis_items_payload = [
            {
                "id": item.id,
                "kind": item.kind,
                "statement": item.statement,
                "evidence_segment_ids": item.evidence_segment_ids,
                "resolved_evidence": self._resolve_evidence_refs(item.evidence_segment_ids, evidence_index),
                "confidence": item.confidence,
                "display": self._build_display_payload(
                    kind="analysis_item",
                    priority=200 + index,
                    compact_text=item.statement,
                    label=item.kind.replace("_", " "),
                    tone="neutral",
                ),
            }
            for index, item in enumerate(result.analysis_items, start=1)
        ]
        verification_items_payload = [
            {
                "id": item.id,
                "claim": item.claim,
                "status": item.status,
                "evidence_segment_ids": item.evidence_segment_ids,
                "resolved_evidence": self._resolve_evidence_refs(item.evidence_segment_ids, evidence_index),
                "rationale": item.rationale,
                "confidence": item.confidence,
                "display": self._build_display_payload(
                    kind="verification_item",
                    priority=self._verification_priority(item.status, index),
                    compact_text=f"{item.claim} [{item.status}]",
                    label=item.status,
                    tone=self._verification_tone(item.status),
                ),
            }
            for index, item in enumerate(result.verification_items, start=1)
        ]
        synthesis_payload = (
            None
            if result.synthesis is None
            else {
                "id": "synthesis-primary",
                "final_answer": result.synthesis.final_answer,
                "what_is_new": result.synthesis.what_is_new,
                "tensions": result.synthesis.tensions,
                "next_steps": result.synthesis.next_steps,
                "open_questions": result.synthesis.open_questions,
                "display": self._build_display_payload(
                    kind="synthesis",
                    priority=400,
                    compact_text=result.synthesis.final_answer,
                    label="Final answer",
                    tone="hero",
                ),
            }
        )
        visual_findings_payload = [
            {
                "id": item.id,
                "finding": item.finding,
                "evidence_frame_paths": item.evidence_frame_paths,
            }
            for item in (result.visual_findings if hasattr(result, "visual_findings") else [])
        ]
        warnings_payload = [
            {
                "id": f"warning-{index}",
                "code": item.code,
                "severity": item.severity,
                "message": item.message,
                "related_refs": [
                    {
                        "kind": ref.kind,
                        "id": ref.id,
                        "role": ref.role,
                    }
                    for ref in item.related_refs
                ],
                "display": self._build_display_payload(
                    kind="warning",
                    priority=self._warning_priority(item.severity, index),
                    compact_text=item.message,
                    label=item.severity,
                    tone=self._warning_tone(item.severity),
                ),
            }
            for index, item in enumerate(result.warnings, start=1)
        ]
        evidence_backlinks = self._build_evidence_backlinks(
            key_points=key_points_payload,
            analysis_items=analysis_items_payload,
            verification_items=verification_items_payload,
        )
        result_index = self._build_result_index(
            summary_payload=summary_payload,
            key_points=key_points_payload,
            analysis_items=analysis_items_payload,
            verification_items=verification_items_payload,
            synthesis_payload=synthesis_payload,
            warnings=warnings_payload,
        )
        chapter_map_payload = [
            {
                "id": ch.id,
                "title": ch.title,
                "role": ch.role,
                "summary": ch.summary,
                "block_ids": ch.block_ids,
                "weight": ch.weight,
            }
            for ch in (result.chapter_map if hasattr(result, "chapter_map") else [])
        ]
        return {
            "content_kind": result.content_kind,
            "author_stance": result.author_stance,
            "summary": summary_payload,
            "key_points": key_points_payload,
            "analysis_items": analysis_items_payload,
            "visual_findings": visual_findings_payload,
            "verification_items": verification_items_payload,
            "synthesis": synthesis_payload,
            "warnings": warnings_payload,
            "chapter_map": chapter_map_payload,
            "evidence_backlinks": evidence_backlinks,
            "result_index": result_index,
            "display_plan": self._build_display_plan(
                summary_payload=summary_payload,
                key_points=key_points_payload,
                analysis_items=analysis_items_payload,
                verification_items=verification_items_payload,
                synthesis_payload=synthesis_payload,
                warnings=warnings_payload,
            ),
        }

    def _build_evidence_index(self, segments) -> dict[str, Any]:
        return {
            segment.id: {
                "kind": segment.kind,
                "source": segment.source,
                "start_ms": segment.start_ms,
                "end_ms": segment.end_ms,
                "preview_text": segment.text[:280],
            }
            for segment in segments
        }

    def _build_evidence_backlinks(
        self,
        *,
        key_points: list[dict[str, Any]],
        analysis_items: list[dict[str, Any]],
        verification_items: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        backlinks: dict[str, list[dict[str, Any]]] = {}
        for item in key_points:
            self._append_evidence_backlink(
                backlinks,
                item=item,
                item_kind="key_point",
                label=item.get("title", ""),
            )
        for item in analysis_items:
            self._append_evidence_backlink(
                backlinks,
                item=item,
                item_kind="analysis_item",
                label=item.get("statement", ""),
            )
        for item in verification_items:
            self._append_evidence_backlink(
                backlinks,
                item=item,
                item_kind="verification_item",
                label=item.get("claim", ""),
            )
        return backlinks

    def _append_evidence_backlink(
        self,
        backlinks: dict[str, list[dict[str, Any]]],
        *,
        item: dict[str, Any],
        item_kind: str,
        label: str,
    ) -> None:
        evidence_ids = item.get("evidence_segment_ids") or []
        display = item.get("display") or {}
        for evidence_id in evidence_ids:
            backlinks.setdefault(evidence_id, []).append(
                {
                    "kind": item_kind,
                    "id": item["id"],
                    "label": str(label).strip(),
                    "priority": display.get("priority"),
                }
            )

    def _build_result_index(
        self,
        *,
        summary_payload: dict[str, Any] | None,
        key_points: list[dict[str, Any]],
        analysis_items: list[dict[str, Any]],
        verification_items: list[dict[str, Any]],
        synthesis_payload: dict[str, Any] | None,
        warnings: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        if summary_payload is not None:
            index[summary_payload["id"]] = self._build_result_index_entry(
                item=summary_payload,
                section="summary",
                kind="summary",
                label=summary_payload.get("headline", ""),
                evidence_segment_ids=[],
            )
        for item in key_points:
            index[item["id"]] = self._build_result_index_entry(
                item=item,
                section="key_points",
                kind="key_point",
                label=item.get("title", ""),
                evidence_segment_ids=item.get("evidence_segment_ids", []),
            )
        for item in analysis_items:
            index[item["id"]] = self._build_result_index_entry(
                item=item,
                section="analysis_items",
                kind="analysis_item",
                label=item.get("statement", ""),
                evidence_segment_ids=item.get("evidence_segment_ids", []),
            )
        for item in verification_items:
            index[item["id"]] = self._build_result_index_entry(
                item=item,
                section="verification_items",
                kind="verification_item",
                label=item.get("claim", ""),
                evidence_segment_ids=item.get("evidence_segment_ids", []),
            )
        if synthesis_payload is not None:
            index[synthesis_payload["id"]] = self._build_result_index_entry(
                item=synthesis_payload,
                section="synthesis",
                kind="synthesis",
                label=synthesis_payload.get("final_answer", ""),
                evidence_segment_ids=[],
            )
        for item in warnings:
            index[item["id"]] = self._build_result_index_entry(
                item=item,
                section="warnings",
                kind="warning",
                label=item.get("message", ""),
                evidence_segment_ids=[
                    ref["id"]
                    for ref in item.get("related_refs", [])
                    if ref.get("kind") == "evidence_segment"
                ],
            )
        return index

    def _build_result_index_entry(
        self,
        *,
        item: dict[str, Any],
        section: str,
        kind: str,
        label: str,
        evidence_segment_ids: list[str],
    ) -> dict[str, Any]:
        display = item.get("display") or {}
        return {
            "section": section,
            "kind": kind,
            "label": str(label).strip(),
            "priority": display.get("priority"),
            "tone": display.get("tone"),
            "evidence_segment_ids": evidence_segment_ids,
        }

    def _serialize_verification_items(self, items, evidence_segments) -> list[dict[str, Any]]:
        evidence_index = {segment.id: segment for segment in evidence_segments}
        serialized: list[dict[str, Any]] = []
        for item in items:
            payload = dict(item)
            evidence_ids = payload.get("evidence_segment_ids")
            if isinstance(evidence_ids, list):
                payload["resolved_evidence"] = self._resolve_evidence_refs(evidence_ids, evidence_index)
            else:
                payload["resolved_evidence"] = []
            serialized.append(payload)
        return serialized

    def _resolve_evidence_refs(self, evidence_ids, evidence_index) -> list[dict[str, Any]]:
        resolved: list[dict[str, Any]] = []
        for evidence_id in evidence_ids:
            segment = evidence_index.get(evidence_id)
            if segment is None:
                continue
            resolved.append(
                {
                    "id": segment.id,
                    "kind": segment.kind,
                    "source": segment.source,
                    "start_ms": segment.start_ms,
                    "end_ms": segment.end_ms,
                    "preview_text": segment.text[:280],
                }
            )
        return resolved

    def _build_display_payload(
        self,
        *,
        kind: str,
        priority: int,
        compact_text: str,
        label: str,
        tone: str,
    ) -> dict[str, Any]:
        normalized = " ".join(compact_text.split())
        return {
            "kind": kind,
            "priority": priority,
            "label": label.strip(),
            "tone": tone,
            "compact_text": normalized[:160],
        }

    def _build_display_plan(
        self,
        *,
        summary_payload: dict[str, Any] | None,
        key_points: list[dict[str, Any]],
        analysis_items: list[dict[str, Any]],
        verification_items: list[dict[str, Any]],
        synthesis_payload: dict[str, Any] | None,
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "version": 1,
            "sections": [
                self._build_section_plan(
                    section_id="summary",
                    title="Summary",
                    priority=0,
                    default_view="hero",
                    default_expanded=True,
                    item_count=1 if summary_payload else 0,
                    item_ids=[] if summary_payload is None else [summary_payload["id"]],
                ),
                self._build_section_plan(
                    section_id="key_points",
                    title="Key Points",
                    priority=100,
                    default_view="cards",
                    default_expanded=True,
                    item_count=len(key_points),
                    item_ids=[item["id"] for item in key_points],
                ),
                self._build_section_plan(
                    section_id="analysis_items",
                    title="Analysis",
                    priority=200,
                    default_view="stack",
                    default_expanded=False,
                    item_count=len(analysis_items),
                    item_ids=[item["id"] for item in analysis_items],
                ),
                self._build_section_plan(
                    section_id="verification_items",
                    title="Verification",
                    priority=300,
                    default_view="evidence_strip",
                    default_expanded=False,
                    item_count=len(verification_items),
                    item_ids=[item["id"] for item in verification_items],
                    pinned_item_ids=[
                        item["id"]
                        for item in verification_items
                        if item.get("status") in {"unsupported", "partial"}
                    ],
                ),
                self._build_section_plan(
                    section_id="synthesis",
                    title="Takeaway",
                    priority=400,
                    default_view="spotlight",
                    default_expanded=True,
                    item_count=1 if synthesis_payload else 0,
                    item_ids=[] if synthesis_payload is None else [synthesis_payload["id"]],
                ),
                self._build_section_plan(
                    section_id="warnings",
                    title="Warnings",
                    priority=500,
                    default_view="compact_list",
                    default_expanded=bool(warnings),
                    item_count=len(warnings),
                    item_ids=[item["id"] for item in warnings],
                ),
            ],
        }

    def _build_section_plan(
        self,
        *,
        section_id: str,
        title: str,
        priority: int,
        default_view: str,
        default_expanded: bool,
        item_count: int,
        item_ids: list[str],
        pinned_item_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": section_id,
            "title": title,
            "priority": priority,
            "default_view": default_view,
            "default_expanded": default_expanded,
            "item_count": item_count,
            "item_ids": item_ids,
        }
        if pinned_item_ids:
            payload["pinned_item_ids"] = pinned_item_ids
        return payload

    def _verification_priority(self, status: str, index: int) -> int:
        base = {
            "unsupported": 300,
            "partial": 320,
            "unclear": 340,
            "supported": 360,
        }.get(status, 380)
        return base + index

    def _verification_tone(self, status: str) -> str:
        return {
            "unsupported": "alert",
            "partial": "caution",
            "unclear": "muted",
            "supported": "positive",
        }.get(status, "neutral")

    def _warning_priority(self, severity: str, index: int) -> int:
        base = {
            "error": 500,
            "warn": 520,
            "info": 540,
        }.get(severity, 560)
        return base + index

    def _warning_tone(self, severity: str) -> str:
        return {
            "error": "alert",
            "warn": "caution",
            "info": "muted",
        }.get(severity, "neutral")

    def _error_code(self, exc: Exception) -> str:
        if isinstance(exc, JobProtocolError):
            return "job_protocol_error"
        return "processing_failed"

    def _cleanup_transient_files(self, target_dir: Path) -> None:
        ready_path = target_dir / READY_FILENAME
        if ready_path.exists():
            ready_path.unlink()

    def _handle_failure(self, job, exc: Exception, started_at: datetime) -> Path:
        # Determine the actual location of the job first — it may have been moved
        # to finalizing/ before the failure occurred.
        if job.job_dir.exists():
            source_dir = job.job_dir
        elif job.finalizing_dir.exists():
            logger.warning(
                "job %s found in finalizing/ during failure handling — rescuing to failed/",
                job.job_id,
            )
            source_dir = job.finalizing_dir
        else:
            logger.error(
                "job %s not found in processing/ or finalizing/ during failure handling",
                job.job_id,
            )
            raise exc
        # Read metadata from the actual source directory.
        metadata_path = source_dir / METADATA_FILENAME
        payload_path = find_payload_file(source_dir)
        payload_filename = payload_path.name if payload_path else None
        content_type = None
        source_url = None
        try:
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                content_type = metadata.get("content_type")
                source_url = metadata.get("source_url")
        except Exception:
            logger.warning("failed to read metadata during failure handling for job %s", job.job_id)
        try:
            target_dir = self._move_job(source_dir, job.failed_dir)
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
