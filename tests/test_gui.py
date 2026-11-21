from __future__ import annotations

import os
from pathlib import Path
import sys
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication, QWindow

from ludex import artwork
from ludex import launch as launch_mod
from ludex.errors import LudexError
from ludex.library import import_account
from ludex.metadata import set_auto_details
from ludex.paths import StatePaths
from ludex.plugins import Command, CommandResult, ConfigField, FetchResult, Metadata, OwnedGame, Provider, SearchHit, View, ViewAction, ViewDetail, ViewRow, ViewTable
from ludex.provider_settings import get_values
from ludex.sources import steam
from ludex.storage import connect
from ludex_gui import gamepad as gamepad_mod
from ludex_gui.app import QML_DIR, Launcher, build_engine, console_environment

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


@pytest.fixture(scope="session")
def qapp():
    return QGuiApplication.instance() or QGuiApplication([])


def _until(qapp, check, seconds: float = 10.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        qapp.processEvents()
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def _paths(tmp_path) -> StatePaths:
    root = tmp_path / "home"
    root.mkdir(mode=0o700)
    return StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")


def _launcher(paths, sources, installed=frozenset(), console=False) -> Launcher:
    return build_engine(paths, sources, lambda: set(installed), lambda store, account: {}, lambda conn: {}, paths.root / "prefixes", console)


def test_the_window_loads_without_warnings_and_lists_the_sidebar_pages(qapp, tmp_path):
    paths = _paths(tmp_path)
    launcher = _launcher(paths, {})
    assert launcher.warnings == [] and launcher.window is not None
    for name in ("library", "installed", "search", "jobs", "settings"):
        assert launcher.window.findChild(QObject, f"nav-{name}") is not None
    launcher.backend.closeDown()


def test_library_filters_sorts_and_launches_an_installed_game(qapp, tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    conn.close()
    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv[1]))
    launcher = _launcher(paths, {"steam": steam.PLUGIN}, {("steam", "2")})
    backend = launcher.backend
    assert backend.count == 2
    backend.setFilter("", "", True, "title", "")
    assert backend.count == 1
    backend.setFilter("had", "", False, "title", "")
    assert backend.count == 1
    backend.setFilter("", "", True, "title", "")
    row = backend.gameModel.index(0, 0)
    ident = next(k for k, v in backend.gameModel.roleNames().items() if v == b"gameId")
    backend.openGame(backend.gameModel.data(row, ident))
    assert backend.current["title"] == "Doom" and backend.current["installed"] is True
    backend.launch(backend.current["gameId"])
    _until(qapp, lambda: opened)
    assert opened == ["steam://rungameid/2"]
    backend.closeDown()


def test_search_marks_what_you_own(qapp, tmp_path):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("store", "1", "Hades")], store="store")
    conn.close()
    store = Provider("store", "s", (), search=lambda q: [SearchHit("store", "1", "Hades", "https://x/1", "9 USD"), SearchHit("store", "2", "Doom", "https://x/2")])
    launcher = _launcher(paths, {"store": store})
    launcher.backend.search("ha")
    _until(qapp, lambda: len(launcher.backend.hits) == 2)
    assert [h["owned"] for h in launcher.backend.hits] == [True, False]
    launcher.backend.closeDown()


def _view_world(tmp_path):
    paths = _paths(tmp_path)
    marker = tmp_path / "marker"
    fetched = {"people": 0}
    gate = threading.Event()

    def mark(ctx, args):
        marker.write_text(" ".join(args))
        return CommandResult(None, "marked\x1b[31m alice")

    def people(settings):
        fetched["people"] += 1
        state = marker.read_text().split()[-1] if marker.exists() else "online"
        return ViewTable(("Name", "State"), (ViewRow("alice", ("Alice", state), (ViewAction("Mark away", "mark", ("alice", "away")),)),))

    def flaky(settings):
        gate.wait(5)
        raise LudexError("rate_limited", "try later")

    provider = Provider(
        "demo", "Demo", (), commands=(Command("mark", "mark", mark),),
        views=(View("people", "People <b>", people), View("status", "Status", lambda s: ViewDetail((("State", "Ready"),))), View("flaky", "Flaky", flaky)),
    )
    return paths, marker, fetched, gate, provider


