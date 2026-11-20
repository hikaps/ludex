from __future__ import annotations

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton

from ludex import launch as launch_mod
from ludex.errors import LudexError
from ludex.library import import_account
from ludex.paths import StatePaths
from ludex.plugins import Command, CommandResult, ConfigField, OwnedGame, Provider, SearchHit, View, ViewAction, ViewDetail, ViewRow, ViewTable
from ludex.provider_settings import get_values
from ludex.sources import steam
from ludex.storage import connect
from ludex_gui.app import MainWindow
from ludex_gui.views import ViewPage


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


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


def _window(paths, sources, installed=frozenset()) -> MainWindow:
    return MainWindow(paths, sources, lambda: set(installed), lambda store, account: {}, lambda conn: {}, paths.root / "prefixes", auto_refresh=False)


def _row(window: MainWindow, label: str) -> None:
    window.drawer.setCurrentRow(next(i for i in range(window.drawer.count()) if window.drawer.item(i).text() == label))


def test_library_filters_launches_the_selected_installed_game(qapp, tmp_path, monkeypatch):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    conn.close()
    opened = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: opened.append(argv[1]))
    window = _window(paths, {"steam": steam.PLUGIN}, {("steam", "2")})
    assert window.owned_table.rowCount() == 2 and window.installed_table.rowCount() == 1
    _row(window, "Installed")
    window.installed_table.selectRow(0)
    assert "Doom" in window.detail.toPlainText() and "installed" in window.detail.toPlainText()
    window._filters[window.owned].setText("had")
    assert window.owned_table.rowCount() == 1 and window.installed_table.rowCount() == 1
    window._launch()
    assert opened == ["steam://rungameid/2"]
    window.close()


def test_search_marks_what_you_own(qapp, tmp_path):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("store", "1", "Hades")], store="store")
    conn.close()
    store = Provider("store", "s", (), search=lambda q: [SearchHit("store", "1", "Hades", "https://x/1", "9 USD"), SearchHit("store", "2", "Doom", "https://x/2")])
    window = _window(paths, {"store": store})
    _row(window, "Search")
    window.query_box.setText("ha")
    window._search()
    _until(qapp, lambda: window.hits_table.rowCount() == 2)
    assert [window.hits_table.item(r, 3).text() for r in range(2)] == ["yes", ""]
    window.hits_table.selectRow(0)
    assert "you own this" in window.detail.toPlainText()
    window.close()


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


def test_plugin_views_are_drawer_entries_and_an_action_runs_only_after_confirmation(qapp, tmp_path, monkeypatch):
    paths, marker, fetched, _, provider = _view_world(tmp_path)
    window = _window(paths, {"demo": provider})
    labels = [window.drawer.item(i).text() for i in range(window.drawer.count())]
    assert labels[:5] == ["Owned", "Installed", "Search", "Jobs", "Settings"] and labels[-3:] == ["People <b>", "Status", "Flaky"]
    assert fetched["people"] == 0  # nothing is fetched until the entry is opened
    window.show()
    _row(window, "People <b>")
    page = window.view_pages[("demo", "people")]
    _until(qapp, lambda: page.table.rowCount() == 1)
    assert [page.table.item(0, c).text() for c in range(2)] == ["Alice", "online"] and fetched["people"] == 1
    assert not page.actions_button.isEnabled()  # no row selected yet
    page.table.selectRow(0)
    assert page.actions_button.isEnabled()

    answers = [False, True]
    monkeypatch.setattr(ViewPage, "_confirmed", lambda self, row, action: answers.pop(0))
    for _ in range(2):  # the user picks the entry twice: declined, then confirmed
        page._choose_action()
        page.menu.actions()[0].trigger()
        if answers:
            assert not marker.exists()
    _until(qapp, lambda: page.table.rowCount() == 1 and page.table.item(0, 1).text() == "away")
    assert marker.read_text() == "alice away" and fetched["people"] == 2
    assert window.status.text().startswith("marked") and "\x1b" not in window.status.text()  # control characters are not shown
    window.close()


def test_a_slow_failure_lands_on_its_own_page_and_refresh_retries(qapp, tmp_path):
    paths, _, fetched, gate, provider = _view_world(tmp_path)
    window = _window(paths, {"demo": provider})
    window.show()
    _row(window, "Flaky")
    flaky = window.view_pages[("demo", "flaky")]
    assert flaky.status.text() == "Loading…" and not flaky.refresh_button.isEnabled()
    _row(window, "Status")  # leave while it is still fetching
    status = window.view_pages[("demo", "status")]
    _until(qapp, lambda: status.table.rowCount() == 1)
    gate.set()
    _until(qapp, lambda: flaky.error is not None)
    assert flaky.status.text() == "try later. Press Refresh to retry."
    assert [status.table.item(0, c).text() for c in range(2)] == ["State", "Ready"] and status.error is None
    window.close()


def test_plugin_settings_save_without_showing_a_secret(qapp, tmp_path):
    paths = _paths(tmp_path)
    provider = Provider(
        "keyed", "K", (),
        settings=(ConfigField("token", "api key", secret=True, optional=True), ConfigField("mode", "mode", optional=True, kind="choice", choices=("a", "b"))),
        commands=(Command("noop", "n", lambda c, a: CommandResult(None, "ok")),),
    )
    window = _window(paths, {"keyed": provider})
    token = next(w for w in window.settings.findChildren(QLineEdit) if w.echoMode() == QLineEdit.EchoMode.Password)
    save = next(b for b in window.settings.findChildren(QPushButton) if b.text() == "Save" and b.parent().title() == "keyed settings")
    token.setText("s3cret")
    save.click()
    assert get_values(paths, "keyed") == {"token": "s3cret"}
    assert token.text() == "" and token.placeholderText() == "(set; type to replace)"  # the secret is not shown again
    save.click()  # nothing edited: nothing changes
    assert get_values(paths, "keyed") == {"token": "s3cret"} and "s3cret" not in window.status.text()
    window.close()


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
