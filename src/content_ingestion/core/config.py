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
    openai_api_key: str | None
    openai_base_url: str | None
    analysis_model: str
    multimodal_model: str
    llm_max_evidence_segments: int


def _read_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[3]
    data_dir = project_root / "data"
    output_dir = Path(os.getenv("CONTENT_INGESTION_OUTPUT_DIR", data_dir / "artifacts"))
    shared_inbox_root = Path(os.getenv("CONTENT_INGESTION_SHARED_INBOX_ROOT", data_dir / "shared_inbox"))
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
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        openai_base_url=os.getenv("OPENAI_BASE_URL"),
        analysis_model=os.getenv("CONTENT_INGESTION_ANALYSIS_MODEL", "gpt-4.1"),
        multimodal_model=os.getenv("CONTENT_INGESTION_MULTIMODAL_MODEL", "gpt-4.1"),
        llm_max_evidence_segments=int(os.getenv("CONTENT_INGESTION_LLM_MAX_EVIDENCE_SEGMENTS", "40")),
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.sessions_dir.mkdir(parents=True, exist_ok=True)
    settings.profiles_dir.mkdir(parents=True, exist_ok=True)
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.shared_inbox_root.mkdir(parents=True, exist_ok=True)
    return settings
