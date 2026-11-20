"""The ludex desktop window (Qt): a drawer of Owned, Installed, Search, Jobs, Settings and one entry per plugin view.

Like the TUI it only collects input, calls the core and shows results; ``ludex.plugin_views`` supplies the plugin
drawer entries and their confirmed row actions.
"""
from __future__ import annotations

import html
import os
import sqlite3
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QSplitter, QStackedWidget, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget,
)

from ludex.accounts import get_account
from ludex.acquire import download_game
from ludex.errors import LudexError
from ludex.find import find_games, owned_keys
from ludex.game_settings import default_download_dir, get_download_dir, get_prefix_root, set_download_dir
from ludex.installed import installed_keys
from ludex.jobs import Job, get_job, list_jobs, progress_line, stop_job
from ludex.launch import install_game, launch_game, open_url
from ludex.library import get_game, list_games
from ludex.loader import load_providers
from ludex.metadata import cached_match, cached_metadata, game_metadata, get_auto_details, get_auto_match
from ludex.paths import StatePaths, state_paths
from ludex.playtime import Played, describe_played, epoch, play_stats
from ludex.plugin_views import list_views
from ludex.plugins import Provider
from ludex.refresh import get_auto_refresh, refresh_all
from ludex.storage import connect, writer_lock

from .settings import SettingsPage
from .views import ViewPage
from .work import run_async

PAGE_LIMIT = 500
DETAILS_DELAY_MS = 600


