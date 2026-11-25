"""Data access. Controllers and views never write SQL directly."""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from synaptiq.model.database import Database
from synaptiq.model.retention import CardState
from synaptiq.services.chunking import Chunk


@dataclass(frozen=True)
class Flashcard:
    id: int
    document_id: int | None
    front: str
    back: str
    state: CardState


@dataclass(frozen=True)
class DocumentInfo:
    id: int
    title: str
    kind: str
    lecture_id: int | None


@dataclass(frozen=True)
class LectureInfo:
    id: int
    course_id: int
    number: int
    title: str


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise ValueError("Name can't be empty.")
    return cleaned


class Repository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- courses and lectures -------------------------------------------

    def find_course(self, name: str) -> int | None:
        row = self._db.fetchone("SELECT id FROM courses WHERE name = ?", (_clean_name(name),))
        return row["id"] if row else None

    def get_or_create_course(self, name: str) -> int:
        name = _clean_name(name)
        with self._db.transaction() as conn:
            row = conn.execute("SELECT id FROM courses WHERE name = ?", (name,)).fetchone()
            if row:
                return row["id"]
            return conn.execute("INSERT INTO courses (name) VALUES (?)", (name,)).lastrowid

    def list_courses(self) -> list[tuple[int, str]]:
        rows = self._db.fetchall("SELECT id, name FROM courses ORDER BY name")
        return [(r["id"], r["name"]) for r in rows]

    def find_or_create_lecture(self, course_id: int, title: str) -> int:
        title = _clean_name(title)
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT id FROM lectures WHERE course_id = ? AND title = ?", (course_id, title)
            ).fetchone()
            if row:
                return row["id"]
            number = conn.execute(
                "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM lectures WHERE course_id = ?",
                (course_id,),
            ).fetchone()["n"]
            return conn.execute(
                "INSERT INTO lectures (course_id, number, title) VALUES (?, ?, ?)",
                (course_id, number, title),
            ).lastrowid

    def list_lectures(self, course_id: int) -> list[LectureInfo]:
        rows = self._db.fetchall(
            "SELECT id, course_id, number, title FROM lectures WHERE course_id = ? ORDER BY number",
            (course_id,),
        )
        return [LectureInfo(r["id"], r["course_id"], r["number"], r["title"]) for r in rows]

    # ---- documents ------------------------------------------------------

    def find_document_by_hash(self, digest: str) -> int | None:
        row = self._db.fetchone("SELECT id FROM documents WHERE content_hash = ?", (digest,))
        return row["id"] if row else None

    def add_document(
        self,
        digest: str,
        title: str,
        source_path: str | None,
        chunks: list[Chunk],
        kind: str = "document",
        lecture_id: int | None = None,
    ) -> int:
        """Insert a document and all its chunks in one transaction."""
        with self._db.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO documents (content_hash, title, source_path, kind, lecture_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (digest, title, source_path, kind, lecture_id),
            )
            document_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO chunks (document_id, ordinal, page, heading, text) "
                "VALUES (?, ?, ?, ?, ?)",
                [(document_id, c.ordinal, c.page, c.heading, c.text) for c in chunks],
            )
        return document_id

    def list_documents(
        self, lecture_id: int | None = None, course_id: int | None = None
    ) -> list[DocumentInfo]:
        if lecture_id is not None:
            rows = self._db.fetchall(
                "SELECT id, title, kind, lecture_id FROM documents WHERE lecture_id = ? ORDER BY id",
                (lecture_id,),
            )
        elif course_id is not None:
            rows = self._db.fetchall(
                "SELECT d.id, d.title, d.kind, d.lecture_id FROM documents d "
                "JOIN lectures l ON l.id = d.lecture_id WHERE l.course_id = ? ORDER BY d.id",
                (course_id,),
            )
        else:
            rows = self._db.fetchall(
                "SELECT id, title, kind, lecture_id FROM documents ORDER BY id"
            )
        return [DocumentInfo(r["id"], r["title"], r["kind"], r["lecture_id"]) for r in rows]

    def document_text(self, document_id: int) -> str:
        rows = self._db.fetchall(
            "SELECT heading, text FROM chunks WHERE document_id = ? ORDER BY ordinal",
            (document_id,),
        )
        return "\n\n".join(
            f"[{r['heading']}] {r['text']}" if r["heading"] else r["text"] for r in rows
        )

    def scope_text(self, document_ids: list[int]) -> str:
        parts = [self.document_text(doc_id) for doc_id in document_ids]
        return "\n\n".join(p for p in parts if p.strip())

    # ---- cards and reviews ----------------------------------------------

    def add_cards(self, document_id: int | None, pairs: list[tuple[str, str]]) -> int:
        with self._db.transaction() as conn:
            conn.executemany(
                "INSERT INTO cards (document_id, front, back) VALUES (?, ?, ?)",
                [(document_id, front, back) for front, back in pairs],
            )
        return len(pairs)

    def load_cards(self) -> list[Flashcard]:
        rows = self._db.fetchall(
            "SELECT id, document_id, front, back, stability, difficulty, last_reviewed "
            "FROM cards ORDER BY id"
        )
        cards = []
        for r in rows:
            last = (
                datetime.fromisoformat(r["last_reviewed"]).replace(tzinfo=timezone.utc)
                if r["last_reviewed"]
                else None
            )
            state = CardState(
                card_id=r["id"],
                stability_days=r["stability"],
                difficulty=r["difficulty"],
                last_reviewed=last,
            )
            cards.append(Flashcard(r["id"], r["document_id"], r["front"], r["back"], state))
        return cards

    def save_review(self, card: CardState, recalled: bool) -> None:
        """Persist the updated scheduling state and log the review in one transaction."""
        with self._db.transaction() as conn:
            conn.execute(
                "UPDATE cards SET stability = ?, difficulty = ?, last_reviewed = ? WHERE id = ?",
                (
                    card.stability_days,
                    card.difficulty,
                    card.last_reviewed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                    if card.last_reviewed
                    else None,
                    card.card_id,
                ),
            )
            conn.execute(
                "INSERT INTO reviews (card_id, recalled) VALUES (?, ?)",
                (card.card_id, 1 if recalled else 0),
            )

    def export_deck_csv(self, path: Path | str) -> int:
        cards = self.load_cards()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["front", "back"])
            for card in cards:
                writer.writerow([card.front, card.back])
        return len(cards)