def test_plugin_views_are_pages_and_an_action_runs_only_after_confirmation(qapp, tmp_path):
    paths, marker, fetched, _, provider = _view_world(tmp_path)
    launcher = _launcher(paths, {"demo": provider})
    views = launcher.backend.views
    assert [v.title for v in views] == ["People <b>", "Status", "Flaky"]
    assert fetched["people"] == 0  # nothing is fetched until the page is opened
    people = views[0]
    people.ensureLoaded()
    _until(qapp, lambda: len(people.rows) == 1)
    assert people.rows[0]["cells"] == ["Alice", "online"] and fetched["people"] == 1
    text = people.confirmText(0, 0)
    assert "Mark away" in text and not marker.exists()  # asking changes nothing
    generation = people.generation
    assert people.runAction(generation - 1, 0, 0) is False and not marker.exists()  # a stale snapshot is refused
    assert people.runAction(generation, 0, 0) is True
    _until(qapp, lambda: len(people.rows) == 1 and people.rows[0]["cells"][1] == "away")
    assert marker.read_text() == "alice away" and fetched["people"] == 2
    assert "\x1b" not in launcher.backend.status  # control characters are not shown
    launcher.backend.closeDown()


def test_a_slow_failure_lands_on_its_own_page_and_refresh_retries(qapp, tmp_path):
    paths, _, _, gate, provider = _view_world(tmp_path)
    launcher = _launcher(paths, {"demo": provider})
    _, status, flaky = launcher.backend.views
    flaky.ensureLoaded()
    assert flaky.busy
    status.ensureLoaded()  # leave while it is still fetching
    _until(qapp, lambda: len(status.rows) == 1)
    gate.set()
    _until(qapp, lambda: flaky.error != "")
    assert flaky.error == "try later" and status.rows[0]["cells"] == ["State", "Ready"] and status.error == ""
    launcher.backend.closeDown()


def test_plugin_settings_save_without_exposing_a_secret(qapp, tmp_path):
    paths = _paths(tmp_path)
    provider = Provider(
        "keyed", "K", (),
        settings=(ConfigField("token", "api key", secret=True, optional=True), ConfigField("mode", "mode", optional=True, kind="choice", choices=("a", "b"))),
        commands=(Command("noop", "n", lambda c, a: CommandResult(None, "ok")),),
    )
    launcher = _launcher(paths, {"keyed": provider})
    settings = launcher.backend.settingsController
    section = next(s for s in settings.sections if s["id"] == "plugin:keyed")
    settings.save("plugin:keyed", {"token": "s3cret", "mode": ""})
    assert get_values(paths, "keyed") == {"token": "s3cret"}
    assert "s3cret" not in repr(settings.sections)  # the secret is never handed to the UI again
    field = next(f for s in settings.sections if s["id"] == "plugin:keyed" for f in s["fields"] if f["name"] == "token")
    assert field["value"] == "" and field["hasValue"] is True and section["fields"][0]["name"] == "token"
    settings.save("plugin:keyed", {"token": "", "mode": ""})  # a blank secret keeps the saved one
    assert get_values(paths, "keyed") == {"token": "s3cret"} and "s3cret" not in launcher.backend.status
    launcher.backend.closeDown()


def _cover_world(tmp_path, calls):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("shop", "1", "Hades")], store="shop")
    conn.close()

    def cover(store_id):
        calls.append((store_id, threading.current_thread() is threading.main_thread()))
        return PNG

    return paths, {"shop": Provider("shop", "s", (), cover=cover)}


