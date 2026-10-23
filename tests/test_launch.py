from __future__ import annotations

import subprocess

import pytest

from ludex import launch as launch_mod
from ludex.errors import LudexError
from ludex.library import import_account
from ludex.plugins import OwnedGame, SourcePlugin
from ludex.sources import epic, steam
from ludex.storage import connect


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "db.sqlite3")


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: calls.append(argv))
    return calls


def test_urls_encode_the_store_id():
    assert steam.PLUGIN.launch_url("220") == "steam://rungameid/220"
    assert epic.PLUGIN.launch_url("a b&c") == "heroic://launch?appName=a%20b%26c&runner=legendary"


def test_launch_opens_the_plugin_url_with_xdg_open(conn, opened):
    import_account(conn, "main", [OwnedGame("steam", "220", "HL2")], store="steam")
    assert launch_mod.launch_game(conn, {"steam": steam.PLUGIN}, 1) == "steam:220"
    assert opened == [["xdg-open", "steam://rungameid/220"]]


def test_several_launchable_stores_need_a_choice_and_local_is_not_launchable(conn, opened):
    import_account(conn, "main", [OwnedGame("steam", "1", "Hades")], store="steam")
    import_account(conn, "main", [OwnedGame("epic", "h", "Hades")], store="epic")
    import_account(conn, "main", [OwnedGame("local", "x", "Hades")], store="local")
    sources = {"steam": steam.PLUGIN, "epic": epic.PLUGIN, "local": SourcePlugin("local", "l", (), lambda c: None)}
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, sources, 1)
    assert info.value.code == "launch_ambiguous"
    assert launch_mod.launch_game(conn, sources, 1, "epic") == "epic:h"
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, sources, 1, "local")
    assert info.value.code == "not_launchable"


def test_failed_open_is_reported_without_the_url(conn, monkeypatch):
    import_account(conn, "main", [OwnedGame("steam", "220", "HL2")], store="steam")

    def boom(argv, **kw):
        raise subprocess.CalledProcessError(3, argv)

    monkeypatch.setattr(launch_mod.subprocess, "run", boom)
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, {"steam": steam.PLUGIN}, 1)
    assert info.value.code == "launch_failed" and "steam://" not in info.value.message
