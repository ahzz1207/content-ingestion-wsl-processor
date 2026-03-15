import json
import sys
from pathlib import Path

from content_ingestion.app.cli import main


def test_validate_inbox_uses_env_shared_root_when_argument_is_omitted(monkeypatch, tmp_path: Path, capsys) -> None:
    shared_root = tmp_path / "shared_inbox"
    monkeypatch.setenv("CONTENT_INGESTION_SHARED_INBOX_ROOT", str(shared_root))
    monkeypatch.setattr(sys, "argv", ["main.py", "validate-inbox"])

    main()

    output = capsys.readouterr().out
    assert json.loads(output) == []


def test_watch_inbox_once_uses_env_shared_root_when_argument_is_omitted(monkeypatch, tmp_path: Path, capsys) -> None:
    shared_root = tmp_path / "shared_inbox"
    monkeypatch.setenv("CONTENT_INGESTION_SHARED_INBOX_ROOT", str(shared_root))
    monkeypatch.setattr(sys, "argv", ["main.py", "watch-inbox", "--once"])

    main()

    output = capsys.readouterr().out
    assert output == ""
    assert (shared_root / "incoming").exists()