def _cover_url(launcher: Launcher) -> str:
    model = launcher.backend.gameModel
    role = next(k for k, v in model.roleNames().items() if v == b"coverUrl")
    return model.data(model.index(0, 0), role)


def test_a_cover_is_fetched_off_the_ui_thread_only_with_details_on_and_then_cached(qapp, tmp_path):
    calls: list = []
    paths, sources = _cover_world(tmp_path, calls)
    conn = connect(paths.database)
    set_auto_details(conn, False)
    conn.close()
    launcher = _launcher(paths, sources)
    game_id = 1
    launcher.backend.requestCover(game_id)
    qapp.processEvents()
    assert calls == [] and _cover_url(launcher) == ""  # auto_details is off: nothing is fetched
    conn = connect(paths.database)
    set_auto_details(conn, True)
    conn.close()
    launcher.backend.requestCover(game_id)
    _until(qapp, lambda: _cover_url(launcher) != "")
    assert calls == [("1", False)] and _cover_url(launcher).startswith("file://")
    launcher.backend.requestCover(game_id)  # now it is on disk
    qapp.processEvents()
    assert len(calls) == 1
    launcher.backend.closeDown()


def test_a_failing_cover_provider_does_not_break_the_grid(qapp, tmp_path):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("shop", "1", "Hades")], store="shop")
    set_auto_details(conn, True)
    conn.close()

    def cover(store_id):
        raise LudexError("cover_failed", "no luck")

    launcher = _launcher(paths, {"shop": Provider("shop", "s", (), cover=cover)})
    launcher.backend.requestCover(1)
    _until(qapp, lambda: launcher.backend.status == "covers: no luck")
    assert launcher.backend.count == 1 and _cover_url(launcher) == ""
    launcher.backend.closeDown()


def test_folders_round_trip_through_file_urls_even_with_url_characters(qapp, tmp_path):
    launcher = _launcher(_paths(tmp_path), {})
    backend = launcher.backend
    folder = "/tmp/Games#1 100%"
    assert backend.localPath(backend.folderUrl(folder)) == folder
    backend.closeDown()


def test_a_plugin_is_added_in_the_background_and_reported(qapp, tmp_path, monkeypatch):
    import ludex_gui.settings as settings_mod

    seen: list = []
    monkeypatch.setattr(settings_mod, "add_plugin", lambda spec: seen.append((spec, threading.current_thread() is threading.main_thread())) or {"name": "demo", "version": "1.0", "providers": ["demo"]})
    launcher = _launcher(_paths(tmp_path), {})
    controller = launcher.backend.settingsController
    notes: list = []
    controller.notice.connect(lambda text, bad: notes.append((text, bad)))
    controller.addPlugin("git+https://example.org/demo")
    assert controller.installing
    _until(qapp, lambda: not controller.installing)
    assert seen == [("git+https://example.org/demo", False)]
    assert notes[-1] == ("added plugin demo 1.0; restart ludex to load it", False)
    launcher.backend.closeDown()


def test_a_plugin_is_updated_in_the_background_and_a_failure_is_reported(qapp, tmp_path, monkeypatch):
    import ludex_gui.settings as settings_mod

    results = [[{"name": "demo", "ok": True, "from": "1.0", "to": "1.1"}], [{"name": "demo", "ok": False, "error": {"code": "install_failed", "message": "network down"}}]]
    seen: list = []
    monkeypatch.setattr(settings_mod, "update_plugins", lambda name: seen.append((name, threading.current_thread() is threading.main_thread())) or results.pop(0))
    launcher = _launcher(_paths(tmp_path), {})
    controller = launcher.backend.settingsController
    notes: list = []
    controller.notice.connect(lambda text, bad: notes.append((text, bad)))
    for expected in (("updated plugin demo to 1.1; restart ludex to load it", False), ("plugin: network down", True)):
        controller.updatePlugin("demo")
        assert controller.installing
        _until(qapp, lambda: not controller.installing)
        assert notes[-1] == expected
    assert seen == [("demo", False), ("demo", False)]
    launcher.backend.closeDown()


