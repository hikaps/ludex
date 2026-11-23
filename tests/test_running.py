from __future__ import annotations

import json

import pytest

from ludex.accounts import add_account
from ludex.library import import_account, list_games
from ludex.paths import state_paths
from ludex.plugins import OwnedGame, Provider, SourceError
from ludex.running import running_games
from ludex.sources import heroic, steam
from ludex.storage import connect


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("LUDEX_HOME", str(tmp_path / "home"))
    paths = state_paths()
    return paths, connect(paths.database)


def _titles(conn, ids):
    return {g["title"] for g in list_games(conn) if g["id"] in ids}


def test_a_game_runs_when_a_copy_does_and_a_broken_client_is_skipped(world):
    paths, conn = world
    import_account(conn, "a", [OwnedGame("store", "1", "Up"), OwnedGame("store", "2", "Down")], store="store")
    import_account(conn, "b", [OwnedGame("bad", "9", "Unknown")], store="bad")
    store = Provider("store", "s", (), lambda c: None, running=lambda c: ["1", "7"])
    bad = Provider("bad", "b", (), lambda c: None, running=lambda c: (_ for _ in ()).throw(SourceError("x", "no")))
    quiet = Provider("quiet", "q", (), lambda c: None)
    for source in ("store", "bad", "quiet"):
        add_account(paths, "main", source, {})
    assert _titles(conn, running_games(paths, {"store": store, "bad": bad, "quiet": quiet}, conn)) == {"Up"}


def test_steam_names_the_apps_under_reaper(monkeypatch):
    monkeypatch.setattr(steam, "command_lines", lambda: [
        ["/home/u/.steam/ubuntu12_32/reaper", "SteamLaunch", "AppId=1245620", "--", "/proton", "run", "eldenring.exe"],
        ["/usr/bin/firefox", "AppId=999"],  # not a Steam launch
        ["/usr/bin/steam"],
    ])
    assert steam.running({}) == {"1245620"}


def test_heroic_names_games_whose_program_is_running(tmp_path, monkeypatch):
    games = [
        {"app_name": "bg3", "title": "BG3", "runner": "sideload", "is_installed": True, "folder_name": "/mnt/g/bg3/bin", "install": {"executable": "/mnt/g/bg3/bin/bg3.exe"}},
        {"app_name": "gow", "title": "GoW", "runner": "sideload", "is_installed": True, "folder_name": "/mnt/g/gow", "install": {"executable": "/mnt/g/gow/gow.exe"}},
        {"app_name": "nat", "title": "Native", "runner": "sideload", "is_installed": True, "folder_name": "/mnt/g/nat", "install": {"executable": "/mnt/g/nat/run.sh"}},
        {"app_name": "off", "title": "Off", "runner": "sideload", "is_installed": False, "folder_name": "/mnt/g/off", "install": {}},
    ]
    (tmp_path / "sideload_apps").mkdir()
    (tmp_path / "sideload_apps" / "library.json").write_text(json.dumps({"games": games}))
    monkeypatch.setattr(heroic, "command_lines", lambda: [
        ["wine64", "Z:\\mnt\\g\\bg3\\bin\\bg3.exe"],   # Wine shows a Windows path
        ["/mnt/g/nat/run.sh"],                          # a native game is its own program
        ["nano", "/mnt/g/gow/notes.txt"],               # a file in the folder is not the game
        ["bash"],
    ])
    assert sorted(heroic.running({"heroic_dir": str(tmp_path)})) == ["bg3", "nat"]
