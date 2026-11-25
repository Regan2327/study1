"""Custom exception hierarchy. Every error the app expects derives from SynaptiqError
so the controller can catch it, log it to telemetry, and keep the UI alive."""


class SynaptiqError(Exception):
    """Base class for all expected application errors."""


class IngestionError(SynaptiqError):
    """A document could not be read or parsed."""


class CorruptFileError(IngestionError):
    """The file is unreadable or malformed. The file is quarantined, not retried."""


class UnsupportedFormatError(IngestionError):
    """The file extension or content type is not supported."""


class GeminiError(SynaptiqError):
    """Base class for failures talking to the Gemini API."""


class GeminiTransientError(GeminiError):
    """Timeouts, dropped connections, 5xx, or rate limits. Safe to retry with backoff."""


class GeminiRequestError(GeminiError):
    """Invalid request or auth problem. Retrying will not help."""


class StorageError(SynaptiqError):
    """A database operation failed."""
