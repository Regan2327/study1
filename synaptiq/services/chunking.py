"""Split extracted pages into chunks along structural boundaries.

Chunks never span pages, so every chunk has a page number that can be cited.
Long pages are split on paragraph breaks, falling back to a hard split only when a
single paragraph exceeds the size limit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MAX_CHARS = 2000
_HEADING = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Za-z0-9 ,:\-]{2,80})$")


@dataclass(frozen=True)
class Chunk:
    ordinal: int
    page: int | None
    heading: str | None
    text: str


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and len(stripped) <= 80 and bool(_HEADING.match(stripped))


def _split_paragraph(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]


def chunk_pages(
    pages: list[str],
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[Chunk]:
    """pages[i] is the text of page i+1. Returns chunks in document order."""
    if max_chars < 100:
        raise ValueError("max_chars must be at least 100")

    chunks: list[Chunk] = []
    current_heading: str | None = None

    for page_number, page_text in enumerate(pages, start=1):
        buffer: list[str] = []
        buffer_len = 0

        def flush() -> None:
            nonlocal buffer, buffer_len
            if buffer:
                text = "\n\n".join(buffer).strip()
                if text:
                    chunks.append(
                        Chunk(len(chunks), page_number, current_heading, text)
                    )
            buffer, buffer_len = [], 0

        for raw_paragraph in re.split(r"\n\s*\n", page_text):
            paragraph = raw_paragraph.strip()
            if not paragraph:
                continue

            first_line = paragraph.splitlines()[0]
            if _is_heading(first_line):
                flush()
                current_heading = first_line.lstrip("#").strip()

            for piece in _split_paragraph(paragraph, max_chars):
                if buffer_len + len(piece) > max_chars:
                    flush()
                buffer.append(piece)
                buffer_len += len(piece) + 2

        flush()

    return chunks
