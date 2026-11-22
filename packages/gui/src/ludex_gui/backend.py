"""The object QML talks to: library, game page, search, jobs, covers, plus the settings and plugin-view controllers.

Like the TUI it only collects input, calls the core and shows results. Blocking core calls run on pool threads
(``work.run_async``) with their own SQLite connections; this object and its connection live on the UI thread.
"""
from __future__ import annotations

import sqlite3
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QCoreApplication, QModelIndex, QObject, QPersistentModelIndex, Qt, QTimer, QUrl, Signal, Slot

from ludex.acquire import download_game
from ludex.artwork import cached_cover, fetch_cover
from ludex.errors import LudexError
from ludex.details import fetch_missing_details, games_without_details
from ludex.find import find_games, owned_keys
from ludex.executables import find_executables
from ludex.game_settings import (
    default_download_dir, format_arguments, format_environment, get_download_dir, get_prefix_root, get_settings, parse_arguments,
    parse_environment, set_download_dir, update_settings,
)
from ludex.jobs import Job, list_jobs, progress_line, stop_job
from ludex.launch import install_game, launch_game, open_url
from ludex.library import get_game, list_games, list_genres
from ludex.metadata import (
    cached_match, cached_metadata, choose_match, clear_match, default_query, game_metadata, get_auto_details, get_auto_match,
    match_candidates,
)
from ludex.paths import StatePaths
from ludex.playtime import Played, describe_played, epoch
from ludex.plugin_views import list_views
from ludex.plugins import Provider
from ludex.refresh import get_auto_refresh, refresh_all
from ludex.runners import find_runners
from ludex.storage import connect, writer_lock

from .settings import SettingsController
from .views import ViewController, plain
from .work import run_async

PAGE = 500  # the core's page size
MAX_GAMES = 20000
COVERS_AT_A_TIME = 2
SORTS = ("title", "recent", "playtime", "installed")
_ROLES = ("gameId", "title", "stores", "installed", "played", "coverUrl")


class GameModel(QAbstractListModel):
    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[dict[str, Any]] = []

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802 (Qt)
        return {Qt.ItemDataRole.UserRole + 1 + i: name.encode() for i, name in enumerate(_ROLES)}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: N802 (Qt)
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        number = role - Qt.ItemDataRole.UserRole - 1
        if not index.isValid() or not 0 <= number < len(_ROLES):
            return None
        return self._rows[index.row()][_ROLES[number]]

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def set_cover(self, game_id: int, url: str) -> None:
        for i, row in enumerate(self._rows):
            if row["gameId"] == game_id and row["coverUrl"] != url:
                row["coverUrl"] = url
                self.dataChanged.emit(self.index(i), self.index(i), [Qt.ItemDataRole.UserRole + 1 + _ROLES.index("coverUrl")])

    def row(self, number: int) -> dict[str, Any]:
        return self._rows[number]


def _folder(text: str) -> str:
    """A path from a QML folder dialog (a ``file://`` URL) or typed text."""
    return QUrl(text).toLocalFile() if text.startswith("file:") else text


