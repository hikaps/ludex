"""Terminal UI: browse, search and launch. All behavior comes from the core library.

ponytail: read-only view of the local database (import with ``ludex import`` outside), no merge or
review screens, first 500 matches only; add when the list needs paging or in-app maintenance.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Input, Static

from .errors import LudexError
from .launch import launch_game
from .library import get_game, list_games
from .plugins import SourcePlugin
from .storage import connect


class LudexApp(App[None]):
    TITLE = "ludex"
    CSS = "#detail { height: auto; max-height: 40%; padding: 0 1; border-top: solid $primary; }"
    BINDINGS = [
        Binding("slash", "search", "Search"),
        Binding("enter", "launch", "Launch"),
        Binding("escape", "clear", "Clear search", show=False),
        Binding("r", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, database: Path, sources: Mapping[str, SourcePlugin]) -> None:
        super().__init__()
        self._database = database
        self._sources = sources
        self._conn = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="search (press / to focus)", id="search")
        yield DataTable(id="games", cursor_type="row", zebra_stripes=True)
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self._conn = connect(self._database)
        table = self.query_one(DataTable)
        table.add_columns("id", "title", "stores")
        table.focus()
        self._reload()

    def on_unmount(self) -> None:
        if self._conn is not None:
            self._conn.close()

    def _reload(self) -> None:
        query = self.query_one(Input).value.strip() or None
        games = list_games(self._conn, query=query, limit=500)
        table = self.query_one(DataTable)
        table.clear()
        for game in games:
            table.add_row(str(game["id"]), game["title"], ", ".join(game["stores"]), key=str(game["id"]))
        self.sub_title = f"{len(games)} games" + (" (first 500)" if len(games) == 500 else "")
        self.query_one("#detail", Static).update("")

    def _current_id(self) -> int | None:
        table = self.query_one(DataTable)
        if table.row_count == 0:
            return None
        return int(table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._reload()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.query_one(DataTable).focus()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        game_id = self._current_id()
        if game_id is None:
            return
        game = get_game(self._conn, game_id)
        lines = [game["title"]] + [
            f"  {o['store']}:{o['store_id']}  account={o['account']}  {'removed' if o['removed'] else 'owned'}"
            for o in game["ownership"]
        ]
        self.query_one("#detail", Static).update("\n".join(lines))

    def action_search(self) -> None:
        self.query_one(Input).focus()

    def action_clear(self) -> None:
        self.query_one(Input).value = ""
        self.query_one(DataTable).focus()

    def action_reload(self) -> None:
        self._reload()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_launch()

    def action_launch(self) -> None:
        game_id = self._current_id()
        if game_id is None:
            return
        try:
            try:
                target = launch_game(self._conn, self._sources, game_id)
            except LudexError as exc:
                if exc.code != "launch_ambiguous":
                    raise
                # several stores can start it: use the first, alphabetically
                store = exc.message.split("launched from ")[1].split(";")[0].split(", ")[0]
                target = launch_game(self._conn, self._sources, game_id, store)
            self.notify(f"launching {target}")
        except LudexError as exc:
            self.notify(exc.message, severity="error")
