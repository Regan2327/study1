"""Application entry point. Builds the object graph and starts the Tk loop."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from synaptiq.utils import telemetry
from synaptiq.utils.secrets import get_api_key

APP_DIR = Path.home() / ".synaptiq"
DB_PATH = APP_DIR / "synaptiq.db"


def build_gemini(api_key: str | None):
    if not api_key:
        return None
    try:
        from synaptiq.services.gemini_client import GeminiClient

        return GeminiClient(api_key)
    except Exception as exc:  # a missing SDK or bad key should not block the app
        logging.getLogger("synaptiq").error("Gemini unavailable: %s", exc)
        return None


def main() -> int:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    telemetry.install()
    log = logging.getLogger("synaptiq")

    from synaptiq.controller.import_queue import ImportQueue
    from synaptiq.controller.study_controller import StudyController
    from synaptiq.model.database import Database
    from synaptiq.model.repository import Repository
    from synaptiq.view.main_window import MainWindow

    db = Database(DB_PATH)
    repo = Repository(db)
    gemini = build_gemini(get_api_key())
    if gemini is None:
        log.warning("No Gemini API key found. Set GEMINI_API_KEY to enable transcription and cards.")

    window_holder: dict[str, MainWindow] = {}

    def on_job_update(job):
        window = window_holder.get("window")
        if window is not None:
            window.post(lambda: window.on_job_update(job))

    imports = ImportQueue(repo, gemini, on_update=on_job_update)
    controller = StudyController(repo, gemini)
    window = MainWindow(controller, imports, repo)
    window_holder["window"] = window
    log.info("Synaptiq started. Database: %s", DB_PATH)

    try:
        window.mainloop()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
