"""The object QML talks to: library, game page, search, jobs, covers, plus the settings and plugin-view controllers.

Like the TUI it only collects input, calls the core and shows results. Blocking core calls run on pool threads
(``work.run_async``) with their own SQLite connections; this object and its connection live on the UI thread.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QAbstractListModel, QModelIndex, QObject, QPersistentModelIndex, Qt, QTimer, QUrl, Signal, Slot

from ludex.acquire import download_game
from ludex.artwork import cached_cover, fetch_cover
from ludex.errors import LudexError
from ludex.find import find_games, owned_keys
from ludex.game_settings import default_download_dir, get_download_dir, get_prefix_root, set_download_dir
from ludex.jobs import Job, list_jobs, progress_line, stop_job
from ludex.launch import install_game, launch_game, open_url
from ludex.library import get_game, list_games
from ludex.metadata import cached_match, cached_metadata, game_metadata, get_auto_details, get_auto_match
from ludex.paths import StatePaths
from ludex.playtime import Played, describe_played, epoch
from ludex.plugin_views import list_views
from ludex.plugins import Provider
from ludex.refresh import get_auto_refresh, refresh_all
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
        self._keys: set[tuple[str, str]] = set()
        self._played: Mapping[int, Played] = {}
        self._filter = ("", "", False, "title")
        self._status, self._status_error = "", False
        self._stores: list[str] = []
        self._count = 0
        self._current: dict[str, Any] = {}
        self._hits: dict[str, dict[str, Any]] = {}
        self._hit_rows: list[dict[str, Any]] = []
        self._searching = False
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

    def _get_busy(self) -> bool:
        return self._refreshing

    def _get_searching(self) -> bool:
        return self._searching

    status = Property(str, _get_status, notify=statusChanged)
    statusError = Property(bool, _get_status_error, notify=statusChanged)
    stores = Property("QVariantList", _get_stores, notify=libraryChanged)
    count = Property(int, _get_count, notify=libraryChanged)
    current = Property("QVariantMap", _get_current, notify=currentChanged)
    hits = Property("QVariantList", _get_hits, notify=hitsChanged)
    jobs = Property("QVariantList", _get_jobs, notify=jobsChanged)
    runningJobs = Property(int, _get_running_jobs, notify=jobsChanged)
    views = Property("QVariantList", _get_views, constant=True)
    gameModel = Property(QObject, _get_games, constant=True)
    settingsController = Property(QObject, _get_settings, constant=True)
    refreshing = Property(bool, _get_busy, notify=busyChanged)
    searching = Property(bool, _get_searching, notify=hitsChanged)

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

    @Slot(str, str, bool, str)
    def setFilter(self, query: str, store: str, installed_only: bool, sort: str) -> None:
        self._filter = (query, store, installed_only, sort if sort in SORTS else "title")
        self._apply()

    def _apply(self) -> None:
        query, store, installed_only, sort = self._filter
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
        self.libraryChanged.emit()
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