def test_removing_a_plugin_reports_it_and_an_unknown_one_is_refused(qapp, tmp_path, monkeypatch):
    import ludex_gui.settings as settings_mod

    gone: list = []
    monkeypatch.setattr(settings_mod, "remove_plugin", lambda name: gone.append(name) or {"name": name, "providers": []})
    launcher = _launcher(_paths(tmp_path), {})
    controller = launcher.backend.settingsController
    notes: list = []
    controller.notice.connect(lambda text, bad: notes.append((text, bad)))
    controller.removePlugin("demo")
    assert gone == ["demo"] and notes[-1] == ("removed plugin demo; restart ludex to unload it", False)
    monkeypatch.undo()
    controller.removePlugin("nope")
    assert notes[-1][1] is True and "no managed plugin named nope" in notes[-1][0]
    launcher.backend.closeDown()


def test_launch_options_round_trip_and_reject_a_bad_environment_line(qapp, tmp_path):
    from ludex.game_settings import get_settings

    paths = _paths(tmp_path)
    folder = tmp_path / "game"
    folder.mkdir()
    (folder / "run.sh").write_text("#!/bin/sh\n")
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("shop", "1", "Hades")], store="shop")
    import_account(conn, "m", [OwnedGame("plain", "2", "Doom")], store="plain")
    conn.close()
    sources = {"shop": Provider("shop", "s", (), game_folder=lambda config, store_id: folder), "plain": Provider("plain", "p", ())}
    launcher = _launcher(paths, sources)
    backend = launcher.backend
    ident = {"Hades": 1, "Doom": 2}
    info = backend.gameSettings(ident["Hades"])
    assert info["available"] is True and info["runner"] == "" and info["args"] == "" and "run.sh" in info["candidates"]
    assert backend.gameSettings(ident["Doom"])["available"] is False
    backend.saveGameSettings(ident["Hades"], {"runner": "", "prefix": "", "executable": "run.sh", "args": "--fullscreen 'a b'", "env": "A=1\n\nB=x=y"})
    conn = connect(paths.database)
    saved = get_settings(conn, "shop", "1")
    assert saved.executable == "run.sh" and saved.args == ("--fullscreen", "a b") and saved.env == {"A": "1", "B": "x=y"}
    backend.saveGameSettings(ident["Hades"], {"env": "no equals sign"})
    assert backend.statusError and get_settings(conn, "shop", "1") == saved  # a rejected form changes nothing
    assert backend.gameSettings(ident["Hades"])["args"] == "--fullscreen 'a b'"
    conn.close()
    backend.closeDown()


def test_an_account_is_added_imported_and_removed_from_settings(qapp, tmp_path):
    paths = _paths(tmp_path)
    shop = Provider("shop", "A shop", (ConfigField("token", "the token", secret=True),), fetch=lambda config: FetchResult([OwnedGame("shop", "1", "Hades")], True, "fake"))
    launcher = _launcher(paths, {"shop": shop})
    backend, controller = launcher.backend, launcher.backend.settingsController
    form = controller.accountForm("shop")
    assert form["name"] == "shop" and [f["name"] for f in form["fields"]] == ["token"] and form["fields"][0]["kind"] == "secret"
    assert controller.accountForm("nope") == {}
    notes: list = []
    controller.notice.connect(lambda text, bad: notes.append((text, bad)))
    assert controller.addAccount("shop", "shop", {"token": ""}) is False  # a required field must be given
    assert notes[-1][1] is True
    assert controller.addAccount("shop", "shop", {"token": "s3cret"}) is True
    assert controller.accountForm("shop")["name"] == "shop2"
    _until(qapp, lambda: backend.count == 1)
    assert "s3cret" not in repr([s for s in controller.sections])
    controller.removeAccount("shop:shop")
    assert backend.count == 0 and not [s for s in controller.sections if s["id"] == "account:shop:shop"]
    backend.closeDown()


