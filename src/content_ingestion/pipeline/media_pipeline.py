from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from content_ingestion.core.config import Settings
from content_ingestion.core.evidence import build_evidence_segment_id
from content_ingestion.core.models import ContentAsset, ContentAttachment, EvidenceSegment
from content_ingestion.normalize.cleaning import clean_text


@dataclass(slots=True)
class MediaProcessingResult:
    status: str
    media_kind: str | None = None
    source_attachment_path: str | None = None
    transcript_text: str | None = None
    transcript_segments: list[EvidenceSegment] = field(default_factory=list)
    analysis_text: str | None = None
    multimodal_frame_paths: list[str] = field(default_factory=list)
    steps: list[dict[str, object]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def process_media_asset(*, job_dir: Path, asset: ContentAsset, settings: Settings) -> MediaProcessingResult:
    primary_attachment = next((item for item in asset.attachments if item.kind in {"audio", "video"}), None)
    if primary_attachment is None:
        return MediaProcessingResult(status="skipped")

    source_path = job_dir.joinpath(*Path(primary_attachment.path).parts)
    if not source_path.exists():
        return MediaProcessingResult(
            status="warn",
            media_kind=primary_attachment.kind,
            source_attachment_path=primary_attachment.path,
            warnings=[f"media attachment not found: {primary_attachment.path}"],
            steps=[{"name": "resolve_media_input", "status": "warn", "details": "missing attachment"}],
        )

    result = MediaProcessingResult(
        status="pass",
        media_kind=primary_attachment.kind,
        source_attachment_path=primary_attachment.path,
        steps=[{"name": "resolve_media_input", "status": "success", "details": primary_attachment.path}],
    )
    temp_dir = Path(tempfile.mkdtemp(prefix="content-ingestion-media-"))
    analysis_dir = job_dir / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    try:
        transcript_input = source_path
        if primary_attachment.kind == "video":
            transcript_input = _extract_audio(
                source_path=source_path,
                temp_dir=temp_dir,
                settings=settings,
                result=result,
            )
            result.multimodal_frame_paths = _extract_frames(
                source_path=source_path,
                output_dir=analysis_dir / "frames",
                settings=settings,
                result=result,
            )
        transcript = _transcribe_audio(
            source_path=transcript_input,
            output_dir=analysis_dir / "transcript",
            settings=settings,
            result=result,
        )
        if transcript is not None:
            asset.transcript_text = transcript["text"]
            asset.analysis_text = _build_analysis_text(asset, transcript["text"])
            result.transcript_text = transcript["text"]
            result.analysis_text = asset.analysis_text
            transcript_segments = [
                EvidenceSegment(
                    id=build_evidence_segment_id(
                        kind="transcript",
                        source=str(segment["source"]),
                        text=str(segment["text"]),
                        sequence=index,
                        start_ms=segment.get("start_ms"),
                        end_ms=segment.get("end_ms"),
                    ),
                    kind="transcript",
                    text=segment["text"],
                    source=segment["source"],
                    start_ms=segment.get("start_ms"),
                    end_ms=segment.get("end_ms"),
                )
                for index, segment in enumerate(transcript["segments"], start=1)
            ]
            asset.evidence_segments.extend(transcript_segments)
            result.transcript_segments = transcript_segments
            asset.attachments.extend(
                [
                    ContentAttachment(
                        id="analysis-transcript-text",
                        path="analysis/transcript/transcript.txt",
                        role="analysis_transcript",
                        media_type="text/plain",
                        kind="transcript",
                        size_bytes=(analysis_dir / "transcript" / "transcript.txt").stat().st_size,
                        description="Whisper transcript text generated during WSL processing.",
                    ),
                    ContentAttachment(
                        id="analysis-transcript-json",
                        path="analysis/transcript/transcript.json",
                        role="analysis_transcript",
                        media_type="application/json",
                        kind="metadata",
                        size_bytes=(analysis_dir / "transcript" / "transcript.json").stat().st_size,
                        description="Whisper transcript metadata generated during WSL processing.",
                    ),
                ]
            )
        if result.multimodal_frame_paths:
            for index, relative_path in enumerate(result.multimodal_frame_paths, start=1):
                frame_path = job_dir.joinpath(*Path(relative_path).parts)
                asset.attachments.append(
                    ContentAttachment(
                        id=f"analysis-frame-{index}",
                        path=relative_path,
                        role="analysis_frame",
                        media_type="image/jpeg",
                        kind="image",
                        size_bytes=frame_path.stat().st_size if frame_path.exists() else None,
                        description="Frame extracted from the source video for future multimodal analysis.",
                    )
                )
        if asset.transcript_text:
            result.steps.append({"name": "analysis_prepare", "status": "success", "details": "analysis text built"})
        else:
            result.steps.append({"name": "analysis_prepare", "status": "warn", "details": "transcript unavailable"})
        result.status = _summarize_media_status(result)
        return result
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def command_available(command: str | None, *, fallback: str | None = None) -> bool:
    if command:
        if shutil.which(command):
            return True
        return Path(command).exists()
    if fallback:
        return shutil.which(fallback) is not None
    return False


def _extract_audio(*, source_path: Path, temp_dir: Path, settings: Settings, result: MediaProcessingResult) -> Path:
    ffmpeg_command = _resolve_command(settings.ffmpeg_command, "ffmpeg")
    if ffmpeg_command is None:
        result.warnings.append("ffmpeg is unavailable; cannot extract audio from video")
        result.steps.append({"name": "extract_audio", "status": "warn", "details": "ffmpeg unavailable"})
        return source_path
    audio_path = temp_dir / "video-audio.wav"
    completed = subprocess.run(
        [
            ffmpeg_command,
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0 or not audio_path.exists():
        result.warnings.append("ffmpeg failed to extract audio from video")
        result.steps.append({"name": "extract_audio", "status": "warn", "details": completed.stderr.strip()})
        return source_path
    result.steps.append({"name": "extract_audio", "status": "success", "details": audio_path.name})
    return audio_path


def _extract_frames(
    *,
    source_path: Path,
    output_dir: Path,
    settings: Settings,
    result: MediaProcessingResult,
) -> list[str]:
    ffmpeg_command = _resolve_command(settings.ffmpeg_command, "ffmpeg")
    if ffmpeg_command is None:
        return []
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame-%03d.jpg"
    completed = subprocess.run(
        [
            ffmpeg_command,
            "-y",
            "-i",
            str(source_path),
            "-vf",
            f"fps=1/{max(settings.multimodal_frame_interval_seconds, 1)}",
            "-frames:v",
            str(max(settings.multimodal_max_frames, 1)),
            str(pattern),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        result.warnings.append("ffmpeg failed to extract multimodal frames")
        result.steps.append({"name": "extract_frames", "status": "warn", "details": completed.stderr.strip()})
        return []
    frame_paths = sorted(output_dir.glob("frame-*.jpg"))
    if not frame_paths:
        result.steps.append({"name": "extract_frames", "status": "warn", "details": "no frames produced"})
        return []
    manifest_path = output_dir.parent / "multimodal_inputs.json"
    relative_paths = [path.relative_to(source_path.parents[2]).as_posix() for path in frame_paths]
    manifest_path.write_text(
        json.dumps(
            {
                "source_video": source_path.name,
                "frame_interval_seconds": settings.multimodal_frame_interval_seconds,
                "max_frames": settings.multimodal_max_frames,
                "frame_paths": relative_paths,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    result.steps.append({"name": "extract_frames", "status": "success", "details": f"{len(relative_paths)} frames"})
    return relative_paths


def _transcribe_audio(
    *,
    source_path: Path,
    output_dir: Path,
    settings: Settings,
    result: MediaProcessingResult,
) -> dict[str, object] | None:
    whisper_command = _resolve_command(settings.whisper_command, "whisper")
    if whisper_command is None:
        result.warnings.append("whisper is unavailable; transcript generation skipped")
        result.steps.append({"name": "transcribe_audio", "status": "warn", "details": "whisper unavailable"})
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            whisper_command,
            str(source_path),
            "--model",
            settings.whisper_model,
            "--task",
            "transcribe",
            "--output_format",
            "json",
            "--output_dir",
            str(output_dir),
            "--verbose",
            "False",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    transcript_json = output_dir / f"{source_path.stem}.json"
    transcript_txt = output_dir / f"{source_path.stem}.txt"
    transcript = _load_whisper_transcript(transcript_json, transcript_txt)
    if completed.returncode != 0 or transcript is None:
        result.warnings.append("whisper failed to transcribe audio")
        result.steps.append({"name": "transcribe_audio", "status": "warn", "details": completed.stderr.strip()})
        return None

    (output_dir / "transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "transcript.txt").write_text(str(transcript["text"]), encoding="utf-8")
    result.steps.append({"name": "transcribe_audio", "status": "success", "details": settings.whisper_model})
    return transcript


def _load_whisper_transcript(json_path: Path, txt_path: Path) -> dict[str, object] | None:
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        text = clean_text(str(payload.get("text") or ""))
        segments = []
        for index, segment in enumerate(payload.get("segments", []) or [], start=1):
            if not isinstance(segment, dict):
                continue
            segment_text = clean_text(str(segment.get("text") or ""))
            if not segment_text:
                continue
            segments.append(
                {
                    "id": f"segment-{index}",
                    "text": segment_text,
                    "source": "analysis/transcript/transcript.json",
                    "start_ms": _seconds_to_ms(segment.get("start")),
                    "end_ms": _seconds_to_ms(segment.get("end")),
                }
            )
        if text:
            return {"text": text, "segments": segments}
    if txt_path.exists():
        text = clean_text(txt_path.read_text(encoding="utf-8"))
        if text:
            return {
                "text": text,
                "segments": [
                    {
                        "id": "segment-1",
                        "text": text,
                        "source": "analysis/transcript/transcript.txt",
                        "start_ms": None,
                        "end_ms": None,
                    }
                ],
            }
    return None


def _build_analysis_text(asset: ContentAsset, transcript_text: str) -> str:
    parts = [f"Title: {asset.title}"]
    if asset.author:
        parts.append(f"Author: {asset.author}")
    if asset.published_at:
        parts.append(f"Published At: {asset.published_at.isoformat()}")
    parts.append(f"Platform: {asset.source_platform}")
    parts.append(f"Source URL: {asset.source_url}")
    if asset.content_text:
        parts.extend(["", "Captured Summary:", asset.content_text])
    parts.extend(["", "Transcript:", transcript_text])
    return "\n".join(parts).strip()


def _resolve_command(command: str | None, fallback: str) -> str | None:
    if command:
        resolved = shutil.which(command)
        if resolved:
            return resolved
        if Path(command).exists():
            return command
        return None
    return shutil.which(fallback)


def _seconds_to_ms(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value) * 1000)
    except (TypeError, ValueError):
        return None


def _summarize_media_status(result: MediaProcessingResult) -> str:
    if any(step["status"] == "warn" for step in result.steps):
        return "warn"
    if result.transcript_text:
        return "pass"
    return "skipped"
