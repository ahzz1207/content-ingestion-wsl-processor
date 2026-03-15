import json
import sys
from types import SimpleNamespace
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


def test_llm_smoke_prints_json(monkeypatch, capsys) -> None:
    class _FakeService:
        def llm_smoke(self, text=None):
            return {
                "status": "pass",
                "provider": "zenmux",
                "summary": "smoke ok",
                "input_text": text,
            }

    fake_container = SimpleNamespace(
        service=_FakeService(),
        settings=SimpleNamespace(shared_inbox_root=Path("/tmp/shared_inbox")),
    )
    monkeypatch.setattr("content_ingestion.app.cli.build_app", lambda: fake_container)
    monkeypatch.setattr(sys, "argv", ["main.py", "llm-smoke", "--text", "hello smoke"])

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "pass"
    assert output["provider"] == "zenmux"
    assert output["input_text"] == "hello smoke"
