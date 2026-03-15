import json
from pathlib import Path


class SessionStore:
    def __init__(self, sessions_dir: Path) -> None:
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, platform: str) -> Path:
        return self.sessions_dir / f"{platform}.json"

    def exists(self, platform: str) -> bool:
        return self._path_for(platform).exists()

    def load(self, platform: str) -> dict | None:
        path = self._path_for(platform)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, platform: str, storage_state: dict) -> None:
        path = self._path_for(platform)
        path.write_text(
            json.dumps(storage_state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete(self, platform: str) -> None:
        path = self._path_for(platform)
        if path.exists():
            path.unlink()
