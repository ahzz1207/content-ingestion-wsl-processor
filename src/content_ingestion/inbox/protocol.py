import json
import logging
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from content_ingestion.core.exceptions import ContentIngestionError

INCOMING_DIRNAME = "incoming"
PROCESSING_DIRNAME = "processing"
PROCESSED_DIRNAME = "processed"
FAILED_DIRNAME = "failed"
FINALIZING_DIRNAME = "finalizing"
METADATA_FILENAME = "metadata.json"
READY_FILENAME = "READY"
STATUS_FILENAME = "status.json"
ERROR_FILENAME = "error.json"
PIPELINE_FILENAME = "pipeline.json"
NORMALIZED_JSON_FILENAME = "normalized.json"
NORMALIZED_MD_FILENAME = "normalized.md"
CAPTURE_MANIFEST_FILENAME = "capture_manifest.json"
ATTACHMENTS_DIRNAME = "attachments"
PAYLOAD_FILENAMES = (
    "payload.html", "payload.txt", "payload.md",
    "payload.pdf",
    "payload.png", "payload.jpg", "payload.jpeg", "payload.webp", "payload.gif",
)
REQUIRED_METADATA_FIELDS = ("job_id", "source_url", "collector", "collected_at", "content_type")
logger = logging.getLogger(__name__)


class JobProtocolError(ContentIngestionError):
    """Raised when a job directory does not match the inbox protocol."""


@dataclass(slots=True)
class SharedInboxPaths:
    root: Path
    incoming: Path
    processing: Path
    processed: Path
    failed: Path
    finalizing: Path


@dataclass(slots=True)
class JobPaths:
    shared_root: Path
    stage_dir: Path
    job_id: str

    @property
    def job_dir(self) -> Path:
        return self.stage_dir / self.job_id

    @property
    def metadata_path(self) -> Path:
        return self.job_dir / METADATA_FILENAME

    @property
    def ready_path(self) -> Path:
        return self.job_dir / READY_FILENAME

    @property
    def payload_path(self) -> Path | None:
        return find_payload_file(self.job_dir)

    @property
    def capture_manifest_path(self) -> Path:
        return self.job_dir / CAPTURE_MANIFEST_FILENAME

    @property
    def attachments_dir(self) -> Path:
        return self.job_dir / ATTACHMENTS_DIRNAME

    @property
    def processed_dir(self) -> Path:
        return self.shared_root / PROCESSED_DIRNAME / self.job_id

    @property
    def failed_dir(self) -> Path:
        return self.shared_root / FAILED_DIRNAME / self.job_id

    @property
    def finalizing_dir(self) -> Path:
        return self.shared_root / FINALIZING_DIRNAME / self.job_id


@dataclass(slots=True)
class JobValidationResult:
    job_id: str
    job_dir: Path
    is_valid: bool
    payload_filename: str | None = None
    content_type: str | None = None
    source_url: str | None = None
    errors: list[str] | None = None


def get_shared_inbox_paths(root: Path) -> SharedInboxPaths:
    return SharedInboxPaths(
        root=root,
        incoming=root / INCOMING_DIRNAME,
        processing=root / PROCESSING_DIRNAME,
        processed=root / PROCESSED_DIRNAME,
        failed=root / FAILED_DIRNAME,
        finalizing=root / FINALIZING_DIRNAME,
    )


def ensure_shared_inbox(root: Path) -> SharedInboxPaths:
    paths = get_shared_inbox_paths(root)
    paths.incoming.mkdir(parents=True, exist_ok=True)
    paths.processing.mkdir(parents=True, exist_ok=True)
    paths.processed.mkdir(parents=True, exist_ok=True)
    paths.failed.mkdir(parents=True, exist_ok=True)
    paths.finalizing.mkdir(parents=True, exist_ok=True)
    return paths


def iter_incoming_jobs(root: Path) -> list[JobPaths]:
    paths = ensure_shared_inbox(root)
    jobs = []
    try:
        children = sorted(paths.incoming.iterdir())
    except FileNotFoundError:
        logger.warning("incoming directory disappeared during scan: %s", paths.incoming)
        return jobs
    for child in children:
        if child.is_dir():
            jobs.append(JobPaths(shared_root=root, stage_dir=paths.incoming, job_id=child.name))
    return jobs


def get_processing_job(job_dir: Path) -> JobPaths:
    if job_dir.parent.name != PROCESSING_DIRNAME:
        raise JobProtocolError(f"Job is not in processing/: {job_dir}")
    return JobPaths(shared_root=job_dir.parents[1], stage_dir=job_dir.parent, job_id=job_dir.name)


def find_payload_file(job_dir: Path) -> Path | None:
    for filename in PAYLOAD_FILENAMES:
        candidate = job_dir / filename
        if candidate.exists():
            return candidate
    return None


