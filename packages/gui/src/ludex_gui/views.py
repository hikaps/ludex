"""A drawer page for one plugin view: a native table or label/value panel, with confirmed row actions."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QMenu, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from ludex.paths import StatePaths
from ludex.plugin_views import fetch_view, run_view_action
from ludex.plugins import Provider, View, ViewAction, ViewDetail, ViewRow, ViewTable

from .work import run_async


def plain(text: str) -> str:
    """Notification text from a plugin: control characters (except newline) become spaces."""
    return "".join(" " if (ord(c) < 32 and c != "\n") or 127 <= ord(c) < 160 else c for c in text)


class ViewPage(QWidget):
    """Fetched on first show and on Refresh; an action runs only after the user confirms it."""

    def __init__(
        self,
        paths: StatePaths,
        providers: Mapping[str, Provider],
        key: str,
        view: View,
        notify: Callable[[str, bool], None],
        after_action: Callable[[], None],
    ) -> None:
        super().__init__()
        self._paths, self._providers, self._key, self._view = paths, providers, key, view
        self._notify, self._after_action = notify, after_action
        self.snapshot: ViewTable | ViewDetail | None = None
        self.error: str | None = None
        self.busy: str | None = None  # "loading" or "running"
        self.loaded = False
        self._generation = 0  # an answer for an older fetch is dropped

        self.status = QLabel()
        self.refresh_button = QPushButton("Refresh")
        self.actions_button = QPushButton("Actions…")
        self.refresh_button.clicked.connect(self.load)
        self.actions_button.clicked.connect(self._choose_action)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._sync)
        bar = QHBoxLayout()
        bar.addWidget(self.status, 1)
        bar.addWidget(self.actions_button)
        bar.addWidget(self.refresh_button)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.table)
        self._sync()

    def showEvent(self, event) -> None:  # noqa: N802 (Qt)
        super().showEvent(event)
        if not self.loaded and self.busy is None:
            self.load()

    def load(self) -> None:
        if self.busy is not None:
            return
        self._generation += 1
        generation = self._generation
        self.snapshot, self.error, self.busy, self.loaded = None, None, "loading", False
        self.table.clear()
        self.table.setRowCount(0)
        self.table.setColumnCount(0)
        self._sync()
        provider, view = self._providers[self._key], self._view
        run_async(lambda: fetch_view(self._paths, provider, view), lambda result, error: self._fetched(generation, result, error))

    def _fetched(self, generation: int, snapshot: ViewTable | ViewDetail | None, error: str | None) -> None:
        if generation != self._generation:
            return
        self.busy, self.loaded, self.snapshot, self.error = None, True, snapshot, error
        self.table.clear()
        if isinstance(snapshot, ViewTable):
            self._fill(snapshot.columns, [row.cells for row in snapshot.rows])
        elif isinstance(snapshot, ViewDetail):
            self._fill(("Field", "Value"), [pair for pair in snapshot.fields])
            self.table.resizeRowsToContents()
        self._sync()

    def _fill(self, columns: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(list(columns))
        self.table.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for c, cell in enumerate(cells):
                item = QTableWidgetItem(cell)  # plain text, never rich text
                item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
                self.table.setItem(r, c, item)

    def selected_row(self) -> ViewRow | None:
        if self.busy is not None or not isinstance(self.snapshot, ViewTable):
            return None
        rows = self.table.selectionModel().selectedRows()
        return self.snapshot.rows[rows[0].row()] if rows else None

    def _sync(self) -> None:
        if self.busy == "loading":
            self.status.setText("Loading…")
        elif self.busy == "running":
            self.status.setText("Running action…")
        elif self.error is not None:
            self.status.setText(f"{self.error}. Press Refresh to retry.")
        elif self.snapshot is not None and not self.table.rowCount():
            self.status.setText("No results.")
        else:
            self.status.setText(self._view.title)
        self.refresh_button.setEnabled(self.busy is None)
        row = self.selected_row()
        self.actions_button.setEnabled(row is not None and bool(row.actions))

    def _choose_action(self) -> None:
        row = self.selected_row()
        if row is None or not row.actions:
            return
        self.menu = QMenu(self)
        snapshot = self.snapshot
        for action in row.actions:
            entry = self.menu.addAction(f"{action.label}  ({action.command})")  # plain text
            entry.triggered.connect(lambda _=False, a=action: self._confirm(snapshot, row, a))
        self.menu.popup(self.actions_button.mapToGlobal(self.actions_button.rect().bottomLeft()))

    def _confirm(self, snapshot: object, row: ViewRow, action: ViewAction) -> None:
        """Picking an action is not confirming it: nothing runs until the user says yes, and only if the data is still current."""
        if self._confirmed(row, action) and self.snapshot is snapshot:
            self.run_action(action)

    def _confirmed(self, row: ViewRow, action: ViewAction) -> bool:
        subject = row.cells[0] if row.cells and row.cells[0].strip() else row.id
        ask = QMessageBox(QMessageBox.Icon.Question, self._view.title, f"{action.label}: {subject}?", parent=self)
        ask.setTextFormat(Qt.TextFormat.PlainText)
        ask.setInformativeText(f"Runs {self._key} {action.command}.")
        ask.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        ask.setDefaultButton(QMessageBox.StandardButton.Cancel)
        return ask.exec() == QMessageBox.StandardButton.Yes

    def run_action(self, action: ViewAction) -> None:
        if self.busy is not None:
            return
        self.busy = "running"
        self._sync()
        run_async(
            lambda: run_view_action(self._paths, self._providers, self._key, action).text,
            self._action_done,
        )

    def _action_done(self, text: str | None, error: str | None) -> None:
        self.busy = None
        if error is not None:
            self._notify(plain(error), True)
            self._sync()
            return
        self.loaded = False
        self._after_action()  # reloads local data, which rewrites the status line: report afterwards
        self._notify(plain(text or "Action completed."), False)
        self.load()
