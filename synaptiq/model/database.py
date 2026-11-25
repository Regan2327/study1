"""SQLite persistence. One connection guarded by a lock, so the import worker and the
UI thread can share it safely. Multi-row writes run inside a transaction."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from synaptiq.utils.exceptions import StorageError

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS courses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS lectures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    number      INTEGER NOT NULL,
    title       TEXT NOT NULL,
    held_on     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (course_id, title)
);

CREATE TABLE IF NOT EXISTS documents (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash  TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    source_path   TEXT,
    kind          TEXT NOT NULL DEFAULT 'document',
    lecture_id    INTEGER REFERENCES lectures(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chunks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    ordinal      INTEGER NOT NULL,
    page         INTEGER,
    heading      TEXT,
    text         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cards (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    front         TEXT NOT NULL,
    back          TEXT NOT NULL,
    stability     REAL NOT NULL DEFAULT 1.0,
    difficulty    REAL NOT NULL DEFAULT 0.5,
    last_reviewed TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reviews (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    card_id     INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    recalled    INTEGER NOT NULL CHECK (recalled IN (0, 1)),
    reviewed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_lectures_course ON lectures(course_id);
CREATE INDEX IF NOT EXISTS idx_documents_lecture ON documents(lecture_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_cards_document ON cards(document_id);
CREATE INDEX IF NOT EXISTS idx_reviews_card ON reviews(card_id);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise StorageError(f"Could not open database at {self.path}: {exc}") from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on any exception."""
        with self._lock:
            try:
                yield self._conn
                self._conn.commit()
            except Exception as exc:
                self._conn.rollback()
                if isinstance(exc, sqlite3.Error):
                    raise StorageError(str(exc)) from exc
                raise

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetchall()
            except sqlite3.Error as exc:
                raise StorageError(str(exc)) from exc

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self._lock:
            try:
                return self._conn.execute(sql, params).fetchone()
            except sqlite3.Error as exc:
                raise StorageError(str(exc)) from exc

    def close(self) -> None:
        with self._lock:
            self._conn.close()
