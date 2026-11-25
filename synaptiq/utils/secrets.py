"""API key lookup. Order: environment variable, then the OS keychain."""

from __future__ import annotations

import os

SERVICE_NAME = "synaptiq"
KEY_NAME = "gemini_api_key"
ENV_VAR = "GEMINI_API_KEY"


def get_api_key() -> str | None:
    key = os.environ.get(ENV_VAR)
    if key:
        return key
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, KEY_NAME)
    except Exception:
        return None


def save_api_key(key: str) -> None:
    import keyring

    keyring.set_password(SERVICE_NAME, KEY_NAME, key)
