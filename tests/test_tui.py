from __future__ import annotations

import asyncio

import pytest

from ludex import launch as launch_mod
from ludex.library import import_account
from ludex.plugins import OwnedGame
from ludex.sources import epic, steam
from ludex.storage import connect
from ludex.tui import LudexApp
from textual.widgets import DataTable, Input, Static


def test_search_narrows_the_list_and_enter_launches(tmp_path, monkeypatch):
    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    import_account(conn, "m", [OwnedGame("epic", "h", "Hades")], store="epic")
    conn.close()
    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv[1]))

    async def scenario():
        app = LudexApp(db, {"steam": steam.PLUGIN, "epic": epic.PLUGIN}, lambda: {("steam", "2"), ("epic", "h")})
        async with app.run_test() as pilot:
            owned = app.query_one("#owned-table", DataTable)
            installed = app.query_one("#installed-table", DataTable)
            assert owned.row_count == 2 and installed.row_count == 2
            assert app.focused is owned  # the list has focus, so letters are shortcuts
            await pilot.press("l")  # launching belongs to the Installed tab
            await pilot.press("tab")
            assert app.focused is installed
            await pilot.press("enter")  # Enter goes to the search box
            assert app.focused is app.query_one("#filter")
            await pilot.press("h", "a", "d", "e", "s")  # typing filters at once
            await pilot.pause()
            assert installed.row_count == 1
            await pilot.press("enter")  # Enter returns to the list; l launches
            assert app.focused is installed
            await pilot.press("i")  # installing belongs to Owned and Search
            await pilot.press("l")
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
            await pilot.press("tab", "tab")  # Owned -> Installed -> Search
            await pilot.pause()
            assert app.query_one("Tabs").active == "search" and app.focused is app.query_one("#search-table")
            await pilot.press("slash", "h", "a")  # "/" jumps to the search box
            await pilot.press("enter")  # new query: search the stores
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#search-table", DataTable)
            rows = [tuple(str(c) for c in table.get_row_at(i)) for i in range(table.row_count)]
            assert app.focused is table  # results take the focus
            await pilot.press("e", "l")  # game settings and launching are not offered on Search
            assert app.screen is app.screen_stack[0]
            await pilot.press("down", "i")  # Install opens the store's page when the plugin has no install link
            await pilot.pause()
            return rows

    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv))
    assert asyncio.run(scenario()) == [("steam", "Hades", "9 USD", "✔ owned"), ("steam", "Doom", "-", "")]
    assert opened == [["xdg-open", "https://x/2"]]


def test_edit_screen_saves_runner_prefix_executable_args_and_env(tmp_path, monkeypatch):
    from textual.widgets import Select, TextArea

    from ludex.game_settings import get_settings
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


def test_settings_tab_saves_the_prefix_folder_and_toggles_sources_and_plugins(tmp_path, monkeypatch):
    from textual.widgets import Switch

    from ludex.accounts import add_account, list_accounts
    from ludex.game_settings import get_prefix_root
    from ludex.library import run_import
    from ludex.paths import StatePaths
    from ludex.plugins import FetchResult, Provider

    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("LUDEX_HOME", str(root))
    paths = StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")
    provider = Provider("shortcuts", "s", (), lambda c: FetchResult([OwnedGame("shortcuts", "1", "Hades")], True, None))
    add_account(paths, "default", "shortcuts", {})
    conn = connect(paths.database)
    run_import(conn, "default", provider, {})
    conn.close()
    plugin = root / "plugins" / "ludex-fake"
    (plugin / "ludex_fake-1.0.dist-info").mkdir(parents=True)
    (plugin / "ludex_fake-1.0.dist-info" / "METADATA").write_text("Name: ludex-fake\nVersion: 1.0\n")
    (plugin / "ludex_fake-1.0.dist-info" / "entry_points.txt").write_text("[ludex.providers]\nfake = x:y\n")

    async def scenario():
        app = LudexApp(paths.database, {"shortcuts": provider}, prefix_root=root / "p", paths=paths)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#owned-table", DataTable).row_count == 1
            await pilot.press("tab", "tab", "tab")  # Owned -> Installed -> Search -> Settings
            await pilot.pause()
            assert app.query_one("Tabs").active == "settings" and app.focused is app.query_one("#folder")
            assert not app.query_one("#filter").display
            app.query_one("#folder", Input).value = str(tmp_path / "all-prefixes")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down", "down")  # arrows move between the settings
            await pilot.pause()
            assert app.focused is app.query_one("#src-steam_shortcuts", Switch)
            app.query_one("#src-steam_shortcuts", Switch).value = False  # off: account and games go, no dialog
            app.query_one("#plg-ludex-fake", Switch).value = False
            await pilot.pause()
            assert app.query_one("#owned-table", DataTable).row_count == 0

    asyncio.run(scenario())
    assert list_accounts(paths) == []
    assert get_prefix_root(connect(paths.database), root / "p") == tmp_path / "all-prefixes"
    assert (plugin / ".disabled").exists()


