"""Parse JSON arrays from Gemini replies. Models sometimes wrap JSON in code fences,
so fences are stripped before parsing."""

from __future__ import annotations

import json
import re

from synaptiq.utils.exceptions import GeminiError

_FENCE = re.compile(r"```(?:json)?")


def parse_json_array(raw: str) -> list:
    cleaned = _FENCE.sub("", raw).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Model did not return valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise GeminiError("Model reply was not a JSON array")
    return value
