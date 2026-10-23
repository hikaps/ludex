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
            tabs = app.query_one("TabbedContent")
            for _ in range(50):  # the initial Owned activation can land after the first switch
                tabs.active = "search"
                await pilot.pause()
                if tabs.active == "search":
                    await pilot.pause()
                    break
            assert tabs.active == "search"
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


def test_edit_screen_saves_runner_prefix_env_and_the_prefix_folder(tmp_path, monkeypatch):
    from textual.widgets import Select, TextArea

    from ludex.game_settings import get_prefix_root, get_settings
    from ludex.plugins import Provider
    from ludex.runners import Runner

    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "disk", [OwnedGame("local", "g", "Hades")], store="local")
    conn.close()
    folder = tmp_path / "games" / "g"
    folder.mkdir(parents=True)
    proton = tmp_path / "GE"
    proton.mkdir()
    (proton / "proton").write_text("")
    monkeypatch.setattr("ludex.tui.find_runners", lambda: [Runner("GE", proton, "steam")])
    monkeypatch.setattr("ludex.runners.find_runners", lambda home=None: [Runner("GE", proton, "steam")])
    local = Provider("local", "l", (), lambda c: None, game_folder=lambda config, store_id: folder)

    async def scenario():
        app = LudexApp(db, {"local": local}, config_for=lambda s, a: {}, prefix_root=tmp_path / "default")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            screen = app.screen
            screen.query_one("#runner", Select).value = "GE"
            screen.query_one("#prefix", Input).value = str(tmp_path / "pfx")
            screen.query_one("#executable", Input).value = "Hades.exe"
            screen.query_one("#args", Input).value = "-w 'a b'"
            screen.query_one("#env", TextArea).text = "A=1\nB=x=y\n"
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.screen is not screen, str(screen.query_one("#form-error").render())  # closed
            await pilot.press("s")
            await pilot.pause()
            app.screen.query_one("#folder", Input).value = str(tmp_path / "all-prefixes")
            await pilot.press("ctrl+s")
            await pilot.pause()

    asyncio.run(scenario())
    conn = connect(db)
    assert get_settings(conn, "local", "g").as_dict() == {
        "runner": "GE", "prefix": str(tmp_path / "pfx"), "executable": "Hades.exe", "args": ["-w", "a b"], "env": {"A": "1", "B": "x=y"},
    }
    assert get_prefix_root(conn, tmp_path / "default") == tmp_path / "all-prefixes"


def test_edit_screen_reports_invalid_input_and_stays_open(tmp_path):
    from textual.widgets import Static, TextArea

    from ludex.game_settings import get_settings
    from ludex.plugins import Provider

    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "disk", [OwnedGame("local", "g", "Hades")], store="local")
    conn.close()
    local = Provider("local", "l", (), lambda c: None, game_folder=lambda config, store_id: tmp_path)

    async def scenario():
        app = LudexApp(db, {"local": local}, config_for=lambda s, a: {}, prefix_root=tmp_path / "default")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            screen = app.screen
            screen.query_one("#env", TextArea).text = "no equals sign"
            await pilot.press("ctrl+s")
            await pilot.pause()
            assert app.screen is screen
            assert "NAME=VALUE" in str(screen.query_one("#form-error", Static).render())

    asyncio.run(scenario())
    assert get_settings(connect(db), "local", "g").env == {}


def test_path_suggester_completes_directories_files_and_home(tmp_path, monkeypatch):
    from ludex.tui_settings import PathSuggester

    (tmp_path / "games").mkdir()
    (tmp_path / "gamma.txt").write_text("")
    (tmp_path / ".hidden").mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))

    def suggest(value, **kw):
        return asyncio.run(PathSuggester(**kw).get_suggestion(value))

    assert suggest(f"{tmp_path}/ga") == f"{tmp_path}/games/"
    assert suggest(f"{tmp_path}/gam", dirs_only=True) == f"{tmp_path}/games/"
    assert suggest(f"{tmp_path}/gamm") == f"{tmp_path}/gamma.txt"
    assert suggest(f"{tmp_path}/gamm", dirs_only=True) is None
    assert suggest("~/gam") == "~/games/"
    assert suggest(f"{tmp_path}/") == f"{tmp_path}/games/"  # hidden entries are skipped
    assert suggest(f"{tmp_path}/.h") == f"{tmp_path}/.hidden/"
    assert suggest("gam", base=tmp_path) == "games/"
    assert suggest(f"{tmp_path}/nothing") is None and suggest("") is None


def test_tab_completes_a_path_then_moves_on(tmp_path):
    from ludex.plugins import Provider

    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "disk", [OwnedGame("local", "g", "Hades")], store="local")
    conn.close()
    (tmp_path / "prefix-root").mkdir()
    local = Provider("local", "l", (), lambda c: None, game_folder=lambda config, store_id: tmp_path)

    async def scenario():
        app = LudexApp(db, {"local": local}, config_for=lambda s, a: {}, prefix_root=tmp_path / "default")
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert app.focused is app.screen.query_one("#runner")  # the form opens ready to use
            prefix = app.screen.query_one("#prefix", Input)
            prefix.focus()
            prefix.value = f"{tmp_path}/pre"
            await pilot.pause(0.3)  # the suggestion arrives asynchronously
            await pilot.press("tab")
            await pilot.pause()
            assert prefix.value == f"{tmp_path}/prefix-root/"
            assert app.focused is prefix
            await pilot.press("tab")  # nothing more to complete (empty folder): focus moves on
            await pilot.pause()
            assert app.focused is app.screen.query_one("#executable", Input)

    asyncio.run(scenario())