def test_settings_tab_edits_plugin_settings_and_account_fields(tmp_path, monkeypatch):
    from ludex.accounts import add_account, get_account
    from ludex.paths import StatePaths
    from ludex.plugins import ConfigField, FetchResult, Provider
    from ludex.provider_settings import get_values

    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    monkeypatch.setenv("LUDEX_HOME", str(root))
    paths = StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")
    connect(paths.database).close()
    provider = Provider(
        "demo", "d",
        (ConfigField("user", "account user"), ConfigField("key", "API key", secret=True), ConfigField("tag", "label", optional=True)),
        lambda c: FetchResult([], True, None),
        settings=(ConfigField("region", "store region", optional=True), ConfigField("token", "API token", secret=True, optional=True)),
    )
    add_account(paths, "a", "demo", {"user": "u1", "key": "k1"})

    async def scenario():
        app = LudexApp(paths.database, {"demo": provider}, prefix_root=root / "p", paths=paths)
        async with app.run_test(size=(100, 60)) as pilot:
            await pilot.pause()
            await pilot.press("tab", "tab", "tab")
            await pilot.pause()
            ids = {target[-1].name + ":" + target[0]: i for i, target in app._fields.items()}
            def edit(name, value):
                box = app.query_one("#" + ids[name], Input)
                box.value = value
                box.focus()
                return pilot.press("enter")
            await edit("region:plugin", "eu"); await pilot.pause()
            await edit("token:plugin", "tok"); await pilot.pause()
            await edit("user:account", "u2"); await pilot.pause()
            await edit("key:account", ""); await pilot.pause()  # blank secret leaves it unchanged
            await edit("tag:account", "x"); await pilot.pause()
            await edit("user:account", ""); await pilot.pause()  # required: rejected, not removed

    asyncio.run(scenario())
    assert get_values(paths, "demo") == {"region": "eu", "token": "tok"}
    assert dict(get_account(paths, "demo:a").config) == {"region": "eu", "token": "tok", "user": "u2", "key": "k1", "tag": "x"}


def test_s_opens_settings_and_letters_only_type_while_the_search_box_has_focus(tmp_path):
    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    conn.close()

    async def scenario():
        app = LudexApp(db, {})
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash", "s", "q")  # typed into the box: no tab switch, no quit
            assert app.query_one("Tabs").active == "owned" and app.query_one("#filter", Input).value == "sq"
            await pilot.press("escape")  # clears the box and returns to the list
            assert app.query_one("#filter", Input).value == "" and app.focused is app.query_one("#owned-table")
            await pilot.press("s")
            await pilot.pause()
            assert app.query_one("Tabs").active == "settings" and app.focused is app.query_one("#folder")
            await pilot.press("tab")  # Tab still cycles: Settings -> Owned
            assert app.query_one("Tabs").active == "owned"

    asyncio.run(scenario())


