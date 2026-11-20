from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject
from PySide6.QtGui import QGuiApplication

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
from ludex_gui.app import QML_DIR, Launcher, build_engine

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


def _launcher(paths, sources, installed=frozenset()) -> Launcher:
    return build_engine(paths, sources, lambda: set(installed), lambda store, account: {}, lambda conn: {}, paths.root / "prefixes")


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
    backend.setFilter("", "", True, "title")
    assert backend.count == 1
    backend.setFilter("had", "", False, "title")
    assert backend.count == 1
    backend.setFilter("", "", True, "title")
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
