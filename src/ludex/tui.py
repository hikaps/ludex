"""Terminal UI: browse, search and launch. All behavior comes from the core library.

ponytail: the library is read-only here (import with ``ludex import`` outside), no merge or review
screens, first 500 matches only; only launch settings and the prefix folder can be edited. Add
paging or more in-app maintenance when needed.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

from .errors import LudexError
from .game_settings import get_prefix_root, get_settings, set_prefix_root, update_settings
from .launch import install_game, launch_game, open_url
from .find import find_games, owned_keys
from .library import get_game, list_games
from .paths import StatePaths
from .plugins import Provider
from .runners import find_runners
from .storage import connect, writer_lock
from .switches import SWITCHES, get_switch, set_switch
from .tui_settings import GameSettingsScreen, SettingsScreen


class LudexApp(App[None]):
    TITLE = "ludex"
    CSS = "#detail { height: auto; max-height: 40%; padding: 0 1; border-top: solid $primary; }"
    BINDINGS = [
        Binding("1", "tab('owned')", "Owned"),
        Binding("2", "tab('installed')", "Installed"),
        Binding("3", "tab('search')", "Search stores"),
        Binding("slash", "search", "Filter"),
        Binding("enter", "launch", "Launch / open page"),
        Binding("escape", "clear", "Clear search", show=False),
        Binding("i", "install", "Install"),
        Binding("e", "edit", "Edit settings"),
        Binding("s", "settings", "Settings"),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        database: Path,
        sources: Mapping[str, Provider],
        installed: Callable[[], set[tuple[str, str]]] = lambda: set(),
        config_for: Callable[[str, str], Mapping[str, str]] | None = None,
        prefix_root: Path | None = None,
        lock: Path | None = None,
        paths: StatePaths | None = None,
    ) -> None:
        super().__init__()
        self._database = database
        self._sources = sources
        self._installed = installed
        self._config_for = config_for
        self._prefix_root = prefix_root
        self._lock = lock
        self._paths = paths
        self._keys: set[tuple[str, str]] = set()
        self._hits: dict[str, dict] = {}
        self._conn = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter your games; on the Search tab press Enter to search the stores (press / to focus)", id="filter")
        with TabbedContent(id="tabs"):
            with TabPane("Owned", id="owned"):
                yield DataTable(id="owned-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Installed", id="installed"):
                yield DataTable(id="installed-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Search", id="search"):
                yield DataTable(id="search-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._conn = connect(self._database)
        for table in self.query(DataTable):
            table.add_columns(*(("store", "title", "price", "owned") if table.id == "search-table" else ("id", "title", "stores")))
        self._table().focus()
        self.action_reload()

    def on_unmount(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _table(self) -> DataTable:
        return self.query_one(f"#{self.query_one(TabbedContent).active}-table", DataTable)

    def _reload(self) -> None:
        query = self.query_one(Input).value.strip() or None
        counts = []
        for name, only in (("owned", None), ("installed", self._keys)):
            games = list_games(self._conn, query=query, only=only, limit=500)
            table = self.query_one(f"#{name}-table", DataTable)
            table.clear()
            for game in games:
                table.add_row(str(game["id"]), game["title"], ", ".join(game["stores"]), key=str(game["id"]))
            counts.append(f"{len(games)}{'+' if len(games) == 500 else ''} {name}")
        self.sub_title = ", ".join(counts)
        self.query_one("#detail", Static).update("")

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id != "search":
            self._table().focus()

    def _current_id(self) -> int | None:
        table = self._table()
        if table.row_count == 0:
            return None
        return int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.query_one(TabbedContent).active == "search":
            query = event.value.strip()
            if query:
                self.sub_title = f"searching the stores for {query!r}..."
                owned = owned_keys(self._conn)
                self.run_worker(lambda: self._search(query, owned), thread=True, exclusive=True)
                return
        self._table().focus()

    def _search(self, query: str, owned: set[tuple[str, str]]) -> None:
        hits, problems = find_games(self._sources, query, owned)
        self.call_from_thread(self._show_hits, query, hits, problems)

    def _show_hits(self, query: str, hits: list, problems: dict[str, str]) -> None:
        self._hits = {str(i): h for i, h in enumerate(hits)}
        table = self.query_one("#search-table", DataTable)
        table.clear()
        for key, h in self._hits.items():
            table.add_row(h["store"], h["title"], h["price"] or "-", "yes" if h["owned"] else "", key=key)
        self.sub_title = f"{len(hits)} results for {query!r}"
        for name, reason in sorted(problems.items()):
            self.notify(f"{name}: {reason}", severity="warning")
        table.focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "search-table":
            hit = self._hits.get(event.row_key.value or "")
            self.query_one("#detail", Static).update(f"{hit['title']}\n  {hit['url']}" if hit else "")
            return
        game_id = self._current_id()
        if game_id is None:
            return
        game = get_game(self._conn, game_id)
        lines = [game["title"]] + [
            f"  {o['store']}:{o['store_id']}  account={o['account']}  {'removed' if o['removed'] else 'owned'}"
            for o in game["ownership"]
        ]
        self.query_one("#detail", Static).update("\n".join(lines))

    def action_tab(self, name: str) -> None:
        self.query_one(TabbedContent).active = name
        if name == "search":
            self.query_one(Input).focus()

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def action_clear(self) -> None:
        self.query_one(Input).value = ""
        self._table().focus()

    def action_reload(self) -> None:
        self._keys = self._installed()
        self._reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_launch()

    def _prefix(self) -> Path | None:
        return get_prefix_root(self._conn, self._prefix_root) if self._prefix_root else None

    def _write(self, change: Callable[[], object]) -> None:
        if self._lock is None:
            change()
            return
        with writer_lock(self._lock):
            change()

    def action_settings(self) -> None:
        default = self._prefix_root or Path.home() / "prefixes"
        keys = sorted(SWITCHES) if self._paths else []
        current = {key: get_switch(self._paths, key) for key in keys}

        def save(folder: str | None, wanted: dict[str, bool]) -> None:
            def apply() -> None:
                set_prefix_root(self._conn, folder)
                for key, on in wanted.items():
                    if on != current[key]:
                        set_switch(self._paths, self._conn, self._sources, key, on)

            self._write(apply)
            self.notify(f"saved settings; prefix folder: {get_prefix_root(self._conn, default)}")
            self.action_reload()

        self.push_screen(SettingsScreen(get_prefix_root(self._conn, default), default, current, save))

    def action_edit(self) -> None:
        game_id = None if self.query_one(TabbedContent).active == "search" else self._current_id()
        if game_id is None:
            return
        game = get_game(self._conn, game_id)
        copies = sorted(
            (o["store"], o["store_id"], o["account"]) for o in game["ownership"]
            if not o["removed"] and getattr(self._sources.get(o["store"]), "game_folder", None)
        )
        if not copies:
            self.notify("launch settings apply to games a provider keeps in a folder (for example local games)", severity="warning")
            return
        store, store_id, account = copies[0]
        folder = None
        try:
            folder = Path(self._sources[store].game_folder(self._config_for(store, account), store_id)) if self._config_for else None
        except Exception:  # the folder is only used for path completion
            pass

        def save(values: dict) -> None:
            self._write(lambda: update_settings(self._conn, store, store_id, clear=True, **values))
            self.notify(f"saved settings for {game['title']}")

        self.push_screen(
            GameSettingsScreen(
                game["title"], get_settings(self._conn, store, store_id), find_runners(),
                self._prefix_root or Path.home() / "prefixes", folder, save,
            )
        )

    def action_install(self) -> None:
        game_id = None if self.query_one(TabbedContent).active == "search" else self._current_id()
        if game_id is None:
            return
        try:
            try:
                target = install_game(self._conn, self._sources, game_id)
            except LudexError as exc:
                if exc.code != "install_ambiguous":
                    raise
                store = exc.message.split("installed from ")[1].split(";")[0].split(", ")[0]
                target = install_game(self._conn, self._sources, game_id, store)
            self.notify(f"asked the client to install {target}")
        except LudexError as exc:
            self.notify(exc.message, severity="error")

    def action_launch(self) -> None:
        if self.query_one(TabbedContent).active == "search":
            table = self.query_one("#search-table", DataTable)
            hit = self._hits.get(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value or "") if table.row_count else None
            if hit is not None:
                try:
                    open_url(hit["url"], "the store page")
                    self.notify(f"opened {hit['title']}")
                except LudexError as exc:
                    self.notify(exc.message, severity="error")
            return
        game_id = self._current_id()
        if game_id is None:
            return
        try:
            try:
                target = launch_game(self._conn, self._sources, game_id, None, self._config_for, self._prefix())
            except LudexError as exc:
                if exc.code != "launch_ambiguous":
                    raise
                # several stores can start it: use the first, alphabetically
                store = exc.message.split("launched from ")[1].split(";")[0].split(", ")[0]
                target = launch_game(self._conn, self._sources, game_id, store, self._config_for, self._prefix())
            self.notify(f"launching {target}")
        except LudexError as exc:
            self.notify(exc.message, severity="error")
