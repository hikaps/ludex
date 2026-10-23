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
        app = LudexApp(db, {"steam": steam.PLUGIN, "epic": epic.PLUGIN})
        async with app.run_test() as pilot:
            table = app.query_one(DataTable)
            assert table.row_count == 2
            app.query_one(Input).value = "hades"
            await pilot.pause()
            assert table.row_count == 1
            table.focus()
            await pilot.press("enter")
            await pilot.pause()

    asyncio.run(scenario())
    assert opened == ["heroic://launch?appName=h&runner=legendary"]
