from content_ingestion.core.models import ContentAsset


def render_markdown(asset: ContentAsset) -> str:
    parts = [
        f"# {asset.title}",
        "",
        f"- Platform: {asset.source_platform}",
        f"- Source URL: {asset.source_url}",
        f"- Author: {asset.author or 'unknown'}",
        f"- Published At: {asset.published_at.isoformat() if asset.published_at else 'unknown'}",
        "",
        "---",
        "",
        asset.content_text,
    ]
    return "\n".join(parts)
