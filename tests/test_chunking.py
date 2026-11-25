import pytest

from synaptiq.services.chunking import chunk_pages


def test_chunks_preserve_pages_and_headings() -> None:
    chunks = chunk_pages(["# First\n\nalpha", "# Second\n\nbeta"])

    assert [(chunk.page, chunk.heading, chunk.text) for chunk in chunks] == [
        (1, "First", "# First\n\nalpha"),
        (2, "Second", "# Second\n\nbeta"),
    ]


def test_long_paragraph_is_split_within_limit() -> None:
    chunks = chunk_pages(["x" * 250], max_chars=100)

    assert [len(chunk.text) for chunk in chunks] == [100, 100, 50]
    assert [chunk.ordinal for chunk in chunks] == [0, 1, 2]


def test_rejects_too_small_chunk_size() -> None:
    with pytest.raises(ValueError, match="at least 100"):
        chunk_pages(["text"], max_chars=99)