def test_an_empty_table_highlight_event_is_ignored(tmp_path):
    from ludex.plugins import Provider

    db = tmp_path / "db.sqlite3"
    connect(db).close()

    async def scenario():
        app = LudexApp(db, {"steam": Provider("steam", "s", (), search=lambda q: [])})
        async with app.run_test() as pilot:
            for table in app.query(DataTable):  # newer Textual sends row_key=None when a table is empty
                app.post_message(DataTable.RowHighlighted(table, -1, None))
            await pilot.pause()
            assert app.is_running

    asyncio.run(scenario())


def test_empty_lists_say_what_to_do_and_installed_games_get_a_marker(tmp_path):
    db = tmp_path / "db.sqlite3"
    connect(db).close()

    async def empty():
        app = LudexApp(db, {})
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "No games" in str(app.query_one("#detail", Static).render())
            await pilot.press("tab", "tab")
            await pilot.pause()
            assert "Press /" in str(app.query_one("#detail", Static).render())

    asyncio.run(empty())
    conn = connect(db)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    conn.close()

    async def marked():
        app = LudexApp(db, {}, lambda: {("steam", "1")})
        async with app.run_test() as pilot:
            await pilot.pause()
            table = app.query_one("#owned-table", DataTable)
            rows = {table.get_row_at(i)[1]: str(table.get_row_at(i)[0]).strip() for i in range(table.row_count)}
            assert rows == {"Doom": "", "Hades": "●"}

    asyncio.run(marked())


def test_enter_goes_to_the_search_box_even_when_the_list_is_empty(tmp_path):
    db = tmp_path / "db.sqlite3"
    connect(db).close()

    async def scenario():
        app = LudexApp(db, {})
        async with app.run_test() as pilot:
            await pilot.pause()
            for _ in range(3):  # Owned, Installed, Search are all empty
                await pilot.press("enter")
                assert app.focused is app.query_one("#filter"), app.query_one("Tabs").active
                await pilot.press("escape", "tab")

    asyncio.run(scenario())


def test_search_columns_fit_the_pane_so_price_and_owned_stay_visible(tmp_path):
    from ludex.plugins import Provider, SearchHit

    db = tmp_path / "db.sqlite3"
    connect(db).close()
    hits = [SearchHit("steam", "1", "A very long game title " * 4, "https://x/1", "9.99 USD")]

    async def scenario():
        app = LudexApp(db, {"steam": Provider("steam", "s", (), search=lambda q: hits)})
        async with app.run_test(size=(80, 20)) as pilot:
            await pilot.press("tab", "tab", "enter", "a", "enter")
            await pilot.pause(0.3)
            await app.workers.wait_for_complete()
            await pilot.pause()
            table = app.query_one("#search-table", DataTable)
            assert table.row_count == 1
            assert sum(c.get_render_width(table) for c in table.columns.values()) <= table.size.width
            assert not table.show_horizontal_scrollbar

    asyncio.run(scenario())


def test_vim_keys_move_the_cursor_and_do_not_steal_typing(tmp_path):
    db = tmp_path / "db.sqlite3"
    conn = connect(db)
    import_account(conn, "m", [OwnedGame("steam", str(i), t) for i, t in enumerate(["Aa", "Bb", "Cc", "Dd"])], store="steam")
    conn.close()

    async def scenario():
        app = LudexApp(db, {})
        async with app.run_test() as pilot:
            await pilot.pause()  # let the app finish mounting before the first key
            table = app.query_one("#owned-table", DataTable)
            await pilot.press("j", "j")
            assert table.cursor_row == 2
            await pilot.press("k")
            assert table.cursor_row == 1
            await pilot.press("G")
            assert table.cursor_row == 3
            await pilot.press("g")
            assert table.cursor_row == 0
            await pilot.press("ctrl+d")
            assert table.cursor_row > 0
            await pilot.press("/", "j", "k", "g")  # in the filter box the letters are text
            assert app.query_one("#filter", Input).value == "jkg"

    asyncio.run(scenario())