def test_a_match_is_chosen_off_the_ui_thread_then_cleared(qapp, tmp_path):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("local", "1", "hades_v1.2")], store="local")
    conn.close()
    db = Provider(
        "db", "A database", (), match=lambda query: [SearchHit("db", "77", "Hades", "https://x/hades")],
        metadata=lambda store_id: Metadata("Escape.", ("Roguelike",), ("Supergiant",), "2020"),
    )
    launcher = _launcher(paths, {"local": Provider("local", "l", ()), "db": db})
    backend = launcher.backend
    assert backend.canMatch and backend.matchQuery(1) == "hades"
    backend.findMatches("hades")
    _until(qapp, lambda: backend.matches)
    assert [(m["plugin"], m["title"]) for m in backend.matches] == [("db", "Hades")]
    backend.chooseMatch(1, 0)
    _until(qapp, lambda: backend.current.get("matched"))
    assert backend.current["title"] == "Hades" and backend.current["genres"] == "Roguelike"
    backend.chooseMatch(1, -1)
    _until(qapp, lambda: not backend.current.get("matched"))
    assert backend.current["title"] == "hades_v1.2"


def test_genres_filter_the_grid_and_details_are_fetched_for_every_game_on_request(qapp, tmp_path):
    from ludex.plugins import Metadata

    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("shop", "1", "Hades"), OwnedGame("shop", "2", "Portal")], store="shop")
    conn.close()
    genres = {"1": ("Action",), "2": ("Puzzle",)}
    shop = Provider("shop", "s", (), metadata=lambda store_id: Metadata("d", genres[store_id]))
    launcher = _launcher(paths, {"shop": shop})
    backend = launcher.backend
    assert backend.genres == [] and backend.missingDetails == 2 and backend.fetchingDetails == ""
    backend.fetchAllDetails()
    assert backend.fetchingDetails != ""
    _until(qapp, lambda: backend.fetchingDetails == "")
    assert backend.missingDetails == 0 and [(g["genre"], g["games"]) for g in backend.genres] == [("Action", 1), ("Puzzle", 1)]
    backend.setFilter("", "", False, "title", "puzzle")
    assert backend.count == 1 and backend.gameModel.row(0)["title"] == "Portal"
    backend.setFilter("", "", False, "title", "")
    assert backend.count == 2
    backend.closeDown()


def test_no_screen_renders_text_as_markup():
    import re

    for path in QML_DIR.glob("*.qml"):
        if path.name != "Txt.qml":
            assert not re.search(r"\b(Text|Label)\s*\{", path.read_text()), path.name


def test_the_gui_command_explains_a_missing_ludex_gui(monkeypatch, capsys, tmp_path):
    import sys

    from ludex_cli.cli import main

    monkeypatch.setenv("LUDEX_HOME", str(_paths(tmp_path).root))

    class Gone:  # as if the package were not installed
        @staticmethod
        def find_spec(name, path=None, target=None):
            if name == "ludex_gui":
                raise ModuleNotFoundError("No module named 'ludex_gui'", name="ludex_gui")

    for name in ("ludex_gui", "ludex_gui.app"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [Gone, *sys.meta_path])
    assert main(["--json", "gui"]) == 1
    assert '"gui_missing"' in capsys.readouterr().err


class _FakeSource:
    def __init__(self) -> None:
        self.events: list[tuple[str, bool]] = []
        self.closed = False

    def poll(self):
        out, self.events = self.events, []
        return out

    def close(self) -> None:
        self.closed = True


def _padded(qapp, tmp_path, monkeypatch, installed=frozenset(), focused=True, console=False):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    conn.close()
    launcher = _launcher(paths, {"steam": steam.PLUGIN}, installed, console)
    window = launcher.window
    monkeypatch.setattr(gamepad_mod.QGuiApplication, "focusWindow", staticmethod(lambda: window if focused else None))
    pad = gamepad_mod.Gamepad(window, _FakeSource())
    grid = window.findChild(QObject, "grid")
    _until(qapp, lambda: grid.property("count") == 2)
    grid.forceActiveFocus()
    grid.setProperty("currentIndex", 0)
    qapp.processEvents()
    return launcher, window, pad


