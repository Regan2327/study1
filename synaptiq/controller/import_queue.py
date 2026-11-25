"""Background import queue. Files are processed one at a time on a worker thread, so a
long transcription never freezes the window. Each job reports its state through a
callback, which the view forwards to the Tk main loop."""

from __future__ import annotations

import hashlib
import logging
import queue
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

from synaptiq.model.repository import Repository
from synaptiq.services.extractors import extract_chunks, kind_for
from synaptiq.utils.exceptions import CorruptFileError, SynaptiqError

log = logging.getLogger("synaptiq.imports")

HASH_BLOCK_BYTES = 1 << 20


class JobState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass
class ImportJob:
    id: int
    path: Path
    lecture_id: int | None
    state: JobState = JobState.QUEUED
    message: str = ""
    document_id: int | None = None


def hash_file(path: Path) -> str:
    """SHA-256 of a file, read in blocks so large lecture videos don't fill memory."""
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(HASH_BLOCK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


class ImportQueue:
    def __init__(
        self,
        repo: Repository,
        gemini,
        on_update: Callable[[ImportJob], None] | None = None,
        start_worker: bool = True,
    ) -> None:
        self._repo = repo
        self._gemini = gemini
        self._on_update = on_update or (lambda job: None)
        self._start_worker = start_worker
        self._jobs: dict[int, ImportJob] = {}
        self._pending: queue.Queue[ImportJob] = queue.Queue()
        self._next_id = 1
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def submit(self, path: Path | str, lecture_id: int | None = None) -> ImportJob:
        """Queue a file. Unsupported types are rejected immediately."""
        path = Path(path)
        kind_for(path)  # raises UnsupportedFormatError before anything is queued
        with self._lock:
            job = ImportJob(self._next_id, path, lecture_id)
            self._next_id += 1
            self._jobs[job.id] = job
        self._pending.put(job)
        self._notify(job)
        if self._start_worker:
            self._ensure_worker()
        return job

    def jobs(self) -> list[ImportJob]:
        with self._lock:
            return list(self._jobs.values())

    def process(self, job: ImportJob) -> None:
        """Run one job. Called by the worker thread, and directly by tests."""
        job.state = JobState.RUNNING
        self._notify(job)
        try:
            digest = hash_file(job.path)
            existing = self._repo.find_document_by_hash(digest)
            if existing is not None:
                job.state = JobState.SKIPPED
                job.message = "already imported"
                job.document_id = existing
                return

            chunks = extract_chunks(job.path, self._gemini)
            if not chunks:
                raise CorruptFileError(f"No readable text found in {job.path.name}")

            job.document_id = self._repo.add_document(
                digest,
                job.path.stem,
                str(job.path),
                chunks,
                kind=kind_for(job.path),
                lecture_id=job.lecture_id,
            )
            job.state = JobState.DONE
            job.message = f"{len(chunks)} sections"
            log.info("Imported %s: %d sections", job.path.name, len(chunks))
        except SynaptiqError as exc:
            job.state = JobState.FAILED
            job.message = str(exc)
            log.error("Import failed for %s: %s", job.path.name, exc)
        except OSError as exc:
            job.state = JobState.FAILED
            job.message = f"Could not read file: {exc}"
            log.error("Could not read %s: %s", job.path.name, exc)
        finally:
            self._notify(job)

    # ---- internals -------------------------------------------------------

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, daemon=True)
                self._worker.start()

    def _run(self) -> None:
        while True:
            job = self._pending.get()
            try:
                self.process(job)
            finally:
                self._pending.task_done()

    def _notify(self, job: ImportJob) -> None:
        try:
            self._on_update(job)
        except Exception:
            log.exception("Import status callback failed")
