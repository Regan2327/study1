"""Turn any supported file into citable chunks.

Each format maps to a location scheme so answers can point back to the source:
PDF and Word use page numbers, PowerPoint uses slide numbers, and lecture recordings
use timestamps. Scanned PDF pages and images are read by Gemini as pictures, and
audio or video is transcribed with its slides described.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

from synaptiq.services.chunking import Chunk, chunk_pages
from synaptiq.utils.exceptions import (
    CorruptFileError,
    GeminiError,
    IngestionError,
    UnsupportedFormatError,
)
from synaptiq.utils.parsing import parse_json_array

log = logging.getLogger("synaptiq.extractors")

SUPPORTED: dict[str, str] = {
    ".pdf": "pdf",
    ".txt": "text",
    ".md": "text",
    ".docx": "docx",
    ".pptx": "pptx",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".webp": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".m4a": "audio",
    ".mp4": "video",
    ".mov": "video",
    ".webm": "video",
}

MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
}

# A PDF page with less extracted text than this is treated as a scan.
SCANNED_PAGE_THRESHOLD = 30

IMAGE_PROMPT = (
    "Extract all text in this image. Explain any diagram, chart, or equation so a "
    "student can study from it. Return plain text, with no preamble."
)
PAGE_PROMPT = (
    "This is a scanned page. Extract all of its text. Explain any figure, diagram, or "
    "equation so a student can study from it. Return plain text, with no preamble."
)
TRANSCRIPT_PROMPT = (
    "Transcribe this lecture recording in the language that is spoken. Group the speech "
    "into segments of roughly one minute. When slides, diagrams, or equations are on "
    "screen, describe them in square brackets inside the text. Return ONLY a JSON array "
    'of objects with the keys "start" (mm:ss from the beginning) and "text". No preamble, '
    "no Markdown."
)


def kind_for(path: Path | str) -> str:
    """Return the file's kind, or raise if the type isn't supported."""
    suffix = Path(path).suffix.lower()
    kind = SUPPORTED.get(suffix)
    if kind is None:
        raise UnsupportedFormatError(f"Unsupported file type: {suffix or 'none'}")
    return kind


def extract_chunks(path: Path | str, gemini=None) -> list[Chunk]:
    """Extract citable chunks from one file. gemini is required for images, scanned
    PDF pages, and lecture recordings."""
    path = Path(path)
    kind = kind_for(path)

    if kind == "text":
        pages = [_read_text(path)]
    elif kind == "pdf":
        pages = _pdf_pages(path, gemini)
    elif kind == "docx":
        pages = _docx_pages(path)
    elif kind == "pptx":
        pages = _pptx_pages(path)
    elif kind == "image":
        _require(gemini, "Reading images")
        pages = [gemini.generate_with_file(IMAGE_PROMPT, path, MIME_TYPES[path.suffix.lower()])]
    else:  # audio or video
        return _transcribe(path, gemini)

    return chunk_pages(pages)


# ---- helpers ------------------------------------------------------------

def _require(gemini, feature: str) -> None:
    if gemini is None:
        raise GeminiError(f"{feature} needs a Gemini API key. Add one in Settings.")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError) as exc:
        raise CorruptFileError(f"Could not read {path.name}: {exc}") from exc


def _pdf_pages(path: Path, gemini) -> list[str]:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise IngestionError("PyMuPDF is not installed") from exc

    pages: list[str] = []
    try:
        with fitz.open(path) as doc:
            for page in doc:
                text = page.get_text("text")
                if len(text.strip()) < SCANNED_PAGE_THRESHOLD and gemini is not None:
                    log.info("Page %d looks scanned, reading it as an image", page.number + 1)
                    text = _describe_pdf_page(page, gemini) or text
                pages.append(text)
    except GeminiError:
        raise
    except Exception as exc:
        raise CorruptFileError(f"Could not parse PDF {path.name}: {exc}") from exc
    return pages


def _describe_pdf_page(page, gemini) -> str:
    pixmap = page.get_pixmap(dpi=150)
    fd, tmp_name = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(pixmap.tobytes("png"))
        return gemini.generate_with_file(PAGE_PROMPT, tmp_name, "image/png")
    finally:
        os.remove(tmp_name)


def _docx_pages(path: Path) -> list[str]:
    try:
        import docx  # python-docx
    except ImportError as exc:
        raise IngestionError("python-docx is not installed") from exc
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise CorruptFileError(f"Could not open Word file {path.name}: {exc}") from exc

    lines: list[str] = []
    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = (para.style.name if para.style else "").lower()
        is_heading = style.startswith("heading") or style == "title"
        lines.append(f"# {text}" if is_heading else text)
    return ["\n\n".join(lines)]


def _pptx_pages(path: Path) -> list[str]:
    try:
        from pptx import Presentation
    except ImportError as exc:
        raise IngestionError("python-pptx is not installed") from exc
    try:
        presentation = Presentation(str(path))
    except Exception as exc:
        raise CorruptFileError(f"Could not open slides {path.name}: {exc}") from exc

    pages: list[str] = []
    for slide in presentation.slides:
        parts = [
            shape.text_frame.text.strip()
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip()
        ]
        if not parts:
            pages.append("")  # keep slide numbering intact
            continue
        pages.append("\n\n".join([f"# {parts[0]}"] + parts[1:]))
    return pages


def _transcribe(path: Path, gemini) -> list[Chunk]:
    _require(gemini, "Lecture transcription")
    raw = gemini.generate_with_file(TRANSCRIPT_PROMPT, path, MIME_TYPES[path.suffix.lower()])

    chunks: list[Chunk] = []
    for item in parse_json_array(raw):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        start = str(item.get("start", "")).strip() or None
        chunks.append(Chunk(ordinal=len(chunks), page=None, heading=start, text=text))

    if not chunks:
        raise GeminiError("Transcription returned no segments")
    return chunks
