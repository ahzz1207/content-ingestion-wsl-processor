from content_ingestion.sources.registry import ConnectorRegistry


def resolve_platform(url: str, registry: ConnectorRegistry) -> str:
    return registry.resolve(url).platform
