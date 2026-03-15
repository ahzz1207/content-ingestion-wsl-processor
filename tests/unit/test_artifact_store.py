from pathlib import Path

from content_ingestion.core.models import ContentAsset, FetchResult
from content_ingestion.storage.artifact_store import ArtifactStore


def test_artifact_store_writes_json_and_markdown(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    content = ContentAsset(
        source_platform="wechat",
        source_url="https://mp.weixin.qq.com/s/example",
        canonical_url="https://mp.weixin.qq.com/s/example",
        title="Hello World",
        content_text="Example body",
        content_markdown="# Hello World",
    )
    result = FetchResult(
        success=True,
        status="ok",
        platform="wechat",
        url="https://mp.weixin.qq.com/s/example",
        content=content,
    )

    markdown_path, json_path = store.write(result)

    assert markdown_path.exists()
    assert json_path.exists()
    assert markdown_path.read_text(encoding="utf-8") == "# Hello World"