class Backend(QObject):
    statusChanged = Signal()
    libraryChanged = Signal()
    currentChanged = Signal()
    hitsChanged = Signal()
    jobsChanged = Signal()
    busyChanged = Signal()
    matchesChanged = Signal()
    detailsChanged = Signal()

    def __init__(
        self,
        paths: StatePaths,
        sources: Mapping[str, Provider],
        installed: Callable[[], set[tuple[str, str]]],
        config_for: Callable[[str, str], Mapping[str, str]],
        played: Callable[[sqlite3.Connection], Mapping[int, Played]],
        prefix_root: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths, self._sources, self._installed = paths, sources, installed
        self._config_for, self._played_of, self._prefix_root = config_for, played, prefix_root
        self._conn = connect(paths.database)
        self.requested_console: bool | None = None  # set by switchMode; app.main restarts into that mode
        self._keys: set[tuple[str, str]] = set()
        self._played: Mapping[int, Played] = {}
        self._filter = ("", "", False, "title", "")
        self._status, self._status_error = "", False
        self._stores: list[str] = []
        self._genres: list[dict[str, Any]] = []
        self._missing = 0
        self._fetching = False
        self._fetch_progress = (0, 0)
        self._fetch_stop = threading.Event()
        self._count = 0
        self._current: dict[str, Any] = {}
        self._hits: dict[str, dict[str, Any]] = {}
        self._hit_rows: list[dict[str, Any]] = []
        self._searching = False
        self._matches: list[tuple[str, Any]] = []
        self._matching = False
        self._refreshing = False
        self._jobs: list[dict[str, Any]] = []
        self._running_jobs = 0
        self._jobs_seen: dict[int, str] = {}
        self._covers: dict[int, str] = {}
        self._cover_tried: set[int] = set()
        self._cover_queue: list[int] = []
        self._cover_running = 0
        self._cover_complaints: set[str] = set()
        self._details_tried: set[int] = set()
        self.games = GameModel(self)
        self.settings = SettingsController(paths, self._conn, sources, prefix_root, self)
        self.settings.notice.connect(self.notify)
        self.settings.libraryChanged.connect(self.reload)
        self.settings.accountsChanged.connect(lambda: self.startRefresh(True))
        self._views = [ViewController(paths, sources, key, view, self) for key, view in list_views(sources)]
        for page in self._views:
            page.notice.connect(self.notify)
            page.actionDone.connect(self.reload)
        self._poll = QTimer(self)
        self._poll.timeout.connect(self.pollJobs)
        self._poll.start(2000)

    # --- properties -----------------------------------------------------------------------------------------

    def _get_status(self) -> str:
        return self._status

    def _get_status_error(self) -> bool:
        return self._status_error

    def _get_stores(self) -> list[str]:
        return self._stores

    def _get_genres(self) -> list[dict[str, Any]]:
        return self._genres

    def _get_missing(self) -> int:
        return self._missing

    def _get_fetching(self) -> str:
        done, total = self._fetch_progress
        return f"Fetching details {done}/{total}" if self._fetching else ""

    def _get_count(self) -> int:
        return self._count

    def _get_current(self) -> dict[str, Any]:
        return self._current

    def _get_hits(self) -> list[dict[str, Any]]:
        return self._hit_rows

    def _get_jobs(self) -> list[dict[str, Any]]:
        return self._jobs

    def _get_running_jobs(self) -> int:
        return self._running_jobs

    def _get_views(self) -> list[QObject]:
        return self._views

    def _get_games(self) -> QObject:
        return self.games

    def _get_settings(self) -> QObject:
        return self.settings

    def _get_matches(self) -> list[dict[str, Any]]:
        return [{"plugin": plugin, "title": hit.title, "price": str(hit.price or ""), "url": hit.url} for plugin, hit in self._matches]

    def _get_matching(self) -> bool:
        return self._matching

    def _get_can_match(self) -> bool:
        return any(p.match and p.metadata for p in self._sources.values())

    def _get_busy(self) -> bool:
        return self._refreshing

    def _get_searching(self) -> bool:
        return self._searching

    status = Property(str, _get_status, notify=statusChanged)
    statusError = Property(bool, _get_status_error, notify=statusChanged)
    stores = Property("QVariantList", _get_stores, notify=libraryChanged)
    count = Property(int, _get_count, notify=libraryChanged)
    genres = Property("QVariantList", _get_genres, notify=libraryChanged)
    missingDetails = Property(int, _get_missing, notify=detailsChanged)
    fetchingDetails = Property(str, _get_fetching, notify=detailsChanged)
    current = Property("QVariantMap", _get_current, notify=currentChanged)
    hits = Property("QVariantList", _get_hits, notify=hitsChanged)
    jobs = Property("QVariantList", _get_jobs, notify=jobsChanged)
    runningJobs = Property(int, _get_running_jobs, notify=jobsChanged)
    views = Property("QVariantList", _get_views, constant=True)
    gameModel = Property(QObject, _get_games, constant=True)
    settingsController = Property(QObject, _get_settings, constant=True)
    refreshing = Property(bool, _get_busy, notify=busyChanged)
    matches = Property("QVariantList", _get_matches, notify=matchesChanged)
    matching = Property(bool, _get_matching, notify=matchesChanged)
    canMatch = Property(bool, _get_can_match, constant=True)
    searching = Property(bool, _get_searching, notify=hitsChanged)

    @Slot(bool)
    def switchMode(self, console: bool) -> None:  # noqa: N802 (Qt)
        """Ask for the launcher to restart in console (fullscreen, controller) or desktop mode."""
        self.requested_console = console
        QCoreApplication.quit()

    @Slot(str, bool)
    def notify(self, text: str, error: bool = False) -> None:
        self._status, self._status_error = plain(text), error
        self.statusChanged.emit()

    # --- library --------------------------------------------------------------------------------------------

    def _list(self, **kw: Any) -> list[dict[str, Any]]:
        games: list[dict[str, Any]] = []
        while len(games) < MAX_GAMES:
            page = list_games(self._conn, limit=PAGE, offset=len(games), **kw)
            games += page
            if len(page) < PAGE:
                break
        return games

    @Slot()
    def reload(self) -> None:
        self._keys = self._installed()
        self._played = self._played_of(self._conn)
        self._apply()

    @Slot(str, str, bool, str, str)
    def setFilter(self, query: str, store: str, installed_only: bool, sort: str, genre: str) -> None:
        self._filter = (query, store, installed_only, sort if sort in SORTS else "title", genre)
        self._apply()

    def _apply(self) -> None:
        query, store, installed_only, sort, genre = self._filter
        everything = self._list()
        stores = sorted({s for g in everything for s in g["stores"]})
        installed = {g["id"] for g in self._list(only=self._keys)}
        order = None
        if sort == "recent":
            order = {i: epoch(p.last_played) for i, p in self._played.items() if p.last_played}
        elif sort == "playtime":
            order = {i: p.minutes for i, p in self._played.items() if p.minutes}
        kw: dict[str, Any] = {"order": order} if order is not None else {}
        if query.strip():
            kw.update(query=query.strip(), fuzzy=True)
        if store:
            kw["store"] = store
        if genre:
            kw["genre"] = genre
        games = self._list(**kw) if kw or installed_only else everything
        if installed_only:
            games = [g for g in games if g["id"] in installed]
        if sort == "installed":
            games = sorted(games, key=lambda g: g["id"] not in installed)
        rows = [
            {
                "gameId": g["id"], "title": g["title"], "stores": ", ".join(g["stores"]), "installed": g["id"] in installed,
                "played": describe_played(self._played[g["id"]]) if g["id"] in self._played else "",
                "coverUrl": self._covers.get(g["id"], ""),
            }
            for g in games
        ]
        self.games.set_rows(rows)
        self._stores, self._count = stores, len(rows)
        self._genres = [{"genre": name, "games": count} for name, count in list_genres(self._conn)]
        self._missing = len(games_without_details(self._conn))
        self.libraryChanged.emit()
        self.detailsChanged.emit()
        if self._current:
            self.openGame(int(self._current["gameId"]), quiet=True)

    # --- covers ---------------------------------------------------------------------------------------------

    @Slot(int)
    def requestCover(self, game_id: int) -> None:
        """Paint the cover at once when it is local; otherwise queue a fetch if the user allowed contacting the stores."""
        if game_id in self._covers or game_id in self._cover_tried:
            return
        try:
            path = cached_cover(self._paths, self._conn, game_id)
        except LudexError:
            return
        if path is not None:
            self._set_cover(game_id, path)
            return
        if not get_auto_details(self._conn):
            return
        self._cover_tried.add(game_id)
        self._cover_queue.append(game_id)
        self._pump_covers()

    @Slot(int)
    def cancelCover(self, game_id: int) -> None:
        """The card left the screen before its fetch started: forget the request so it is asked again when seen."""
        if game_id in self._cover_queue:
            self._cover_queue.remove(game_id)
            self._cover_tried.discard(game_id)

    def _set_cover(self, game_id: int, path: Path) -> None:
        url = QUrl.fromLocalFile(str(path)).toString()
        self._covers[game_id] = url
        self.games.set_cover(game_id, url)
        if self._current and self._current.get("gameId") == game_id:
            self._current = {**self._current, "coverUrl": url}
            self.currentChanged.emit()

    def _pump_covers(self) -> None:
        if self._cover_queue and not get_auto_details(self._conn):  # consent withdrawn: ask nothing more
            for game_id in self._cover_queue:
                self._cover_tried.discard(game_id)
            self._cover_queue.clear()
        while self._cover_queue and self._cover_running < COVERS_AT_A_TIME:
            game_id = self._cover_queue.pop(0)
            self._cover_running += 1
            paths, sources = self._paths, self._sources

            def work(game_id: int = game_id) -> Path | None:
                conn = connect(paths.database)
                try:
                    return fetch_cover(paths, conn, sources, game_id)
                finally:
                    conn.close()

            run_async(work, lambda result, error, game_id=game_id: self._cover_done(game_id, result, error))

    def _cover_done(self, game_id: int, path: Path | None, error: str | None) -> None:
        self._cover_running -= 1
        if path is not None:
            self._set_cover(game_id, path)
        elif error and error not in self._cover_complaints:
            self._cover_complaints.add(error)  # one notice per reason, never one per game
            self.notify(f"covers: {error}", True)
        self._pump_covers()

    # --- the game page --------------------------------------------------------------------------------------

    @Slot(int)
    def openGame(self, game_id: int, quiet: bool = False) -> None:
        try:
            game = get_game(self._conn, game_id)
        except LudexError as exc:
            self.notify(exc.message, True)
            return
        copies = [(o["store"], str(o["store_id"])) for o in game["ownership"]]
        found = next((m for store, store_id in copies if (m := cached_metadata(self._conn, store, store_id))), None)
        matched = next((m for store, store_id in copies if (m := cached_match(self._conn, store, store_id))), None)
        running = list_jobs(self._conn, None, game_id, running=True, limit=1)
        what = ""
        if running:
            what = f"installing {progress_line(running[0])}" if running[0].kind == "install" else f"running since {running[0].started_at}"
        live = [o for o in game["ownership"] if not o["removed"]]
        self._current = {
            "gameId": game_id,
            "title": game["title"],
            "ownership": [{"store": o["store"], "storeId": str(o["store_id"]), "account": str(o["account"]), "removed": bool(o["removed"])} for o in game["ownership"]],
            "stores": ", ".join(sorted({o["store"] for o in live})),
            "installed": any(c in self._keys for c in copies),
            "played": describe_played(self._played.get(game_id)),
            "coverUrl": self._covers.get(game_id, ""),
            "description": found.description or "" if found else "",
            "genres": ", ".join(found.genres) if found else "",
            "developers": ", ".join(found.developers) if found else "",
            "released": found.released or "" if found else "",
            "matched": f"{matched['plugin']}: {matched['title']}" if matched else "",
            "running": what,
        }
        self.currentChanged.emit()
        if not quiet:
            self.requestCover(game_id)
            if found is None:
                self._fetch_details(game_id)

    def _settings_copy(self, game_id: int) -> tuple[str, str, str, str]:
        """(store, store_id, account, title) of the copy whose launch settings apply: one a provider keeps in a folder."""
        game = get_game(self._conn, game_id)
        copies = sorted(
            (o["store"], str(o["store_id"]), str(o["account"])) for o in game["ownership"]
            if not o["removed"] and getattr(self._sources.get(o["store"]), "game_folder", None)
        )
        if not copies:
            raise LudexError("not_applicable", "launch options apply to games a plugin keeps in a folder (for example local games)")
        return (*copies[0], game["title"])

    @Slot(int, result="QVariantMap")
    def gameSettings(self, game_id: int) -> dict[str, Any]:
        """What the launch options form shows: the saved values, the Proton builds and the executables found in the folder."""
        try:
            store, store_id, account, title = self._settings_copy(game_id)
        except LudexError as exc:
            return {"available": False, "reason": exc.message}
        folder: Path | None = None
        try:
            folder = Path(self._sources[store].game_folder(self._config_for(store, account), store_id))
        except Exception:  # the folder only feeds the executable suggestions
            pass
        current = get_settings(self._conn, store, store_id)
        runners = [r.name for r in find_runners()]
        if current.runner and current.runner not in runners:
            runners.append(current.runner)
        return {
            "available": True, "title": title, "runner": current.runner or "", "runners": runners,
            "prefix": current.prefix or "", "defaultPrefix": str(self._prefix_root),
            "executable": current.executable or "", "candidates": [str(p) for p in find_executables(folder, title)] if folder is not None and folder.is_dir() else [],
            "args": format_arguments(current.args), "env": format_environment(current.env),
        }

    @Slot(int, "QVariantMap")
    def saveGameSettings(self, game_id: int, values: dict[str, Any]) -> None:
        """Replace the game's launch options with the form's; a blank value is unset."""
        try:
            store, store_id, _, title = self._settings_copy(game_id)
            with writer_lock(self._paths.import_lock):
                update_settings(
                    self._conn, store, store_id, clear=True,
                    runner=str(values.get("runner", "")).strip() or None,
                    prefix=str(values.get("prefix", "")).strip() or None,
                    executable=str(values.get("executable", "")).strip() or None,
                    args=parse_arguments(str(values.get("args", ""))),
                    env=parse_environment(str(values.get("env", ""))),
                )
        except LudexError as exc:
            self.notify(exc.message, True)
            return
        self.notify(f"saved launch options for {title}")

    @Slot(int, result=str)
    def matchQuery(self, game_id: int) -> str:
        """The title to start looking up: the folder name, cleaned."""
        try:
            return default_query(self._conn, game_id)
        except LudexError as exc:
            self.notify(exc.message, True)
            return ""

    @Slot(str)
    def findMatches(self, query: str) -> None:
        """Ask the database plugins for entries named ``query`` (the plugin sees the query)."""
        query = query.strip()
        if not query or self._matching:
            return
        self._matching = True
        self.matchesChanged.emit()
        sources = self._sources

        def done(result: tuple | None, error: str | None) -> None:
            self._matching = False
            self._matches = result[0] if result else []
            self.matchesChanged.emit()
            if error is not None:
                self.notify(f"match: {error}", True)
            elif result and result[1]:
                self.notify("; ".join(f"{name}: {reason}" for name, reason in result[1].items()), True)

        run_async(lambda: match_candidates(sources, query), done)

    @Slot()
    def clearMatches(self) -> None:
        self._matches = []
        self.matchesChanged.emit()

    @Slot(int, int)
    def chooseMatch(self, game_id: int, index: int) -> None:
        """Keep entry ``index`` of the last results as the game's title and details (or, with -1, forget the match)."""
        if index >= len(self._matches):
            return
        pick = self._matches[index] if index >= 0 else None
        paths, sources = self._paths, self._sources

        def work() -> str:
            conn = connect(paths.database)
            try:
                with writer_lock(paths.import_lock):
                    if pick is None:
                        return "match cleared" if clear_match(conn, game_id) else "no match to clear"
                    choose_match(conn, sources, game_id, pick[0], pick[1])
                    return f"matched to {pick[0]}: {pick[1].title}"
            finally:
                conn.close()

        def done(message: str | None, error: str | None) -> None:
            if error is not None:
                self.notify(f"match: {error}", True)
                return
            self.notify(message or "")
            self._details_tried.add(game_id)  # do not match it again by itself this run
            self._cover_tried.discard(game_id)
            self.reload()
            self.openGame(game_id, quiet=True)
            self.requestCover(game_id)

        run_async(work, done)

    @Slot()
    def closeGame(self) -> None:
        self._current = {}
        self.currentChanged.emit()

    def _fetch_details(self, game_id: int) -> None:
        """Ask for the details once per game per run, and only when the user allowed contacting the stores."""
        if not get_auto_details(self._conn) or game_id in self._details_tried:
            return
        self._details_tried.add(game_id)
        match, paths, sources = get_auto_match(self._conn), self._paths, self._sources

        def work() -> bool:
            conn = connect(paths.database)
            try:
                with writer_lock(paths.import_lock):
                    return game_metadata(conn, sources, game_id, False, match) is not None
            finally:
                conn.close()

        def done(found: object, error: str | None) -> None:
            if error is not None:
                self.notify(f"details: {error}", True)
            elif found:
                self._cover_tried.discard(game_id)  # a title match may have made a cover findable
                self.requestCover(game_id)
                if self._current.get("gameId") == game_id:
                    self.openGame(game_id, quiet=True)

        run_async(work, done)

    # --- launching ------------------------------------------------------------------------------------------

    @Slot(int)
    def launch(self, game_id: int) -> None:
        self._start_game(game_id, launch_game, "launch", "launched from")

    @Slot(int)
    def install(self, game_id: int) -> None:
        self._start_game(game_id, install_game, "install", "installed from")

    def _start_game(self, game_id: int, call: Callable, verb: str, phrase: str) -> None:
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
            self.openGame(game_id, quiet=True)

    @Slot(int)
    def stopGame(self, game_id: int) -> None:
        running = list_jobs(self._conn, None, game_id, running=True, limit=1)
        if running:
            self.stopJob(running[0].id)

    @Slot(int)
    def stopJob(self, job_id: int) -> None:
        database = self._paths.database

        def work() -> Job:
            conn = connect(database)  # stopping waits for the process
            try:
                return stop_job(conn, job_id)
            finally:
                conn.close()

        def done(job: Any, error: str | None) -> None:
            self.notify(error if error else f"stopped {job.title}", error is not None)
            self.pollJobs()

        run_async(work, done)

    # --- refresh --------------------------------------------------------------------------------------------

    def autoRefresh(self) -> None:
        """Refresh the accounts in the background when the user asked for that at start."""
        if get_auto_refresh(self._conn):
            self.startRefresh(True)

    @Slot(bool)
    def startRefresh(self, quiet: bool = False) -> None:
        if self._refreshing:
            if not quiet:
                self.notify("already refreshing")
            return
        self._refreshing = True
        self.busyChanged.emit()
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
            self.busyChanged.emit()
            self.reload()
            self.settings.reload()
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

    # --- details for every game -----------------------------------------------------------------------------

    @Slot()
    def fetchAllDetails(self) -> None:
        """Ask the stores and database plugins for the details of every game that has none (the user clicked for it)."""
        if self._fetching:
            return
        self._fetching, self._fetch_progress = True, (0, self._missing)
        self._fetch_stop.clear()
        self.detailsChanged.emit()
        paths, sources, match = self._paths, self._sources, get_auto_match(self._conn)

        def report(done: int, total: int) -> None:
            self._fetch_progress = (done, total)  # read by pollJobs on the UI thread

        def work() -> Any:
            conn = connect(paths.database)
            try:
                return fetch_missing_details(paths, conn, sources, match=match, report=report, should_stop=self._fetch_stop.is_set)
            finally:
                conn.close()

        def done(summary: Any, error: str | None) -> None:
            self._fetching = False
            self.reload()
            self.detailsChanged.emit()
            if error is not None:
                self.notify(f"details: {error}", True)
                return
            self.notify(
                f"details: {summary.fetched} games now have them, {summary.unavailable} have none to give, {summary.failed} failed"
                + ("; stopped" if summary.stopped else ""), summary.failed > 0,
            )

        run_async(work, done)

    @Slot()
    def stopFetchingDetails(self) -> None:
        self._fetch_stop.set()

    # --- search ---------------------------------------------------------------------------------------------

    @Slot(str)
    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            return
        self._searching = True
        self.hitsChanged.emit()
        self.notify(f"searching for {query}…")
        owned, sources = owned_keys(self._conn), self._sources
        run_async(lambda: find_games(sources, query, owned), lambda result, error: self._searched(query, result, error))

    def _searched(self, query: str, result: tuple | None, error: str | None) -> None:
        self._searching = False
        if error is not None:
            self.hitsChanged.emit()
            self.notify(error, True)
            return
        hits, problems = result  # type: ignore[misc]
        self._hits = {f"{h['store']}:{h['store_id']}": h for h in hits}
        self._hit_rows = [
            {"key": key, "title": h["title"], "store": h["store"], "storeId": str(h["store_id"]), "price": str(h.get("price") or ""), "owned": bool(h["owned"])}
            for key, h in self._hits.items()
        ]
        self.hitsChanged.emit()
        text = f"{len(hits)} results for {query}"
        if problems:
            text += "; " + "; ".join(f"{name}: {reason}" for name, reason in problems.items())
        self.notify(text, bool(problems))

    @Slot(str, result=bool)
    def hitNeedsFolder(self, key: str) -> bool:
        """Whether installing this hit downloads it (asks where); a store with its own client is opened instead."""
        hit = self._hits.get(key)
        plugin = self._sources.get(hit["store"]) if hit else None
        return plugin is not None and plugin.acquire is not None

    @Slot(result=str)
    def downloadFolder(self) -> str:
        return str(get_download_dir(self._conn, default_download_dir()))

    @Slot(str, result=str)
    def folderUrl(self, path: str) -> str:
        """A folder path as a file URL (escaped), for a folder dialog."""
        return QUrl.fromLocalFile(path).toString()

    @Slot(str, result=str)
    def localPath(self, url: str) -> str:
        """The folder path of a file URL a folder dialog returned."""
        return QUrl(url).toLocalFile()

    @Slot(str, str)
    def installHit(self, key: str, folder: str = "") -> None:
        hit = self._hits.get(key)
        if hit is None:
            return
        plugin = self._sources.get(hit["store"])
        if plugin is None or plugin.acquire is None:  # a store with its own client: open it
            try:
                open_url(plugin.install_url(hit["store_id"]) if plugin and plugin.install_url else hit["url"], f"the {hit['store']} client")
            except LudexError as exc:
                self.notify(exc.message, True)
            return
        target = _folder(folder)
        if not target:
            return
        try:
            with writer_lock(self._paths.import_lock):
                set_download_dir(self._conn, target)
            job = download_game(
                self._conn, self._sources, hit["store"], hit["store_id"], hit["title"],
                get_download_dir(self._conn, default_download_dir()), self._paths.database.parent / "logs",
            )
        except LudexError as exc:
            self.notify(exc.message, True)
            return
        self._jobs_seen[job.id] = job.state
        self.notify(f"downloading {hit['title']} in the background; see Downloads")

    # --- jobs -----------------------------------------------------------------------------------------------

    @Slot()
    def pollJobs(self) -> None:
        if self._fetching:
            self.detailsChanged.emit()  # the worker thread only stores its progress
        jobs = sorted(list_jobs(self._conn, limit=50), key=lambda j: (j.state != "running", -j.id))
        changed = False
        for job in jobs:
            was = self._jobs_seen.get(job.id)
            if was == "running" and job.state != "running":
                self.notify(f"{job.title}: {job.state}", job.state == "failed")
                changed = True
            self._jobs_seen[job.id] = job.state
        self._jobs = [
            {"id": j.id, "kind": j.kind, "state": j.state, "title": j.title, "started": j.started_at, "log": str(j.log),
             "progress": progress_line(j) if j.state == "running" else ""}
            for j in jobs
        ]
        self._running_jobs = sum(j.state == "running" for j in jobs)
        self.jobsChanged.emit()
        if changed:
            self.reload()

    @Slot()
    def closeDown(self) -> None:
        self._poll.stop()
        self._conn.close()
