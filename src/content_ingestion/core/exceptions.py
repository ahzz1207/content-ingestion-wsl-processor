class ContentIngestionError(Exception):
    """Base error for the project."""


class UnsupportedSourceError(ContentIngestionError):
    """Raised when no connector supports the input source."""


class SessionRequiredError(ContentIngestionError):
    """Raised when a platform session is missing."""


class SessionExpiredError(ContentIngestionError):
    """Raised when a stored session is no longer valid."""


class ExtractionError(ContentIngestionError):
    """Raised when content extraction fails."""


class TemporaryFetchError(ContentIngestionError):
    """Raised when a transient fetch error occurs."""
