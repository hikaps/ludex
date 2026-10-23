"""Terminal UI: browse, search and launch. All behavior comes from the core library.

ponytail: the library is read-only here (import with ``ludex import`` outside), no merge or review
screens, first 500 matches only; only launch settings and the prefix folder can be edited. Add
paging or more in-app maintenance when needed.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import ContentSwitcher, DataTable, Footer, Input, Label, Static, Switch, Tab, Tabs

from .accounts import get_account, list_accounts, update_account
from .errors import LudexError
from .game_settings import get_prefix_root, get_settings, set_prefix_root, update_settings
from .metadata import cached_metadata, game_metadata, get_auto_details, set_auto_details
from .launch import install_game, launch_game, open_url
from .find import find_games, owned_keys
from .library import get_game, list_games
from .paths import StatePaths
from .plugins import ConfigField, Provider
from .provider_settings import get_values, set_value
from .runners import find_runners
from .storage import connect, writer_lock
from .switches import get_switch, set_switch
from .plugin_manager import list_plugins, set_plugin_enabled
from .tui_settings import GameSettingsScreen, PathInput, PathSuggester


_SOURCE_LABELS = {
    "steam_shortcuts": "Steam non-Steam shortcuts",
    "heroic_sideload": "Heroic sideloaded games",
}


_STORE_COLORS = {"steam": "#66c0f4", "epic": "#e8e8e8", "gog": "#b57edc", "heroic": "#4dd0e1", "shortcuts": "#ffb454", "local": "#9ece6a"}
_FALLBACK = ("#f7768e", "#e0af68", "#7dcfff", "#bb9af7", "#73daca")


def _store_color(store: str) -> str:
    return _STORE_COLORS.get(store) or _FALLBACK[sum(map(ord, store)) % len(_FALLBACK)]


def _stores_text(stores) -> Text:
    out = Text()
    for i, store in enumerate(stores):
        out.append(", " if i else "").append(store, style=_store_color(store))
    return out


class LudexApp(App[None]):
    TITLE = "ludex"
    DETAILS_DELAY = 0.5  # seconds the cursor must rest on a game before its details are fetched
    CSS = """
    Screen { background: $background; }
    #main { height: 1fr; }
    #left { width: 45%; border: round $panel-lighten-2; border-title-color: $text-muted; border-subtitle-color: $text-muted; }
    #left:focus-within { border: round $success; border-title-color: $success; border-title-style: bold; }
    #detail { width: 1fr; height: 100%; border: round $panel-lighten-2; border-title-color: $text-muted; padding: 0 1; }
    #main.-settings #left { width: 100%; }
    #main.-settings #detail { display: none; }
    Tabs { background: $background; height: 1; }
    Tabs Underline { display: none; }
    Tab { background: $background; color: $text-muted; padding: 0 1; }
    Tab.-active { color: $success; text-style: bold; }
    #views { height: 1fr; }
    DataTable { height: 100%; background: $background; }
    DataTable > .datatable--header { background: $background; color: $text-muted; text-style: bold; }
    DataTable > .datatable--cursor { background: $primary; color: $text; text-style: bold; }
    #filter { border: none; height: 1; background: $background; padding: 0 1; }
    #filter:focus { background: $surface; }
    Footer { background: $background; }
    Footer .footer-key--key { color: $success; background: transparent; text-style: bold; }
    #settings-table { padding: 0 1; scrollbar-size-vertical: 1; scrollbar-color: $panel-lighten-1; scrollbar-background: $background; }
    #settings-table .section { text-style: bold; color: $success; margin-top: 1; width: 100%; border-bottom: solid $panel; }
    #settings-table .hint { color: $text-muted; width: 100%; }
    #settings-table .row { height: 1; border-left: thick $background; }
    #settings-table .row:focus-within { border-left: thick $success; background: $surface; }
    #settings-table Input { border: none; border-left: thick $panel; height: 1; padding: 0 1; max-width: 80; background: $background; }
    #settings-table Input:focus { border-left: thick $success; background: $surface; }
    #settings-table Switch { border: none; height: 1; padding: 0 1; background: transparent; }
    #settings-table Switch > .switch--slider { color: $text-muted; background: $panel; }
    #settings-table Switch.-on > .switch--slider { color: $success; }
    #settings-table Switch:focus { background: transparent; }
    """
    BINDINGS = [
        Binding("tab", "next_tab", "Next tab", priority=True),
        Binding("shift+tab", "previous_tab", "Previous tab", priority=True, show=False),
        Binding("down", "cursor('down')", "Down", show=False, priority=True),
        Binding("up", "cursor('up')", "Up", show=False, priority=True),
        Binding("pagedown", "cursor('page_down')", "Page down", show=False, priority=True),
        Binding("pageup", "cursor('page_up')", "Page up", show=False, priority=True),
        Binding("enter", "enter_list", "Search", priority=True),  # priority: an empty table swallows Enter
        Binding("slash", "focus_filter", "Search", show=False),
        Binding("escape", "clear", "Back to list", show=False),
        Binding("l", "launch", "Launch"),
        Binding("e", "edit", "Game settings"),
        Binding("i", "install", "Install"),
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
        self._auto = True
        self._tried: set[int] = set()
        self._details_timer = None
        self._searched = ""
        self._fields: dict[str, tuple] = {}  # settings Input id -> what it edits
        self._conn = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Tabs(Tab("Owned", id="owned"), Tab("Installed", id="installed"), Tab("Search", id="search"), Tab("Settings", id="settings"), id="tabs")
                with ContentSwitcher(id="views", initial="owned-table"):
                    yield DataTable(id="owned-table", cursor_type="row", show_header=False)
                    yield DataTable(id="installed-table", cursor_type="row", show_header=False)
                    yield DataTable(id="search-table", cursor_type="row")
                    with VerticalScroll(id="settings-table"):
                        yield from self._settings_widgets()
                yield Input(id="filter")
            yield Static("", id="detail")
        yield Footer()

    def _status(self, text: str) -> None:
        self.query_one("#left").border_subtitle = text

    def on_mount(self) -> None:
        self.query_one("#left").border_title = "ludex"
        self.query_one("#detail").border_title = "Detail"
        self.theme = "tokyo-night"  # colourful default; ctrl+p opens the theme picker
        self._conn = connect(self._database)
        self._auto = get_auto_details(self._conn)
        with self.prevent(Switch.Changed):
            self.query_one("#opt-auto_details", Switch).value = self._auto
        for table in self.query(DataTable):
            table.add_columns(*(("store", "title", "price", "owned") if table.id == "search-table" else ("", "title", "stores")))
        self.query_one("#folder", Input).value = str(get_prefix_root(self._conn, self._default_prefix()))
        self.action_reload()
        self._table().focus()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # tab, arrows and paging belong to the list only on the main screen; forms keep their own
        if len(self.screen_stack) > 1 and action not in {"quit"}:
            return False
        tab_actions = {"owned": {"install", "edit"}, "installed": {"launch", "edit"}, "search": {"install"}}
        if action in {"launch", "edit", "install"}:  # what you can do depends on the tab
            return action in tab_actions.get(self._active(), set())
        if self._active() == "settings" and action in {"focus_filter", "settings"}:
            return False
        if action == "enter_list":  # only from the list; inputs and switches keep their own Enter
            return self._active() != "settings" and (self.focused is None or isinstance(self.focused, (DataTable, Tabs)))
        return True

    def _active(self) -> str:
        return self.query_one(Tabs).active

    def on_tabs_tab_activated(self, event: Tabs.TabActivated) -> None:
        name = event.tab.id or "owned"
        self.refresh_bindings()
        self.query_one(ContentSwitcher).current = f"{name}-table"
        self.query_one("#main").set_class(name == "settings", "-settings")
        box = self.query_one("#filter", Input)
        box.display = name != "settings"
        box.placeholder = "store search: type a name, Enter" if name == "search" else "filter: type, then Enter or Esc"
        (self.query_one("#folder") if name == "settings" else self._table()).focus()
        if name == "settings":
            self._status("")
            self.query_one("#detail", Static).update("")
        else:
            self._show_hint()

    def action_next_tab(self) -> None:
        self.query_one(Tabs).action_next_tab()

    def action_previous_tab(self) -> None:
        self.query_one(Tabs).action_previous_tab()

    def action_cursor(self, move: str) -> None:
        if self._active() == "settings":  # arrows move between the settings
            (self.screen.focus_previous if move in {"up", "page_up"} else self.screen.focus_next)()
            return
        getattr(self._table(), f"action_cursor_{move}" if move in {"up", "down"} else f"action_{move}")()

    def on_unmount(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _table(self) -> DataTable:
        return self.query_one(f"#{self._active()}-table", DataTable)

    def _reload(self) -> None:
        query = self.query_one("#filter", Input).value.strip() or None
        counts = []
        installed_ids: set[int] = set()
        for name, only in (("installed", self._keys), ("owned", None)):
            games = list_games(self._conn, query=query, only=only, limit=500)
            table = self.query_one(f"#{name}-table", DataTable)
            table.clear()
            if name == "installed":
                installed_ids = {g["id"] for g in games}
            for game in games:
                mark = Text("●", style="#9ece6a") if game["id"] in installed_ids else Text(" ")
                table.add_row(mark, game["title"], _stores_text(game["stores"]), key=str(game["id"]))
            counts.append(f"{len(games)}{'+' if len(games) == 500 else ''} {name}")
        self._status(", ".join(reversed(counts)))
        self._show_hint()

    def _show_hint(self) -> None:
        """Say what to do when the visible list is empty; otherwise the detail card waits for a row."""
        name = self._active()
        hints = {
            "owned": "No games here yet. Add a source with 'ludex account add' and run 'ludex import'." ,
            "installed": "Nothing installed was found for these games. Press r to look again.",
            "search": "Press / and type a game name, then Enter to search the stores.",
        }
        empty = name in hints and self.query_one(f"#{name}-table", DataTable).row_count == 0
        self.query_one("#detail", Static).update(f"[dim]{hints[name]}[/]" if empty else "")

    def _current_id(self) -> int | None:
        table = self._table()
        if table.row_count == 0:
            return None
        return int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self._reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "folder":
            self._save_prefix_folder(event.value.strip() or None)
            return
        if event.input.id in self._fields:
            self._save_field(event.input.id, event.value.strip())
            return
        if self._active() == "search":
            query = event.value.strip()
            if query and query != self._searched:
                self._searched = query
                self._status(f"searching the stores for {query!r}...")
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
            table.add_row(Text(h["store"], style=_store_color(h["store"])), h["title"], Text(h["price"] or "-", style="#e0af68"), Text("✔ owned", style="bold #9ece6a") if h["owned"] else "", key=key)
        self._status(f"{len(hits)} results for {query!r}")
        self.query_one("#detail", Static).update("" if hits else f"[dim]No results for {escape(query)!r}.[/]")
        if self._active() == "search" and self.focused is self.query_one("#filter"):
            table.focus()
        for name, reason in sorted(problems.items()):
            self.notify(f"{name}: {reason}", severity="warning")

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = event.row_key.value if event.row_key is not None else None  # None: the table is empty
        if event.data_table.id == "search-table":
            hit = self._hits.get(key or "")
            self.query_one("#detail", Static).update(
                f"[b #7aa2f7]{escape(hit['title'])}[/]\n[dim]{escape(hit['url'])}[/]" + (f"\n[#e0af68]{escape(hit['price'])}[/]" if hit["price"] else "") if hit else ""
            )
            return
        if key is None:
            return
        self._show_game(int(key))  # the event's own row, not the active tab's cursor

    def _show_game(self, game_id: int, note: str | None = None) -> None:
        game = get_game(self._conn, game_id)
        lines = [f"[b #7aa2f7]{escape(game['title'])}[/]"] + [
            f"  [{_store_color(o['store'])}]{escape(o['store'])}[/]:{escape(str(o['store_id']))}  [dim]{escape(str(o['account']))}[/]  "
            + ("[b #f7768e]removed[/]" if o["removed"] else "[b #9ece6a]owned[/]")
            for o in game["ownership"]
        ]
        if any((o["store"], str(o["store_id"])) in self._keys for o in game["ownership"]):
            lines.append("[#9ece6a]● installed[/]")
        found = next((m for o in game["ownership"] if (m := cached_metadata(self._conn, o["store"], str(o["store_id"])))), None)
        if found is not None:
            lines += [""] + ([escape(found.description)] if found.description else [])
            lines += [f"[dim]{label}:[/] {escape(', '.join(values))}" for label, values in (("genres", found.genres), ("by", found.developers), ("released", (found.released,) if found.released else ())) if values]
        self.query_one("#detail", Static).update("\n".join(lines))
        if note:
            lines += ["", note]
        if found is None and note is None:
            self._queue_details(game_id)

    def _queue_details(self, game_id: int) -> None:
        """Ask for details once the cursor rests on a game (and only once per game per run)."""
        if self._details_timer is not None:
            self._details_timer.stop()
            self._details_timer = None
        if self._auto and game_id not in self._tried:
            self._details_timer = self.set_timer(self.DETAILS_DELAY, lambda: self._start_details(game_id))

    def _start_details(self, game_id: int) -> None:
        self._details_timer = None
        if self._active() not in {"owned", "installed"} or self._current_id() != game_id or game_id in self._tried:
            return
        self._tried.add(game_id)
        self.run_worker(lambda: self._fetch_details(game_id), thread=True, exclusive=True, group="details")

    def _fetch_details(self, game_id: int) -> None:
        conn = connect(self._database)  # a worker thread needs its own connection
        try:
            found, problem = game_metadata(conn, self._sources, game_id), None
        except LudexError as exc:
            found, problem = None, None if exc.code == "metadata_unavailable" else exc.message
        finally:
            conn.close()
        self.call_from_thread(self._details_ready, game_id, found is not None, problem)

    def _details_ready(self, game_id: int, found: bool, problem: str | None) -> None:
        if self._active() not in {"owned", "installed"} or self._current_id() != game_id:
            return
        if found:
            self._show_game(game_id)
        elif problem:
            self._show_game(game_id, f"[dim]no details: {escape(problem)}[/]")

    def action_clear(self) -> None:
        self.query_one("#filter", Input).value = ""
        if self._active() != "settings":
            self._table().focus()

    def action_enter_list(self) -> None:
        self.action_focus_filter()  # Enter goes to the search box; l launches

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def action_settings(self) -> None:
        self.query_one(Tabs).active = "settings"

    def action_reload(self) -> None:
        self._keys = self._installed()
        self._reload()

    def _prefix(self) -> Path | None:
        return get_prefix_root(self._conn, self._prefix_root) if self._prefix_root else None

    def _write(self, change: Callable[[], object]) -> None:
        if self._lock is None:
            change()
            return
        with writer_lock(self._lock):
            change()

    def _default_prefix(self) -> Path:
        return self._prefix_root or Path.home() / "prefixes"

    def _settings_widgets(self):
        yield Label("Default prefix folder", classes="section")
        yield Label("Each game gets its own prefix inside it. Enter saves, Right arrow completes, blank resets.", classes="hint")
        yield PathInput("", suggester=PathSuggester(dirs_only=True), id="folder")
        yield Label("Game details", classes="section")
        with Horizontal(classes="row"):
            yield Switch(True, id="opt-auto_details")
            yield Label(" Fetch description, genres and developer for the highlighted game (the store sees the game id)")
        if self._paths is None:
            return
        yield Label("Sources", classes="section")
        for key, text in _SOURCE_LABELS.items():
            with Horizontal(classes="row"):
                yield Switch(get_switch(self._paths, key), id=f"src-{key}")
                yield Label(f" {text}")
        yield Label("Plugins", classes="section")
        plugins = list_plugins()
        for plugin in plugins:
            with Horizontal(classes="row"):
                yield Switch(plugin["enabled"], id=f"plg-{plugin['name']}")
                yield Label(f" {plugin['name']} {plugin['version']}  ({', '.join(plugin['providers'])})")
        yield Label(
            "Add plugins with: ludex plugin add <git link or package>. Enabling or disabling applies the next time ludex starts."
            if plugins else "No plugins installed. Add one with: ludex plugin add <git link or package>",
            classes="hint",
        )
        for plugin in sorted(self._sources.values(), key=lambda p: p.name):
            if plugin.settings:
                values = get_values(self._paths, plugin.name)
                yield Label(f"{plugin.name} settings", classes="section")
                for field in plugin.settings:
                    yield from self._field_input(("plugin", plugin, field), field, values.get(field.name))
        accounts = [(f"{source}:{name}", source) for name, source in list_accounts(self._paths) if source in self._sources]
        if accounts:
            yield Label("Accounts", classes="section")
            yield Label("Enter saves a field. Run 'ludex import' afterwards to pick up the change.", classes="hint")
        for ref, source in accounts:
            plugin = self._sources[source]
            config = get_account(self._paths, ref).config
            yield Label(ref, classes="section")
            for field in plugin.config_fields:
                yield from self._field_input(("account", ref, plugin, field), field, config.get(field.name))

    def _field_input(self, target: tuple, field: ConfigField, value: str | None):
        input_id = f"field-{len(self._fields)}"
        self._fields[input_id] = target
        yield Label(f"{field.name}: {field.help}" + (" (optional)" if field.optional else ""), classes="hint")
        shown = "" if field.secret else value or ""
        placeholder = "(set; type to replace)" if field.secret and value else ""
        if field.path:
            yield PathInput(shown, suggester=PathSuggester(dirs_only=False), placeholder=placeholder, id=input_id)
        else:
            yield Input(shown, placeholder=placeholder, password=field.secret, id=input_id)

    def _save_field(self, input_id: str, text: str) -> None:
        target = self._fields[input_id]
        try:
            if target[0] == "plugin":
                _, plugin, field = target
                self._write(lambda: set_value(self._paths, plugin, field.name, text or None))
                self.notify(f"{plugin.name}.{field.name} {'saved' if text else 'removed'}")
            else:
                _, ref, plugin, field = target
                if not text and field.secret:
                    self.notify(f"{field.name} unchanged (type a new value to replace it)")
                    return
                self._write(
                    lambda: update_account(
                        self._paths, ref, plugin.config_fields, {field.name: text} if text else {}, [] if text else [field.name]
                    )
                )
                self.notify(f"{ref}: {field.name} {'saved' if text else 'removed'}; run 'ludex import {ref}'")
        except LudexError as exc:
            self.notify(exc.message, severity="error")

    def _save_prefix_folder(self, folder: str | None) -> None:
        try:
            self._write(lambda: set_prefix_root(self._conn, folder))
        except LudexError as exc:
            self.notify(exc.message, severity="error")
            return
        self.notify(f"prefix folder: {get_prefix_root(self._conn, self._default_prefix())}")

    def on_switch_changed(self, event: Switch.Changed) -> None:
        kind, _, name = (event.switch.id or "").partition("-")
        try:
            if kind == "src":
                count = []
                self._write(lambda: count.append(set_switch(self._paths, self._conn, self._sources, name, event.value)))
                self.notify(
                    f"{_SOURCE_LABELS[name]}: {count[0]} games imported" if event.value
                    else f"{_SOURCE_LABELS[name]}: removed {count[0]} records; turn it on to bring the games back"
                )
                self.action_reload()
            elif kind == "opt":
                self._write(lambda: set_auto_details(self._conn, event.value))
                self._auto = event.value
            elif kind == "plg":
                self._write(lambda: set_plugin_enabled(name, event.value))
                self.notify(f"{name} {'enabled' if event.value else 'disabled'}; applies the next time ludex starts")
        except LudexError as exc:
            self.notify(exc.message, severity="error")
            with self.prevent(Switch.Changed):
                event.switch.value = not event.value

    def action_edit(self) -> None:
        game_id = None if self._active() in {"search", "settings"} else self._current_id()
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

    def _install_hit(self) -> None:
        table = self.query_one("#search-table", DataTable)
        hit = self._hits.get(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value or "") if table.row_count else None
        if hit is None:
            return
        plugin = self._sources.get(hit["store"])
        try:  # the store client's own install link when the plugin has one, else the store page
            open_url(plugin.install_url(hit["store_id"]) if plugin and plugin.install_url else hit["url"], f"the {hit['store']} client")
            self.notify(f"asked the client to install {hit['title']}")
        except LudexError as exc:
            self.notify(exc.message, severity="error")

    def action_install(self) -> None:
        if self._active() == "search":
            self._install_hit()
            return
        game_id = None if self._active() == "settings" else self._current_id()
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
        if self._active() == "settings":
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
