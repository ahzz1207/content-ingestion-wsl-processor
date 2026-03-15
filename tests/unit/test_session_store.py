from pathlib import Path

from content_ingestion.session.session_store import SessionStore


def test_session_store_roundtrip(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    state = {"cookies": [{"name": "session"}], "origins": []}

    store.save("wechat", state)

    assert store.exists("wechat")
    assert store.load("wechat") == state
