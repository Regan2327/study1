"""Gemini API wrapper. Separates transient failures (retry with backoff) from request
errors (fail fast). Media files are uploaded, processed, and deleted after use."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Callable, TypeVar

from synaptiq.utils.exceptions import GeminiError, GeminiRequestError, GeminiTransientError

log = logging.getLogger("synaptiq.gemini")

MODEL = "gemini-2.5-flash"
MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 1.0
FILE_POLL_SECONDS = 2.0
FILE_TIMEOUT_SECONDS = 300.0

T = TypeVar("T")


def classify_error(exc: Exception) -> Exception:
    """Map a raw SDK or network exception to one of our error types."""
    if isinstance(exc, GeminiError):
        return exc
    message = str(exc).lower()
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)

    if isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return GeminiTransientError(str(exc))
    if status in (429, 500, 502, 503, 504) or "rate limit" in message or "unavailable" in message:
        return GeminiTransientError(str(exc))
    return GeminiRequestError(str(exc))


def with_retry(
    operation: Callable[[], T],
    *,
    attempts: int = MAX_ATTEMPTS,
    base_delay: float = BASE_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run operation, retrying transient failures with exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:
            error = classify_error(exc)
            if not isinstance(error, GeminiTransientError):
                raise error from exc
            last_error = error
            if attempt == attempts:
                break
            delay = base_delay * (2 ** (attempt - 1))
            log.warning("Gemini transient error (attempt %d/%d), retrying in %.1fs: %s",
                        attempt, attempts, delay, error)
            sleep(delay)
    raise last_error  # type: ignore[misc]


class GeminiClient:
    def __init__(self, api_key: str, model: str = MODEL) -> None:
        if not api_key:
            raise GeminiRequestError("A Gemini API key is required.")
        from google import genai  # imported here so the rest of the app runs without the SDK

        self._client = genai.Client(api_key=api_key)
        self._model = model

    def generate(self, prompt: str) -> str:
        def call() -> str:
            response = self._client.models.generate_content(model=self._model, contents=prompt)
            return self._text_or_raise(response)

        return with_retry(call)

    def generate_with_file(self, prompt: str, path: Path | str, mime_type: str) -> str:
        """Upload a file, ask a question about it, then delete the upload."""

        def call() -> str:
            uploaded = self._client.files.upload(file=str(path), config={"mime_type": mime_type})
            try:
                uploaded = self._wait_until_active(uploaded)
                response = self._client.models.generate_content(
                    model=self._model, contents=[uploaded, prompt]
                )
            finally:
                self._delete_quietly(uploaded)
            return self._text_or_raise(response)

        return with_retry(call)

    def _wait_until_active(self, uploaded):
        waited = 0.0
        while str(getattr(getattr(uploaded, "state", None), "name", "ACTIVE")) == "PROCESSING":
            if waited >= FILE_TIMEOUT_SECONDS:
                raise GeminiTransientError("Gemini is still processing the upload")
            time.sleep(FILE_POLL_SECONDS)
            waited += FILE_POLL_SECONDS
            uploaded = self._client.files.get(name=uploaded.name)
        return uploaded

    def _delete_quietly(self, uploaded) -> None:
        try:
            self._client.files.delete(name=uploaded.name)
        except Exception:
            log.warning("Could not delete uploaded file %s", getattr(uploaded, "name", "?"))

    @staticmethod
    def _text_or_raise(response) -> str:
        text = getattr(response, "text", None)
        if not text:
            raise GeminiTransientError("Empty response from Gemini")
        return text
