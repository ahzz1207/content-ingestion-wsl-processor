from datetime import datetime, timezone

from content_ingestion.core.models import ContentAsset


class OpenClawAdapter:
    def ingest(self, asset: ContentAsset) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return f"stub-{asset.source_platform}-{timestamp}"
