from pathlib import Path

from content_ingestion.core.config import load_settings


def test_load_settings_reads_shared_inbox_root_from_env(monkeypatch, tmp_path: Path) -> None:
    shared_root = tmp_path / "external-shared-inbox"
    monkeypatch.setenv("CONTENT_INGESTION_SHARED_INBOX_ROOT", str(shared_root))

    settings = load_settings()

    assert settings.shared_inbox_root == shared_root
    assert settings.shared_inbox_root.exists()


def test_load_settings_reads_media_tool_env(monkeypatch, tmp_path: Path) -> None:
    ffmpeg = tmp_path / "ffmpeg"
    whisper = tmp_path / "whisper"
    monkeypatch.setenv("CONTENT_INGESTION_FFMPEG_COMMAND", str(ffmpeg))
    monkeypatch.setenv("CONTENT_INGESTION_WHISPER_COMMAND", str(whisper))
    monkeypatch.setenv("CONTENT_INGESTION_WHISPER_MODEL", "small")

    settings = load_settings()

    assert settings.ffmpeg_command == str(ffmpeg)
    assert settings.whisper_command == str(whisper)
    assert settings.whisper_model == "small"


def test_load_settings_reads_openai_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("CONTENT_INGESTION_MULTIMODAL_MODEL", "gpt-4.1")

    settings = load_settings()

    assert settings.openai_api_key == "sk-test"
    assert settings.openai_base_url == "https://example.invalid/v1"
    assert settings.analysis_model == "gpt-4.1-mini"
    assert settings.multimodal_model == "gpt-4.1"
