"""One plugin view as a QML-facing controller: a table or label/value snapshot, with confirmed row actions."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from ludex.paths import StatePaths
from ludex.plugin_views import fetch_view, run_view_action
from ludex.plugins import Provider, View, ViewDetail, ViewTable

from .work import run_async


def plain(text: str) -> str:
    """Notification text from a plugin: control characters (except newline) become spaces."""
    return "".join(" " if (ord(c) < 32 and c != "\n") or 127 <= ord(c) < 160 else c for c in text)


class ViewController(QObject):
    """Fetched on first visit and on ``load``; an action runs only for the snapshot the user was shown and confirmed."""

    changed = Signal()
    notice = Signal(str, bool)
    actionDone = Signal()

    def __init__(self, paths: StatePaths, providers: Mapping[str, Provider], key: str, view: View, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._paths, self._providers, self._key, self._view = paths, providers, key, view
        self._snapshot: ViewTable | ViewDetail | None = None
        self._error = ""
        self._busy = ""  # "loading" or "running"
        self._loaded = False
        self._generation = 0  # bumps on every fetch start and every snapshot: an older answer or confirmation is refused

    # --- what QML shows -------------------------------------------------------------------------------------

    def _title(self) -> str:
        return self._view.title

    def _get_busy(self) -> str:
        return self._busy

    def _get_error(self) -> str:
        return self._error

    def _get_loaded(self) -> bool:
        return self._loaded

    def _get_generation(self) -> int:
        return self._generation

    def _get_columns(self) -> list[str]:
        if isinstance(self._snapshot, ViewTable):
            return list(self._snapshot.columns)
        return ["Field", "Value"] if isinstance(self._snapshot, ViewDetail) else []

    def _get_rows(self) -> list[dict[str, Any]]:
        snapshot = self._snapshot
        if isinstance(snapshot, ViewTable):
            return [{"id": r.id, "cells": list(r.cells), "actions": [{"label": a.label, "command": a.command} for a in r.actions]} for r in snapshot.rows]
        if isinstance(snapshot, ViewDetail):
            return [{"id": label, "cells": [label, value], "actions": []} for label, value in snapshot.fields]
        return []

    def _get_text(self) -> str:
        if self._busy == "loading":
            return "Loading…"
        if self._busy == "running":
            return "Running action…"
        if self._error:
            return f"{self._error}. Press Refresh to retry."
        if self._snapshot is not None and not self._get_rows():
            return "No results."
        return ""

    title = Property(str, _title, constant=True)
    busy = Property(str, _get_busy, notify=changed)
    error = Property(str, _get_error, notify=changed)
    loaded = Property(bool, _get_loaded, notify=changed)
    generation = Property(int, _get_generation, notify=changed)
    columns = Property("QVariantList", _get_columns, notify=changed)
    rows = Property("QVariantList", _get_rows, notify=changed)
    text = Property(str, _get_text, notify=changed)

    # --- fetching -------------------------------------------------------------------------------------------

    @Slot()
    def ensureLoaded(self) -> None:
        if not self._loaded and not self._busy:
            self.load()

    @Slot()
    def load(self) -> None:
        if self._busy:
            return
        self._generation += 1
        generation = self._generation
        self._snapshot, self._error, self._busy, self._loaded = None, "", "loading", False
        self.changed.emit()
        provider, view, paths = self._providers[self._key], self._view, self._paths
        run_async(lambda: fetch_view(paths, provider, view), lambda result, error: self._fetched(generation, result, error))

    def _fetched(self, generation: int, snapshot: ViewTable | ViewDetail | None, error: str | None) -> None:
        if generation != self._generation:
            return
        self._generation += 1  # a confirmation dialog opened on an older snapshot can no longer run
        self._busy, self._loaded, self._snapshot, self._error = "", True, snapshot, error or ""
        self.changed.emit()

    # --- actions --------------------------------------------------------------------------------------------

    @Slot(int, int, result=str)
    def confirmText(self, row: int, action: int) -> str:
        """The question to ask before running; empty when the row or action does not exist."""
        picked = self._pick(row, action)
        if picked is None:
            return ""
        shown = picked[0].cells[0] if picked[0].cells and picked[0].cells[0].strip() else picked[0].id
        return f"{picked[1].label}: {shown}?\nRuns {self._key} {picked[1].command}."

    def _pick(self, row: int, action: int):
        if self._busy or not isinstance(self._snapshot, ViewTable):
            return None
        if not 0 <= row < len(self._snapshot.rows):
            return None
        chosen = self._snapshot.rows[row]
        return (chosen, chosen.actions[action]) if 0 <= action < len(chosen.actions) else None

    @Slot(int, int, int, result=bool)
    def runAction(self, generation: int, row: int, action: int) -> bool:
        """Run the confirmed action; refused (False) when the view moved on since the user saw it."""
        picked = self._pick(row, action)
        if picked is None or generation != self._generation:
            return False
        self._busy = "running"
        self.changed.emit()
        chosen, key, paths, providers = picked[1], self._key, self._paths, self._providers
        run_async(lambda: run_view_action(paths, providers, key, chosen).text, self._action_done)
        return True

    def _action_done(self, text: str | None, error: str | None) -> None:
        self._busy = ""
        if error is not None:
            self.notice.emit(plain(error), True)
            self.changed.emit()
            return
        self._loaded = False
        self.actionDone.emit()  # reloads local data, which rewrites the status line: report afterwards
        self.notice.emit(plain(text or "Action completed."), False)
        self.load()