def _table(columns: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(columns)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    return table


def _fill(table: QTableWidget, rows: list[tuple[object, tuple[str, ...]]]) -> None:
    """Rows are ``(key, cells)``; the key rides on the first cell."""
    table.setRowCount(len(rows))
    for r, (key, cells) in enumerate(rows):
        for c, cell in enumerate(cells):
            item = QTableWidgetItem(cell)
            if c == 0:
                item.setData(Qt.ItemDataRole.UserRole, key)
            table.setItem(r, c, item)


def _selected_key(table: QTableWidget) -> object | None:
    rows = table.selectionModel().selectedRows()
    return table.item(rows[0].row(), 0).data(Qt.ItemDataRole.UserRole) if rows else None


def _select_key(table: QTableWidget, key: object | None) -> None:
    for r in range(table.rowCount()):
        if table.item(r, 0).data(Qt.ItemDataRole.UserRole) == key:
            table.selectRow(r)
            return


class MainWindow(QMainWindow):
    def __init__(
        self,
        paths: StatePaths,
        sources: Mapping[str, Provider],
        installed: Callable[[], set[tuple[str, str]]],
        config_for: Callable[[str, str], Mapping[str, str]],
        played: Callable[[sqlite3.Connection], Mapping[int, Played]],
        prefix_root: Path,
        *,
        auto_refresh: bool = True,
    ) -> None:
        super().__init__()
        self.setWindowTitle("ludex")
        self.resize(1100, 680)
        self._paths, self._sources, self._installed = paths, sources, installed
        self._config_for, self._played_of, self._prefix_root = config_for, played, prefix_root
        self._conn = connect(paths.database)
        self._keys: set[tuple[str, str]] = set()
        self._played: Mapping[int, Played] = {}
        self._hits: dict[str, dict] = {}
        self._tried: set[int] = set()
        self._refreshing = False
        self._jobs_seen: dict[int, str] = {}
        self._page_of: list[QWidget | None] = []  # drawer row -> page (None: a separator)
        self._filters: dict[QWidget, QLineEdit] = {}

        self.drawer = QListWidget()
        self.drawer.setMaximumWidth(260)
        self.pages = QStackedWidget()
        self.detail = QTextBrowser()
        self.detail.setOpenLinks(False)
        self.detail.setMinimumWidth(260)
        self.status = QLabel()
        splitter = QSplitter()
        splitter.addWidget(self.drawer)
        splitter.addWidget(self.pages)
        splitter.addWidget(self.detail)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([170, 650, 280])
        central = QWidget()
        column = QVBoxLayout(central)
        column.addWidget(splitter, 1)
        column.addWidget(self.status)
        self.setCentralWidget(central)

        self.owned, self.owned_table = self._library_page("Owned", installed_only=False)
        self.installed_page, self.installed_table = self._library_page("Installed", installed_only=True)
        self._search_page()
        self._jobs_page()
        self.settings = SettingsPage(paths, self._conn, sources, self.notify, self._reload_local, prefix_root)
        self._add("Settings", self.settings)
        self.view_pages: dict[tuple[str, str], ViewPage] = {}
        for index, (key, view) in enumerate(list_views(sources)):
            page = ViewPage(paths, sources, key, view, self.notify, self._reload_local)
            self.view_pages[(key, view.id)] = page
            self._add(view.title, page, separator=index == 0)
        self.drawer.currentRowChanged.connect(self._opened)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_jobs)
        self._poll.start(2000)
        self._details_timer = QTimer(self)
        self._details_timer.setSingleShot(True)
        self._details_timer.timeout.connect(lambda: self._start_details(self._details_game))
        self._details_game = 0
        self.drawer.setCurrentRow(0)
        self._reload_local()
        if auto_refresh and get_auto_refresh(self._conn):
            self._start_refresh(quiet=True)

    # --- chrome ---------------------------------------------------------------------------------------------

    def _add(self, label: str, page: QWidget, *, separator: bool = False) -> None:
        if separator:
            line = QListWidgetItem("— plugins —")
            line.setFlags(Qt.ItemFlag.NoItemFlags)
            self.drawer.addItem(line)
            self._page_of.append(None)
        item = QListWidgetItem(label)  # plain text: a plugin title is not markup
        self.drawer.addItem(item)
        self.pages.addWidget(page)
        self._page_of.append(page)

    def notify(self, text: str, error: bool = False) -> None:
        self.status.setText(("Error: " if error else "") + text)
        self.status.setToolTip(text)

    def _opened(self, row: int) -> None:
        page = self._page_of[row] if 0 <= row < len(self._page_of) else None
        if page is None:
            return
        self.pages.setCurrentWidget(page)
        self.detail.clear()
        if page is self.owned:
            self._on_game_selected(self.owned_table)
        elif page is self.installed_page:
            self._on_game_selected(self.installed_table)
        elif page is self.jobs_page:
            self._poll_jobs()
            self._show_job()
        elif page is self.search_page:
            self._show_hit()

    def active(self) -> QWidget | None:
        return self.pages.currentWidget()

    # --- library --------------------------------------------------------------------------------------------

    def _library_page(self, title: str, installed_only: bool) -> tuple[QWidget, QTableWidget]:
        page = QWidget()
        filter_box = QLineEdit()
        filter_box.setPlaceholderText("Filter by title")
        filter_box.textChanged.connect(lambda _: self._reload())
        table = _table(["", "Title", "Stores"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.itemSelectionChanged.connect(lambda t=table: self._on_game_selected(t))
        table.itemDoubleClicked.connect(lambda _: self._launch() if installed_only else self._install())
        launch, install, stop, refresh = QPushButton("Launch"), QPushButton("Install"), QPushButton("Stop"), QPushButton("Refresh")
        launch.clicked.connect(self._launch)
        install.clicked.connect(self._install)
        stop.clicked.connect(self._stop_game)
        refresh.clicked.connect(lambda: (self._reload_local(), self._start_refresh(quiet=False)))
        bar = QHBoxLayout()
        bar.addWidget(filter_box, 1)
        for button in ((launch,) if installed_only else (install,)) + (stop, refresh):
            bar.addWidget(button)
        layout = QVBoxLayout(page)
        layout.addLayout(bar)
        layout.addWidget(table)
        self._filters[page] = filter_box
        self._add(title, page)
        return page, table

    def _reload_local(self) -> None:
        self._keys = self._installed()
        self._played = self._played_of(self._conn)
        self._reload()

    def _reload(self) -> None:
        installed_ids: set[int] = set()
        counts = []
        for name, page, table, only in (("installed", self.installed_page, self.installed_table, self._keys), ("owned", self.owned, self.owned_table, None)):
            query = self._filters[page].text().strip() or None
            games = list_games(self._conn, query=query, only=only, limit=PAGE_LIMIT, fuzzy=True)
            if name == "installed":
                installed_ids = {g["id"] for g in games}
            keep = _selected_key(table)
            table.blockSignals(True)
            _fill(table, [(g["id"], ("●" if g["id"] in installed_ids else "", g["title"], ", ".join(g["stores"]))) for g in games])
            table.blockSignals(False)
            _select_key(table, keep)
            counts.append(f"{len(games)}{'+' if len(games) == PAGE_LIMIT else ''} {name}")
        self.notify(", ".join(reversed(counts)))
        for table in (self.owned_table, self.installed_table):
            if table is self.active_table():
                self._on_game_selected(table)

    def active_table(self) -> QTableWidget | None:
        return {self.owned: self.owned_table, self.installed_page: self.installed_table}.get(self.active())  # type: ignore[arg-type]

    def _current_game(self) -> int | None:
        table = self.active_table()
        key = _selected_key(table) if table is not None else None
        return int(key) if key is not None else None

    def _on_game_selected(self, table: QTableWidget) -> None:
        if table is not self.active_table():
            return
        game_id = _selected_key(table)
        if game_id is None:
            return
        self._show_game(int(game_id))

    def _show_game(self, game_id: int, note: str | None = None) -> None:
        game = get_game(self._conn, game_id)
        lines = [f"<h3>{html.escape(game['title'])}</h3>"]
        for o in game["ownership"]:
            state = "removed" if o["removed"] else "owned"
            lines.append(f"<p>{html.escape(o['store'])}:{html.escape(str(o['store_id']))} &nbsp;<i>{html.escape(str(o['account']))}</i> &nbsp;<b>{state}</b></p>")
        if any((o["store"], str(o["store_id"])) in self._keys for o in game["ownership"]):
            lines.append("<p><b>● installed</b></p>")
        if (played := self._played.get(game_id)) is not None:
            lines.append(f"<p>played {html.escape(describe_played(played))}</p>")
        found = next((m for o in game["ownership"] if (m := cached_metadata(self._conn, o["store"], str(o["store_id"])))), None)
        if found is not None:
            if found.description:
                lines.append(f"<p>{html.escape(found.description)}</p>")
            for label, values in (("genres", found.genres), ("by", found.developers), ("released", (found.released,) if found.released else ())):
                if values:
                    lines.append(f"<p>{label}: {html.escape(', '.join(values))}</p>")
            matched = next((m for o in game["ownership"] if (m := cached_match(self._conn, o["store"], str(o["store_id"])))), None)
            if matched:
                lines.append(f"<p><i>matched to {html.escape(matched['plugin'])}: {html.escape(matched['title'])}</i></p>")
        running = list_jobs(self._conn, None, game_id, running=True, limit=1)
        if running:
            what = f"installing {progress_line(running[0])}" if running[0].kind == "install" else f"running since {running[0].started_at}"
            lines.append(f"<p><b>{html.escape(what)}</b></p>")
        if note:
            lines.append(f"<p>{html.escape(note)}</p>")
        self.detail.setHtml("".join(lines))
        if found is None and note is None:
            self._queue_details(game_id)

    def _queue_details(self, game_id: int) -> None:
        """Ask for details once the selection rests on a game (once per game per run)."""
        self._details_timer.stop()
        if not get_auto_details(self._conn) or game_id in self._tried:
            return
        self._details_game = game_id
        self._details_timer.start(DETAILS_DELAY_MS)

    def _start_details(self, game_id: int) -> None:
        if game_id != self._current_game() or game_id in self._tried:
            return
        self._tried.add(game_id)
        match, database, sources = get_auto_match(self._conn), self._paths.database, self._sources

        def work() -> bool:
            conn = connect(database)
            try:
                with writer_lock(self._paths.import_lock):
                    return game_metadata(conn, sources, game_id, False, match) is not None
            finally:
                conn.close()

        def done(found: object, error: str | None) -> None:
            if error is not None:
                self.notify(f"details: {error}", True)
            elif found and game_id == self._current_game():
                self._show_game(game_id)

        run_async(work, done)

    def _launch(self) -> None:
        self._start_game(launch_game, "launch", "launched from")

    def _install(self) -> None:
        if self.active() is self.search_page:
            self._install_hit()
            return
        self._start_game(install_game, "install", "installed from")

    def _start_game(self, call: Callable, verb: str, phrase: str) -> None:
        game_id = self._current_game()
        if game_id is None:
            return
        logs = self._paths.database.parent / "logs"
        extra = (get_prefix_root(self._conn, self._prefix_root), logs) if verb == "launch" else (logs,)
        try:
            try:
                target, job = call(self._conn, self._sources, game_id, None, self._config_for, *extra)
            except LudexError as exc:
                if exc.code != f"{verb}_ambiguous":
                    raise
                store = exc.message.split(phrase)[1].split(";")[0].split(", ")[0]  # several stores: the first, alphabetically
                target, job = call(self._conn, self._sources, game_id, store, self._config_for, *extra)
        except LudexError as exc:
            self.notify(exc.message, True)
            return
        self.notify(f"{verb}ing {target}" if job is None else f"{verb}ing {target} in the background")
        if job is not None:
            self._jobs_seen[job.id] = job.state
            self._show_game(game_id)

    def _stop_game(self) -> None:
        game_id = self._current_game()
        running = list_jobs(self._conn, None, game_id, running=True, limit=1) if game_id is not None else []
        if running:
            self._stop(running[0].id)

    def _stop(self, job_id: int) -> None:
        database = self._paths.database

        def work() -> Job:
            conn = connect(database)  # stopping waits for the process
            try:
                return stop_job(conn, job_id)
            finally:
                conn.close()

        def done(job: object, error: str | None) -> None:
            self.notify(error if error else f"stopped {job.title}", error is not None)  # type: ignore[union-attr]
            self._poll_jobs()

        run_async(work, done)

    # --- refresh --------------------------------------------------------------------------------------------

    def _start_refresh(self, quiet: bool) -> None:
        if self._refreshing:
            if not quiet:
                self.notify("already refreshing")
            return
        self._refreshing = True
        self.notify("refreshing accounts…")
        paths, sources = self._paths, self._sources

        def work() -> list:
            conn = connect(paths.database)
            try:
                with writer_lock(paths.import_lock):
                    return refresh_all(paths, conn, sources)
            finally:
                conn.close()

        def done(results: list | None, error: str | None) -> None:
            self._refreshing = False
            self._reload_local()
            if error:
                self.notify(f"refresh skipped: {error}", True)
                return
            problems = [f"{r.ref}: {r.error}" for r in results or [] if r.error]
            added, restored, removed = (sum(getattr(r, f) for r in results or []) for f in ("added", "restored", "removed"))
            if problems:
                self.notify("; ".join(problems), True)
            elif added or restored or removed:
                self.notify(f"refreshed: {added} new, {restored} restored, {removed} removed")
            elif not quiet:
                self.notify("refreshed: no changes")

        run_async(work, done)

    # --- search ---------------------------------------------------------------------------------------------

    def _search_page(self) -> None:
        self.search_page = QWidget()
        self.query_box = QLineEdit()
        self.query_box.setPlaceholderText("Search the stores, then press Enter")
        self.query_box.returnPressed.connect(self._search)
        self.install_hit_button = QPushButton("Install")
        self.install_hit_button.clicked.connect(self._install_hit)
        self.hits_table = _table(["Title", "Store", "Price", "Owned"])
        self.hits_table.itemSelectionChanged.connect(self._show_hit)
        bar = QHBoxLayout()
        bar.addWidget(self.query_box, 1)
        bar.addWidget(self.install_hit_button)
        layout = QVBoxLayout(self.search_page)
        layout.addLayout(bar)
        layout.addWidget(self.hits_table)
        self._add("Search", self.search_page)

    def _search(self) -> None:
        query = self.query_box.text().strip()
        if not query:
            return
        self.notify(f"searching for {query}…")
        owned, sources = owned_keys(self._conn), self._sources
        run_async(lambda: find_games(sources, query, owned), lambda result, error: self._searched(query, result, error))

    def _searched(self, query: str, result: tuple | None, error: str | None) -> None:
        if error is not None:
            self.notify(error, True)
            return
        hits, problems = result  # type: ignore[misc]
        self._hits = {f"{h['store']}:{h['store_id']}": h for h in hits}
        _fill(self.hits_table, [(f"{h['store']}:{h['store_id']}", (h["title"], h["store"], str(h.get("price") or ""), "yes" if h["owned"] else "")) for h in hits])
        text = f"{len(hits)} results for {query}"
        if problems:
            text += "; " + "; ".join(f"{name}: {reason}" for name, reason in problems.items())
        self.notify(text, bool(problems))

    def _hit(self) -> dict | None:
        key = _selected_key(self.hits_table)
        return self._hits.get(str(key)) if key is not None else None

    def _show_hit(self) -> None:
        hit = self._hit()
        if hit is None or self.active() is not self.search_page:
            return
        lines = [f"<h3>{html.escape(hit['title'])}</h3>", f"<p>{html.escape(hit['store'])}:{html.escape(str(hit['store_id']))}</p>"]
        if hit.get("price"):
            lines.append(f"<p>{html.escape(str(hit['price']))}</p>")
        if hit["owned"]:
            lines.append("<p><b>you own this</b></p>")
        self.detail.setHtml("".join(lines))

    def _install_hit(self) -> None:
        hit = self._hit()
        if hit is None:
            return
        plugin = self._sources.get(hit["store"])
        if plugin is None or plugin.acquire is None:  # a store with its own client: open it
            try:
                open_url(plugin.install_url(hit["store_id"]) if plugin and plugin.install_url else hit["url"], f"the {hit['store']} client")
            except LudexError as exc:
                self.notify(exc.message, True)
            return
        folder = QFileDialog.getExistingDirectory(self, f"Download {hit['title']} to", str(get_download_dir(self._conn, default_download_dir())))
        if not folder:
            return
        try:
            with writer_lock(self._paths.import_lock):
                set_download_dir(self._conn, folder)
            job = download_game(
                self._conn, self._sources, hit["store"], hit["store_id"], hit["title"],
                get_download_dir(self._conn, default_download_dir()), self._paths.database.parent / "logs",
            )
        except LudexError as exc:
            self.notify(exc.message, True)
            return
        self._jobs_seen[job.id] = job.state
        self.notify(f"downloading {hit['title']} in the background; see Jobs")

    # --- jobs -----------------------------------------------------------------------------------------------

    def _jobs_page(self) -> None:
        self.jobs_page = QWidget()
        self.jobs_table = _table(["Kind", "State", "Title"])
        self.jobs_table.itemSelectionChanged.connect(self._show_job)
        stop = QPushButton("Stop")
        stop.clicked.connect(self._stop_selected_job)
        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(stop)
        layout = QVBoxLayout(self.jobs_page)
        layout.addLayout(bar)
        layout.addWidget(self.jobs_table)
        self._add("Jobs", self.jobs_page)

    def _selected_job(self) -> Job | None:
        key = _selected_key(self.jobs_table)
        try:
            return get_job(self._conn, int(key)) if key is not None else None
        except LudexError:
            return None

    def _stop_selected_job(self) -> None:
        job = self._selected_job()
        if job is not None and job.state == "running":
            self._stop(job.id)

    def _poll_jobs(self) -> None:
        jobs = sorted(list_jobs(self._conn, limit=50), key=lambda j: (j.state != "running", -j.id))
        for job in jobs:
            was = self._jobs_seen.get(job.id)
            if was == "running" and job.state != "running":
                self.notify(f"{job.title}: {job.state}", job.state == "failed")
                self._reload_local()
            self._jobs_seen[job.id] = job.state
        running = sum(j.state == "running" for j in jobs)
        item = self.drawer.item(self._page_of.index(self.jobs_page))
        item.setText(f"Jobs ({running})" if running else "Jobs")
        if self.active() is self.jobs_page:
            keep = _selected_key(self.jobs_table)
            self.jobs_table.blockSignals(True)
            _fill(self.jobs_table, [(j.id, (j.kind, j.state, j.title + (f"  {progress_line(j)}" if j.state == "running" else ""))) for j in jobs])
            self.jobs_table.blockSignals(False)
            _select_key(self.jobs_table, keep)
            self._show_job()

    def _show_job(self) -> None:
        job = self._selected_job()
        if job is None or self.active() is not self.jobs_page:
            return
        lines = [f"<h3>{html.escape(job.title)}</h3>", f"<p>{html.escape(job.kind)} {html.escape(job.target)}</p>", f"<p>{html.escape(job.state)} · started {html.escape(job.started_at)}</p>"]
        if job.state == "running":
            lines.append(f"<p>{html.escape(progress_line(job))}</p>")
        lines.append(f"<p>log: {html.escape(str(job.log))}</p>")
        self.detail.setHtml("".join(lines))

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        self._poll.stop()
        self._details_timer.stop()
        self._conn.close()
        super().closeEvent(event)


def main() -> int:
    """Run the desktop window on the user's library; ``ludex gui`` and the ``ludex-gui`` script land here."""
    sources, _ = load_providers()
    paths = state_paths()
    previous_umask = os.umask(0o077)
    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
        window = MainWindow(
            paths, sources, lambda: installed_keys(paths, sources)[0],
            lambda store, account: get_account(paths, f"{store}:{account}").config,
            lambda conn: play_stats(paths, sources, conn)[0],
            paths.root / "prefixes",
        )
        window.show()
        code = app.exec()
    finally:
        os.umask(previous_umask)
    return code
