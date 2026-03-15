import json
import os
from pathlib import Path

from content_ingestion.inbox.processor import JobProcessor
from content_ingestion.inbox.protocol import ensure_shared_inbox


def test_processor_writes_structured_asset_fields(tmp_path: Path) -> None:
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = inbox.processing / "job123"
    job_dir.mkdir(parents=True)

    (job_dir / "payload.html").write_text(
        "<html><head><title>Demo Video</title></head><body><p>Body text</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "job123",
                "source_url": "https://example.com/video",
                "collector": "windows-client",
                "collected_at": "2026-03-15T09:00:00+00:00",
                "content_type": "html",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "audio",
                "capture_manifest_filename": "capture_manifest.json",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")

    video_dir = job_dir / "attachments" / "video"
    video_dir.mkdir(parents=True)
    (video_dir / "video.mp3").write_bytes(b"audio")
    (video_dir / "video.en.vtt").write_text(
        "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello world\n",
        encoding="utf-8",
    )
    (job_dir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "job_id": "job123",
                "source_url": "https://example.com/video",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "audio",
                "primary_payload": {
                    "path": "payload.html",
                    "role": "focused_capture",
                    "media_type": "text/html",
                    "content_type": "html",
                    "size_bytes": 77,
                    "is_primary": True,
                },
                "artifacts": [
                    {
                        "path": "payload.html",
                        "role": "focused_capture",
                        "media_type": "text/html",
                        "content_type": "html",
                        "size_bytes": 77,
                        "is_primary": True,
                    },
                    {
                        "path": "attachments/video/video.mp3",
                        "role": "audio_file",
                        "media_type": "audio/mpeg",
                        "size_bytes": 5,
                        "is_primary": False,
                    },
                    {
                        "path": "attachments/video/video.en.vtt",
                        "role": "subtitle",
                        "media_type": "text/vtt",
                        "size_bytes": 52,
                        "is_primary": False,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    target_dir = JobProcessor().process(job_dir)
    normalized = json.loads((target_dir / "normalized.json").read_text(encoding="utf-8"))

    asset = normalized["asset"]
    assert asset["content_shape"] == "video"
    assert asset["attachments"]
    assert asset["attachments"][0]["kind"] == "audio"
    assert asset["evidence_segments"]
    assert asset["metadata"]["handoff"]["video_download_mode"] == "audio"
    assert asset["metadata"]["capture"]["video_download_mode"] == "audio"
    assert asset["metadata"]["llm_processing"]["status"] == "skipped"


def test_processor_runs_ffmpeg_whisper_and_llm_pipeline(tmp_path: Path, monkeypatch) -> None:
    shared_root = tmp_path / "shared_inbox"
    inbox = ensure_shared_inbox(shared_root)
    job_dir = inbox.processing / "job234"
    job_dir.mkdir(parents=True)

    ffmpeg_script = tmp_path / "ffmpeg"
    ffmpeg_script.write_text(
        "#!/bin/sh\n"
        "last=''\n"
        "for arg in \"$@\"; do last=\"$arg\"; done\n"
        "case \"$last\" in\n"
        "  *frame-%03d.jpg)\n"
        "    outdir=$(dirname \"$last\")\n"
        "    mkdir -p \"$outdir\"\n"
        "    printf 'frame1' > \"$outdir/frame-001.jpg\"\n"
        "    printf 'frame2' > \"$outdir/frame-002.jpg\"\n"
        "    ;;\n"
        "  *)\n"
        "    mkdir -p \"$(dirname \"$last\")\"\n"
        "    printf 'audio-bytes' > \"$last\"\n"
        "    ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    whisper_script = tmp_path / "whisper"
    whisper_script.write_text(
        "#!/bin/sh\n"
        "src=\"$1\"\n"
        "shift\n"
        "outdir=''\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = \"--output_dir\" ]; then\n"
        "    shift\n"
        "    outdir=\"$1\"\n"
        "  fi\n"
        "  shift\n"
        "done\n"
        "base=$(basename \"$src\")\n"
        "stem=${base%.*}\n"
        "mkdir -p \"$outdir\"\n"
        "cat > \"$outdir/$stem.json\" <<'EOF'\n"
        "{\"text\": \"hello transcript\", \"segments\": [{\"start\": 0.0, \"end\": 1.2, \"text\": \"hello transcript\"}]}\n"
        "EOF\n"
        "printf 'hello transcript' > \"$outdir/$stem.txt\"\n",
        encoding="utf-8",
    )
    os.chmod(ffmpeg_script, 0o755)
    os.chmod(whisper_script, 0o755)
    monkeypatch.setenv("CONTENT_INGESTION_FFMPEG_COMMAND", str(ffmpeg_script))
    monkeypatch.setenv("CONTENT_INGESTION_WHISPER_COMMAND", str(whisper_script))
    monkeypatch.setenv("CONTENT_INGESTION_WHISPER_MODEL", "tiny")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("CONTENT_INGESTION_MULTIMODAL_MODEL", "gpt-4.1")

    class _FakeResponses:
        def create(self, **kwargs):
            if kwargs["model"] == "gpt-4.1-mini":
                return type(
                    "Response",
                    (),
                    {
                        "output_text": json.dumps(
                            {
                                "summary": "Summarized transcript",
                                "analysis_items": ["Point 1"],
                                "verification_items": [
                                    {"claim": "Claim 1", "status": "supported", "evidence": ["Evidence 1"]}
                                ],
                                "synthesis": "Synthesized answer",
                            }
                        )
                    },
                )()
            return type(
                "Response",
                (),
                {
                    "output_text": json.dumps(
                        {
                            "visual_findings": ["Frame review"],
                            "verification_adjustments": [
                                {"claim": "Claim 2", "status": "mixed", "rationale": "Frame mismatch"}
                            ],
                            "overall_assessment": "Visual review done",
                        }
                    )
                },
            )()

    class _FakeClient:
        def __init__(self) -> None:
            self.responses = _FakeResponses()

    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline.openai_sdk_available", lambda: True)
    monkeypatch.setattr("content_ingestion.pipeline.llm_pipeline._create_client", lambda settings: _FakeClient())

    (job_dir / "payload.html").write_text(
        "<html><head><title>Demo Video</title></head><body><p>Body text</p></body></html>",
        encoding="utf-8",
    )
    (job_dir / "metadata.json").write_text(
        json.dumps(
            {
                "job_id": "job234",
                "source_url": "https://example.com/video",
                "collector": "windows-client",
                "collected_at": "2026-03-15T09:00:00+00:00",
                "content_type": "html",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "video",
                "capture_manifest_filename": "capture_manifest.json",
            }
        ),
        encoding="utf-8",
    )
    (job_dir / "READY").write_text("", encoding="utf-8")
    video_dir = job_dir / "attachments" / "video"
    video_dir.mkdir(parents=True)
    (video_dir / "video.mp4").write_bytes(b"video")
    (job_dir / "capture_manifest.json").write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "job_id": "job234",
                "source_url": "https://example.com/video",
                "platform": "bilibili",
                "content_shape": "video",
                "video_download_mode": "video",
                "primary_payload": {
                    "path": "payload.html",
                    "role": "focused_capture",
                    "media_type": "text/html",
                    "content_type": "html",
                    "size_bytes": 77,
                    "is_primary": True,
                },
                "artifacts": [
                    {
                        "path": "payload.html",
                        "role": "focused_capture",
                        "media_type": "text/html",
                        "content_type": "html",
                        "size_bytes": 77,
                        "is_primary": True,
                    },
                    {
                        "path": "attachments/video/video.mp4",
                        "role": "video_file",
                        "media_type": "video/mp4",
                        "size_bytes": 5,
                        "is_primary": False,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    target_dir = JobProcessor().process(job_dir)
    normalized = json.loads((target_dir / "normalized.json").read_text(encoding="utf-8"))
    asset = normalized["asset"]

    assert asset["transcript_text"] == "hello transcript"
    assert "Transcript:" in asset["analysis_text"]
    assert asset["metadata"]["media_processing"]["status"] == "pass"
    assert asset["summary"] == "Summarized transcript"
    assert asset["analysis_items"]
    assert asset["verification_items"]
    assert asset["synthesis"] == "Synthesized answer"
    assert asset["metadata"]["llm_processing"]["status"] == "pass"
    assert asset["metadata"]["llm_processing"]["summary_available"] is True
    assert asset["metadata"]["media_processing"]["media_kind"] == "video"
    assert asset["metadata"]["media_processing"]["transcript_text_available"] is True
    assert asset["metadata"]["media_processing"]["multimodal_frame_paths"]
    assert (target_dir / "analysis" / "transcript" / "transcript.txt").exists()
    assert (target_dir / "analysis" / "transcript" / "transcript.json").exists()
    assert (target_dir / "analysis" / "frames" / "frame-001.jpg").exists()
    assert (target_dir / "analysis" / "llm" / "analysis_result.json").exists()
