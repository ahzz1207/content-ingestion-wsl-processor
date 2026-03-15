import json
import re
from datetime import datetime, timezone
from pathlib import Path

from content_ingestion.core.models import FetchResult, to_dict


class ArtifactStore:
    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def write(self, result: FetchResult, output_dir: Path | None = None) -> tuple[Path, Path]:
        target_dir = output_dir or self.output_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        slug = self._slugify(result.content.title if result.content else result.platform)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        stem = f"{result.platform}_{timestamp}_{slug}"

        markdown_path = target_dir / f"{stem}.md"
        json_path = target_dir / f"{stem}.json"

        markdown = result.content.content_markdown if result.content else ""
        markdown_path.write_text(markdown or "", encoding="utf-8")
        json_path.write_text(
            json.dumps(to_dict(result), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return markdown_path, json_path

    @staticmethod
    def _slugify(value: str) -> str:
        compact = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip()).strip("-").lower()
        return compact or "artifact"
