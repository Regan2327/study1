"""Main window. Only this module touches Tk widgets. Worker threads never call widget
methods directly: their results go onto _ui_queue and are applied on the Tk main loop."""

from __future__ import annotations

import queue
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Callable

import customtkinter as ctk
import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from synaptiq.controller.import_queue import ImportJob, ImportQueue, JobState
from synaptiq.controller.study_controller import StudyController
from synaptiq.model.repository import Flashcard, Repository
from synaptiq.model.retention import recall_probability
from synaptiq.services.extractors import SUPPORTED
from synaptiq.utils import telemetry
from synaptiq.utils.exceptions import StorageError, SynaptiqError

VOID = "#0A0A0C"
PANEL = "#111116"
ACCENT = "#00FFCC"
TEXT = "#E6FFF9"
MUTED = "#5C7A74"
WARN = "#FFB86B"
ERROR = "#FF5C7A"
ALL_MATERIALS = "All materials"
DEFAULT_COURSE = "General"


class MainWindow(ctk.CTk):
    def __init__(self, controller: StudyController, imports: ImportQueue, repo: Repository) -> None:
        super().__init__()
        self.controller = controller
        self.imports = imports
        self.repo = repo
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._current: Flashcard | None = None
        self._scope_map: dict[str, int | None] = {ALL_MATERIALS: None}

        ctk.set_appearance_mode("dark")
        self.title("Synaptiq")
        self.geometry("1240x820")
        self.configure(fg_color=VOID)

        self._build_layout()
        self._refresh_deck()
        self._refresh_scope()
        self.after(100, self._poll_ui_queue)
        self.after(250, self._drain_telemetry)

    # ---- layout ----------------------------------------------------------

    def _build_layout(self) -> None:
        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(0, weight=3)
        self.grid_rowconfigure(1, weight=2)

        study = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=12)
        study.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        study.grid_columnconfigure(0, weight=1)
        study.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(study, text="SYNAPTIQ", text_color=ACCENT,
                     font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(14, 6))

        library = ctk.CTkFrame(study, fg_color="transparent")
        library.grid(row=1, column=0, sticky="ew", padx=16)
        self.course_entry = ctk.CTkEntry(library, width=150, placeholder_text="Course", fg_color=VOID,
                                         border_color=MUTED, text_color=TEXT)
        self.course_entry.insert(0, DEFAULT_COURSE)
        self.course_entry.pack(side="left", padx=(0, 6))
        self.course_entry.bind("<FocusOut>", lambda _e: self._refresh_scope())
        self.lecture_entry = ctk.CTkEntry(library, width=190, placeholder_text="Lecture title (optional)",
                                          fg_color=VOID, border_color=MUTED, text_color=TEXT)
        self.lecture_entry.pack(side="left", padx=(0, 6))
        ctk.CTkButton(library, text="Add files", command=self._on_import,
                      fg_color=ACCENT, text_color=VOID, hover_color="#00D9B0").pack(side="left")

        toolbar = ctk.CTkFrame(study, fg_color="transparent")
        toolbar.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 0))
        self.scope_menu = ctk.CTkOptionMenu(toolbar, values=[ALL_MATERIALS], width=190,
                                            fg_color=VOID, button_color=MUTED, text_color=TEXT)
        self.scope_menu.pack(side="left", padx=(0, 6))
        ctk.CTkButton(toolbar, text="Generate cards", command=self._on_generate,
                      fg_color="transparent", border_width=1, border_color=ACCENT,
                      text_color=ACCENT).pack(side="left", padx=(0, 6))
        ctk.CTkButton(toolbar, text="Export CSV", command=self._on_export,
                      fg_color="transparent", border_width=1, border_color=MUTED,
                      text_color=TEXT).pack(side="left")

        self.card_front = ctk.CTkLabel(study, text="Add files to begin.", wraplength=640,
                                       text_color=TEXT, font=ctk.CTkFont(size=18))
        self.card_front.grid(row=3, column=0, sticky="nsew", padx=16, pady=16)

        self.card_back = ctk.CTkLabel(study, text="", wraplength=640, text_color=MUTED,
                                      font=ctk.CTkFont(size=15))
        self.card_back.grid(row=4, column=0, sticky="ew", padx=16)

        grades = ctk.CTkFrame(study, fg_color="transparent")
        grades.grid(row=5, column=0, sticky="ew", padx=16, pady=14)
        ctk.CTkButton(grades, text="Show answer", command=self._show_answer,
                      fg_color="transparent", border_width=1, border_color=MUTED,
                      text_color=TEXT).pack(side="left", padx=(0, 8))
        ctk.CTkButton(grades, text="Forgot", command=lambda: self._grade(False),
                      fg_color=ERROR, text_color=VOID).pack(side="left", padx=(0, 8))
        ctk.CTkButton(grades, text="Recalled", command=lambda: self._grade(True),
                      fg_color=ACCENT, text_color=VOID).pack(side="left")

        analytics = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=12)
        analytics.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=(12, 6))
        self.figure = Figure(figsize=(4, 3), facecolor=PANEL)
        self.axes = self.figure.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.figure, master=analytics)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
        self._draw_decay_curve(stability=1.0)

        self.status = ctk.CTkLabel(analytics, text="", text_color=MUTED)
        self.status.pack(anchor="w", padx=12, pady=(0, 10))

        terminal = ctk.CTkFrame(self, fg_color="#050507", corner_radius=12)
        terminal.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=12, pady=(6, 12))
        ctk.CTkLabel(terminal, text="TELEMETRY", text_color=ACCENT,
                     font=ctk.CTkFont(family="Courier", size=12, weight="bold")).pack(anchor="w", padx=12, pady=(8, 0))
        self.log_box = ctk.CTkTextbox(terminal, fg_color="#050507", text_color=ACCENT,
                                      font=ctk.CTkFont(family="Courier", size=12), wrap="word")
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.log_box.configure(state="disabled")

    # ---- thread hand-off -------------------------------------------------

    def post(self, fn: Callable[[], None]) -> None:
        """Safe from any thread. fn runs on the Tk main loop."""
        self._ui_queue.put(fn)

    def _poll_ui_queue(self) -> None:
        try:
            while True:
                self._ui_queue.get_nowait()()
        except queue.Empty:
            pass
        except Exception as exc:
            self._log_line("ERROR", f"UI update failed: {exc}")
        self.after(100, self._poll_ui_queue)

    def _drain_telemetry(self) -> None:
        events = telemetry.drain()
        if events:
            self.log_box.configure(state="normal")
            for event in events:
                stamp = event.timestamp.strftime("%H:%M:%S")
                self.log_box.insert("end", f"[{stamp}] {event.level:<7} {event.message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(250, self._drain_telemetry)

    def _log_line(self, level: str, message: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{level:<7} {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---- library actions -------------------------------------------------

    def _course_name(self) -> str:
        return " ".join(self.course_entry.get().split()) or DEFAULT_COURSE

    def _on_import(self) -> None:
        patterns = " ".join(f"*{suffix}" for suffix in sorted(SUPPORTED))
        paths = filedialog.askopenfilenames(
            title="Add course materials",
            filetypes=[("Supported files", patterns), ("All files", "*.*")],
        )
        if not paths:
            return
        try:
            course_id = self.repo.get_or_create_course(self._course_name())
            title = " ".join(self.lecture_entry.get().split()) or "Untitled lecture"
            lecture_id = self.repo.find_or_create_lecture(course_id, title)
        except (StorageError, ValueError) as exc:
            self._error("Could not set up the lecture", exc)
            return

        queued, rejected = 0, []
        for path in paths:
            try:
                self.imports.submit(path, lecture_id=lecture_id)
                queued += 1
            except SynaptiqError as exc:
                rejected.append(f"{Path(path).name}: {exc}")
        self.status.configure(text=f"Queued {queued} file(s) for {title}", text_color=MUTED)
        for line in rejected:
            self._log_line("WARNING", f"Skipped {line}")
        self._refresh_scope()

    def on_job_update(self, job: ImportJob) -> None:
        """Called on the Tk main loop when an import job changes state."""
        level = {JobState.FAILED: "ERROR", JobState.SKIPPED: "WARNING"}.get(job.state, "INFO")
        detail = f" ({job.message})" if job.message else ""
        self._log_line(level, f"{job.path.name}: {job.state.value}{detail}")
        if job.state in (JobState.DONE, JobState.SKIPPED):
            self._refresh_scope()
            self.status.configure(text=f"Ready: {job.path.name}", text_color=MUTED)
        elif job.state is JobState.FAILED:
            self.status.configure(text=f"Could not import {job.path.name}", text_color=WARN)

    def _refresh_scope(self) -> None:
        """Rebuild the material picker from the lectures in the current course."""
        self._scope_map = {ALL_MATERIALS: None}
        course_id = self.repo.find_course(self._course_name())
        if course_id is not None:
            for lecture in self.repo.list_lectures(course_id):
                self._scope_map[lecture.title] = lecture.id
        choice = self.scope_menu.get()
        self.scope_menu.configure(values=list(self._scope_map))
        self.scope_menu.set(choice if choice in self._scope_map else ALL_MATERIALS)

    def _on_generate(self) -> None:
        scope = self.scope_menu.get()
        course_id = self.repo.find_course(self._course_name())
        if course_id is None:
            messagebox.showinfo("Synaptiq", "Add some materials first.")
            return
        lecture_id = self._scope_map.get(scope)
        docs = (self.repo.list_documents(lecture_id=lecture_id) if lecture_id is not None
                else self.repo.list_documents(course_id=course_id))
        if not docs:
            messagebox.showinfo("Synaptiq", "No materials in this scope yet.")
            return
        self.status.configure(text=f"Generating cards from {len(docs)} document(s)...", text_color=MUTED)
        self.controller.generate_cards(
            [d.id for d in docs],
            count=15,
            on_done=lambda n: self.post(lambda: self._cards_finished(n)),
            on_error=lambda exc: self.post(lambda: self._error("Card generation failed", exc)),
        )

    def _cards_finished(self, count: int) -> None:
        self.status.configure(text=f"Added {count} cards", text_color=MUTED)
        self._refresh_deck()

    # ---- review ----------------------------------------------------------

    def _refresh_deck(self) -> None:
        deck = self.controller.next_cards()
        if deck:
            self._show_card(deck[0])
        else:
            self._current = None
            self.card_front.configure(text="No cards yet. Add materials and generate cards.")
            self.card_back.configure(text="")

    def _show_card(self, card: Flashcard) -> None:
        self._current = card
        self.card_front.configure(text=card.front)
        self.card_back.configure(text="")
        self._draw_decay_curve(stability=card.state.stability_days)

    def _show_answer(self) -> None:
        if self._current:
            self.card_back.configure(text=self._current.back)

    def _grade(self, recalled: bool) -> None:
        if not self._current:
            return
        try:
            updated = self.controller.record_answer(self._current, recalled)
        except SynaptiqError as exc:
            self._error("Could not save review", exc)
            return
        self._draw_decay_curve(stability=updated.stability_days)
        self._refresh_deck()

    def _on_export(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            count = self.controller.export_deck(path)
            self.status.configure(text=f"Exported {count} cards", text_color=MUTED)
        except OSError as exc:
            self._error("Export failed", exc)

    # ---- helpers ---------------------------------------------------------

    def _error(self, title: str, exc: Exception) -> None:
        self.status.configure(text=title, text_color=WARN)
        self._log_line("ERROR", f"{title}: {exc}")
        messagebox.showerror("Synaptiq", f"{title}.\n\n{exc}")

    def _draw_decay_curve(self, stability: float) -> None:
        days = np.linspace(0, max(stability * 3, 1), 200)
        recall = [recall_probability(float(t), stability) for t in days]
        self.axes.clear()
        self.axes.plot(days, recall, color=ACCENT, linewidth=2)
        self.axes.set_facecolor(PANEL)
        self.axes.set_title("Predicted recall", color=TEXT, fontsize=10)
        self.axes.set_xlabel("days since review", color=MUTED, fontsize=8)
        self.axes.set_ylabel("R(t)", color=MUTED, fontsize=8)
        self.axes.set_ylim(0, 1.05)
        self.axes.tick_params(colors=MUTED, labelsize=7)
        for spine in self.axes.spines.values():
            spine.set_color(MUTED)
        self.figure.tight_layout()
        self.canvas.draw_idle()