def is_job_ready(job: JobPaths) -> bool:
    return (
        job.job_dir.is_dir()
        and job.metadata_path.exists()
        and job.ready_path.exists()
        and job.payload_path is not None
    )


def load_metadata(metadata_path: Path) -> dict[str, Any]:
    with metadata_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    missing = [field for field in REQUIRED_METADATA_FIELDS if not data.get(field)]
    if missing:
        raise JobProtocolError(f"metadata.json missing required fields: {', '.join(missing)}")
    return data


def load_capture_manifest(manifest_path: Path, *, expected_payload_filename: str | None = None) -> dict[str, Any]:
    with manifest_path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise JobProtocolError("capture_manifest.json must contain a JSON object")
    primary_payload = data.get("primary_payload")
    if not isinstance(primary_payload, dict):
        raise JobProtocolError("capture_manifest.json missing primary_payload")
    primary_path = primary_payload.get("path")
    if not isinstance(primary_path, str) or not primary_path:
        raise JobProtocolError("capture_manifest.json primary_payload.path must be a non-empty string")
    if expected_payload_filename is not None and primary_path != expected_payload_filename:
        raise JobProtocolError(
            f"capture manifest primary payload does not match job payload: {primary_path} != {expected_payload_filename}"
        )
    artifacts = data.get("artifacts")
    if artifacts is not None:
        if not isinstance(artifacts, list):
            raise JobProtocolError("capture_manifest.json artifacts must be a list")
        seen_paths: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                raise JobProtocolError("capture_manifest.json artifact entries must be objects")
            artifact_path = artifact.get("path")
            if not isinstance(artifact_path, str) or not artifact_path:
                raise JobProtocolError("capture_manifest.json artifact.path must be a non-empty string")
            normalized = PurePosixPath(artifact_path)
            if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
                raise JobProtocolError(f"capture_manifest.json artifact path escapes job directory: {artifact_path}")
            if artifact_path in seen_paths:
                raise JobProtocolError(f"capture_manifest.json contains duplicate artifact path: {artifact_path}")
            seen_paths.add(artifact_path)
            resolved = manifest_path.parent.joinpath(*normalized.parts)
            if not resolved.exists():
                raise JobProtocolError(f"capture_manifest.json references missing artifact: {artifact_path}")
    return data


def validate_job(job: JobPaths) -> dict[str, Any]:
    if not job.job_dir.exists():
        raise JobProtocolError(f"Job directory does not exist: {job.job_dir}")
    payload_path = job.payload_path
    if payload_path is None:
        raise JobProtocolError(f"No supported payload file found in: {job.job_dir}")
    if not job.metadata_path.exists():
        raise JobProtocolError(f"metadata.json missing in: {job.job_dir}")
    metadata = load_metadata(job.metadata_path)
    if metadata["job_id"] != job.job_id:
        raise JobProtocolError(
            f"metadata job_id does not match directory name: {metadata['job_id']} != {job.job_id}"
        )
    if job.capture_manifest_path.exists():
        load_capture_manifest(job.capture_manifest_path, expected_payload_filename=payload_path.name)
    return metadata


def inspect_job(job: JobPaths) -> JobValidationResult:
    errors: list[str] = []
    payload_path = find_payload_file(job.job_dir)
    metadata: dict[str, Any] | None = None

    if not job.job_dir.exists():
        errors.append(f"job directory does not exist: {job.job_dir}")
    if payload_path is None:
        errors.append("missing supported payload file")
    if not job.metadata_path.exists():
        errors.append("missing metadata.json")
    if not job.ready_path.exists():
        errors.append("missing READY")

    if job.metadata_path.exists():
        try:
            metadata = load_metadata(job.metadata_path)
        except Exception as exc:
            errors.append(str(exc))
        else:
            if metadata["job_id"] != job.job_id:
                errors.append(
                    f"metadata job_id does not match directory name: {metadata['job_id']} != {job.job_id}"
                )
            if payload_path is not None and metadata.get("content_type") != payload_path.suffix[1:]:
                errors.append(
                    f"content_type does not match payload suffix: {metadata.get('content_type')} != {payload_path.suffix[1:]}"
                )

    if payload_path is not None and job.capture_manifest_path.exists():
        try:
            load_capture_manifest(job.capture_manifest_path, expected_payload_filename=payload_path.name)
        except Exception as exc:
            errors.append(str(exc))

    return JobValidationResult(
        job_id=job.job_id,
        job_dir=job.job_dir,
        is_valid=not errors,
        payload_filename=payload_path.name if payload_path else None,
        content_type=str(metadata.get("content_type")) if metadata and metadata.get("content_type") else None,
        source_url=str(metadata.get("source_url")) if metadata and metadata.get("source_url") else None,
        errors=errors,
    )
