"""Flashcard generation and review. Long operations run on worker threads, and results
reach the UI through callbacks that the view forwards to the Tk main loop."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from synaptiq.model.repository import Flashcard, Repository
from synaptiq.model.retention import CardState, apply_review, schedule_order
from synaptiq.services.gemini_client import GeminiClient
from synaptiq.utils.exceptions import GeminiError, SynaptiqError
from synaptiq.utils.parsing import parse_json_array

log = logging.getLogger("synaptiq.controller")

MAX_MATERIAL_CHARS = 120_000

CARD_PROMPT = """You are creating study flashcards from the material below.
Return ONLY a JSON array, with no preamble and no Markdown fences. Each item must be
an object with the keys "front" (a question) and "back" (a concise answer).
Create at most {count} cards. Focus on concepts a student must understand, and
include figures or equations where they carry the meaning.

MATERIAL:
{material}
"""

OnDone = Callable[[object], None]
OnError = Callable[[Exception], None]


def parse_cards(raw: str) -> list[tuple[str, str]]:
    """Parse the model's reply into (front, back) pairs, skipping incomplete items."""
    pairs: list[tuple[str, str]] = []
    for item in parse_json_array(raw):
        if isinstance(item, dict):
            front = str(item.get("front", "")).strip()
            back = str(item.get("back", "")).strip()
            if front and back:
                pairs.append((front, back))
    return pairs


class StudyController:
    def __init__(self, repo: Repository, gemini: GeminiClient | None) -> None:
        self._repo = repo
        self._gemini = gemini

    def generate_cards(
        self,
        document_ids: list[int],
        count: int,
        on_done: OnDone,
        on_error: OnError,
    ) -> threading.Thread:
        """Generate cards from the selected documents, which may span a whole lecture or course."""

        def work() -> None:
            try:
                if self._gemini is None:
                    raise GeminiError("No Gemini API key configured.")
                if not document_ids:
                    raise GeminiError("Choose materials with text first.")
                material = self._repo.scope_text(document_ids)
                if not material.strip():
                    raise GeminiError("The selected materials have no text.")

                log.info("Requesting %d flashcards from %d document(s)", count, len(document_ids))
                raw = self._gemini.generate(
                    CARD_PROMPT.format(count=count, material=material[:MAX_MATERIAL_CHARS])
                )
                pairs = parse_cards(raw)
                if not pairs:
                    raise GeminiError("Gemini returned no usable cards")
                stored = self._repo.add_cards(document_ids[0], pairs)
                log.info("Saved %d flashcards", stored)
                on_done(stored)
            except SynaptiqError as exc:
                log.error("Card generation failed: %s", exc)
                on_error(exc)

        return self._start(work)

    def next_cards(self, limit: int = 20) -> list[Flashcard]:
        cards = self._repo.load_cards()
        by_id = {c.state.card_id: c for c in cards}
        ordered = schedule_order([c.state for c in cards])
        return [by_id[s.card_id] for s in ordered[:limit]]

    def record_answer(self, card: Flashcard, recalled: bool) -> CardState:
        updated = apply_review(card.state, recalled)
        self._repo.save_review(updated, recalled)
        return updated

    def export_deck(self, path: Path | str) -> int:
        return self._repo.export_deck_csv(path)

    @staticmethod
    def _start(target: Callable[[], None]) -> threading.Thread:
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        return thread
