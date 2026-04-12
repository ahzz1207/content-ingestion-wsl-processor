import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    project_root: Path
    data_dir: Path
    sessions_dir: Path
    profiles_dir: Path
    output_dir: Path
    cache_dir: Path
    shared_inbox_root: Path
    headless: bool
    browser_timeout_ms: int
    user_agent: str
    ffmpeg_command: str | None
    whisper_command: str | None
    whisper_model: str
    multimodal_frame_interval_seconds: int
    multimodal_max_frames: int
    llm_provider: str
    openai_api_key: str | None
    openai_base_url: str | None
    analysis_model: str
    multimodal_model: str
    llm_max_evidence_segments: int
    whisper_timeout_seconds: int
    watcher_interval_seconds: int
    bilibili_whisper_model: str
    bilibili_whisper_language: str | None
    llm_max_content_chars: int
    image_card_model: str | None
    image_card_api_key: str | None
    image_card_base_url: str | None


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _read_first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            return value
    return None


def _has_any_env(*names: str) -> bool:
    return any(os.getenv(name) not in (None, "") for name in names)


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    # Runtime data lives outside the repo worktree by default so that
    # git reset / reclone / clean operations do not destroy live data.
    # Override with CONTENT_INGESTION_DATA_DIR when needed.
    data_dir = Path(os.getenv("CONTENT_INGESTION_DATA_DIR", Path.home() / ".content-ingestion-wsl"))
    output_dir = Path(os.getenv("CONTENT_INGESTION_OUTPUT_DIR", data_dir / "artifacts"))
    shared_inbox_root = Path(os.getenv("CONTENT_INGESTION_SHARED_INBOX_ROOT", data_dir / "shared_inbox"))
    zenmux_configured = _has_any_env(
        "ZENMUX_API_KEY",
        "ZENMUX_BASE_URL",
        "ZENMUX_ANALYSIS_MODEL",
        "ZENMUX_MULTIMODAL_MODEL",
    )
    llm_provider = "zenmux" if zenmux_configured else "openai"
    openai_api_key = _read_first_env("OPENAI_API_KEY", "ZENMUX_API_KEY")
    openai_base_url = _read_first_env("OPENAI_BASE_URL", "ZENMUX_BASE_URL")
    if llm_provider == "zenmux" and openai_base_url is None:
        openai_base_url = "https://zenmux.ai/api/v1"
    analysis_model = _read_first_env("CONTENT_INGESTION_ANALYSIS_MODEL", "ZENMUX_ANALYSIS_MODEL")
    if analysis_model is None:
        analysis_model = "openai/gpt-5.2" if llm_provider == "zenmux" else "gpt-4.1"
    multimodal_model = _read_first_env("CONTENT_INGESTION_MULTIMODAL_MODEL", "ZENMUX_MULTIMODAL_MODEL")
    if multimodal_model is None:
        multimodal_model = analysis_model
    image_card_model = _read_first_env("CONTENT_INGESTION_IMAGE_CARD_MODEL")
    image_card_api_key = _read_first_env("CONTENT_INGESTION_IMAGE_CARD_API_KEY")
    image_card_base_url = _read_first_env("CONTENT_INGESTION_IMAGE_CARD_BASE_URL")

    settings = Settings(
        project_root=project_root,
        data_dir=data_dir,
        sessions_dir=data_dir / "sessions",
        profiles_dir=data_dir / "profiles",
        output_dir=output_dir,
        cache_dir=data_dir / "cache",
        shared_inbox_root=shared_inbox_root,
        headless=_read_bool("CONTENT_INGESTION_HEADLESS", True),
        browser_timeout_ms=int(os.getenv("CONTENT_INGESTION_BROWSER_TIMEOUT_MS", "30000")),
        user_agent=os.getenv(
            "CONTENT_INGESTION_USER_AGENT",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
        ),
        ffmpeg_command=os.getenv("CONTENT_INGESTION_FFMPEG_COMMAND"),
        whisper_command=os.getenv("CONTENT_INGESTION_WHISPER_COMMAND"),
        whisper_model=os.getenv("CONTENT_INGESTION_WHISPER_MODEL", "base"),
        multimodal_frame_interval_seconds=int(os.getenv("CONTENT_INGESTION_FRAME_INTERVAL_SECONDS", "60")),
        multimodal_max_frames=int(os.getenv("CONTENT_INGESTION_MULTIMODAL_MAX_FRAMES", "8")),
        llm_provider=llm_provider,
        openai_api_key=openai_api_key,
        openai_base_url=openai_base_url,
        analysis_model=analysis_model,
        multimodal_model=multimodal_model,
        llm_max_evidence_segments=int(os.getenv("CONTENT_INGESTION_LLM_MAX_EVIDENCE_SEGMENTS", "200")),
        whisper_timeout_seconds=int(os.getenv("CONTENT_INGESTION_WHISPER_TIMEOUT_SECONDS", "600")),
        watcher_interval_seconds=int(os.getenv("CONTENT_INGESTION_WATCHER_INTERVAL_SECONDS", "2")),
        bilibili_whisper_model=os.getenv("CONTENT_INGESTION_BILIBILI_WHISPER_MODEL", "medium"),
        bilibili_whisper_language=os.getenv("CONTENT_INGESTION_BILIBILI_WHISPER_LANGUAGE") or None,
        llm_max_content_chars=int(os.getenv("CONTENT_INGESTION_LLM_MAX_CONTENT_CHARS", "40000")),
        image_card_model=image_card_model,
        image_card_api_key=image_card_api_key,
        image_card_base_url=image_card_base_url,
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    settings.profiles_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.shared_inbox_root.mkdir(parents=True, exist_ok=True)
    return settings