def test_the_pad_moves_through_the_grid_and_opens_and_closes_a_game(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch)
    grid = window.findChild(QObject, "grid")
    assert grid.property("currentIndex") == 0
    pad.press("dpright")
    pad.release("dpright")
    assert grid.property("currentIndex") == 1
    pad.press("a")
    _until(qapp, lambda: launcher.backend.current.get("gameId") is not None)
    pad.press("b")
    _until(qapp, lambda: launcher.backend.current.get("gameId") is None)
    pad.close()
    launcher.backend.closeDown()


def test_an_arrow_nothing_uses_moves_focus_to_the_nearest_control_that_way(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch)
    refresh = next(b for b in window.findChildren(QObject) if b.property("text") == "Refresh" and b.property("visible"))
    refresh.forceActiveFocus()
    qapp.processEvents()
    assert window.activeFocusItem() is refresh
    assert gamepad_mod.send_key(window, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier)
    neighbour = window.activeFocusItem()
    assert neighbour is not refresh and neighbour.x() < refresh.x() + 1
    assert gamepad_mod.send_key(window, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    assert window.activeFocusItem() is refresh
    assert not gamepad_mod.send_key(window, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    assert window.activeFocusItem() is refresh
    launcher.backend.closeDown()


def test_the_bumpers_change_page_but_not_under_a_dialog(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch)
    assert window.property("section") == "library"
    pad.press("rightshoulder")
    assert window.property("section") == "installed"
    pad.press("leftshoulder")
    pad.press("leftshoulder")
    assert window.property("section") == "settings"
    dialog = window.findChild(QObject, "trust")
    dialog.open()
    _until(qapp, lambda: dialog.property("visible"))
    dialog.property("contentItem").forceActiveFocus()
    pad.press("rightshoulder")
    assert window.property("section") == "settings"
    launcher.backend.closeDown()


def test_x_plays_the_current_installed_game(qapp, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv[1]))
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch, {("steam", "1"), ("steam", "2")})
    pad.press("dpright")
    pad.release("dpright")
    pad.press("x")
    _until(qapp, lambda: opened)
    assert opened == ["steam://rungameid/1"]
    launcher.backend.closeDown()


def test_the_pad_does_nothing_while_the_window_is_not_focused(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch, focused=False)
    pad.press("dpright")
    assert window.findChild(QObject, "grid").property("currentIndex") == 0
    launcher.backend.closeDown()


def test_without_the_gamepad_extra_there_is_no_source(monkeypatch):
    monkeypatch.setitem(sys.modules, "sdl2", None)
    assert gamepad_mod.open_sdl_source() is None


def test_return_opens_a_combo_and_the_list_stays_open_after_the_key_is_released(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch)
    box = window.findChild(QObject, "sortBox")
    box.forceActiveFocus()
    qapp.processEvents()
    pad.press("a")
    qapp.processEvents()
    assert box.property("down")
    launcher.backend.closeDown()


def test_a_stick_held_right_survives_the_other_pad_centering_and_releases_when_pushed_back():
    class _Sdl:
        SDL_CONTROLLER_AXIS_LEFTX, SDL_CONTROLLER_AXIS_LEFTY = 0, 1

        def SDL_Event(self):
            return None

    source = gamepad_mod._SdlSource(_Sdl())
    out: list[tuple[str, bool]] = []
    source._axis(1, 0, 20000, out)
    source._axis(2, 0, 0, out)
    assert out == [("dpright", True)]
    out.clear()
    source._axis(1, 0, -12000, out)
    assert out == [("dpright", False)]


