from __future__ import annotations

import asyncio

import pytest

from ludex import launch as launch_mod
from ludex.library import import_account
from ludex.plugins import OwnedGame
from ludex.sources import epic, steam
from ludex.storage import connect
from ludex.tui import LudexApp
from textual.widgets import DataTable, Input


def test_search_narrows_the_list_and_enter_launches(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    import_account(conn, "m", [OwnedGame("epic", "h", "Hades")], store="epic")
    conn.close()
    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv[1]))

    async def scenario():
        app = LudexApp(db, {"steam": steam.PLUGIN, "epic": epic.PLUGIN}, lambda: {("steam", "2")})
        async with app.run_test() as pilot:
            table = app.query_one("#owned-table", DataTable)
            assert table.row_count == 2
            installed = app.query_one("#installed-table", DataTable)
            assert [installed.get_row_at(i)[1] for i in range(installed.row_count)] == ["Doom"]
            app.query_one(Input).value = "hades"
            await pilot.pause()
            assert table.row_count == 1
            table.focus()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert opened == ["heroic://launch?appName=h&runner=legendary"]


def test_search_tab_queries_providers_marks_owned_and_enter_opens_the_page(tmp_path, monkeypatch):
    from ludex.plugins import Provider, SearchHit

    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades")], store="steam")
    conn.close()
    store = Provider("steam", "s", (), search=lambda q: [SearchHit("steam", "1", "Hades", "https://x/1", "9 USD"), SearchHit("steam", "2", "Doom", "https://x/2")])

    async def scenario():
        app = LudexApp(db, {"steam": store})
        async with app.run_test() as pilot:
            await pilot.pause()
            app.query_one("TabbedContent").active = "search"
            await pilot.pause()
            app.query_one(Input).value = "ha"
            app.query_one(Input).focus()
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#search-table", DataTable)
            rows = [tuple(table.get_row_at(i)) for i in range(table.row_count)]
            await pilot.press("down", "enter")
            await pilot.pause()
            return rows

    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv))
    assert asyncio.run(scenario()) == [("steam", "Hades", "9 USD", "yes"), ("steam", "Doom", "-", "")]
    assert opened == [["xdg-open", "https://x/2"]]
