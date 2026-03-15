from content_ingestion.core.models import ContentAsset


def with_metadata(asset: ContentAsset, **metadata: str) -> ContentAsset:
    asset.metadata.update(metadata)
    return asset