def test_y_jumps_to_the_search_field_and_start_opens_the_menu_with_a_working_quit(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch)
    pad.press("y")
    _until(qapp, lambda: window.activeFocusItem() is not None and window.activeFocusItem().property("cursorPosition") is not None)
    pad.release("y")
    window.findChild(QObject, "grid").forceActiveFocus()
    qapp.processEvents()
    pad.press("start")
    menu = window.findChild(QObject, "menu")
    _until(qapp, lambda: menu.property("visible"))
    pad.press("start")  # a second press under the open menu changes nothing
    assert menu.property("visible")
    pad.press("b")
    _until(qapp, lambda: not menu.property("visible"))
    launcher.backend.closeDown()


def test_console_mode_goes_fullscreen_and_shows_the_controller_hints(qapp, tmp_path, monkeypatch):
    launcher, window, pad = _padded(qapp, tmp_path, monkeypatch, console=True)
    assert window.visibility() == QWindow.Visibility.FullScreen
    assert window.findChild(QObject, "hints").property("visible")
    launcher.backend.closeDown()


def test_console_mode_scales_the_ui_unless_the_user_chose_a_scale():
    env: dict[str, str] = {}
    console_environment(env)
    assert env == {"QT_SCALE_FACTOR": "1.25"}
    env = {"QT_SCALE_FACTOR": "2"}
    console_environment(env)
    assert env == {"QT_SCALE_FACTOR": "2"}


def test_menu_entries_are_written_quoted_and_removed_again(tmp_path):
    from ludex_gui import desktop

    launcher = tmp_path / "my tools" / "ludex-gui"
    first = desktop.install(tmp_path / "data", launcher)
    assert desktop.install(tmp_path / "data", launcher) == first
    plain = (tmp_path / "data" / "applications" / "ludex.desktop").read_text()
    console = (tmp_path / "data" / "applications" / "ludex-console.desktop").read_text()
    assert f'Exec="{launcher}"\n' in plain
    assert f'Exec="{launcher}" --console\n' in console
    assert "Icon=ludex\n" in plain and "Categories=Game;" in plain
    assert (tmp_path / "data" / "icons" / "hicolor" / "scalable" / "apps" / "ludex.svg").read_text().startswith("<svg")
    assert not list((tmp_path / "data").rglob("*.tmp"))
    assert sorted(desktop.uninstall(tmp_path / "data")) == sorted(first)
    assert desktop.uninstall(tmp_path / "data") == []


def test_the_data_directory_follows_xdg_only_for_an_absolute_path(tmp_path):
    from ludex_gui import desktop

    assert desktop.data_home({"XDG_DATA_HOME": "/srv/data"}, tmp_path) == Path("/srv/data")
    assert desktop.data_home({"XDG_DATA_HOME": "data"}, tmp_path) == tmp_path / ".local" / "share"
    assert desktop.data_home({}, tmp_path) == tmp_path / ".local" / "share"


def test_the_window_icon_renders(qapp):
    from importlib import resources

    from PySide6.QtGui import QIcon

    icon = QIcon(str(resources.files("ludex_gui") / "assets" / "ludex.svg"))
    assert not icon.pixmap(64, 64).isNull()


def test_ludex_gui_install_desktop_reports_the_files_it_wrote(monkeypatch, capsys, tmp_path):
    import json

    from ludex_cli.cli import main

    monkeypatch.setenv("LUDEX_HOME", str(_paths(tmp_path).root))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert main(["--json", "gui", "--install-desktop"]) == 0
    files = json.loads(capsys.readouterr().out)["data"]["files"]
    assert str(tmp_path / "xdg" / "applications" / "ludex.desktop") in files
    assert (tmp_path / "xdg" / "applications" / "ludex-console.desktop").is_file()
    assert main(["--json", "gui", "--uninstall-desktop"]) == 0
    assert not (tmp_path / "xdg" / "applications" / "ludex.desktop").exists()
