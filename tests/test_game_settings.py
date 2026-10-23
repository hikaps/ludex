from __future__ import annotations

import os
from pathlib import Path

import pytest

from ludex.errors import LudexError
from ludex.game_settings import get_settings, pick_copy, update_settings
from ludex.library import delete_account_records, import_account
from ludex.plugins import OwnedGame
from ludex.runners import find_runners, resolve_runner
from ludex.storage import connect


def _proton(folder: Path) -> Path:
    folder.mkdir(parents=True)
    (folder / "proton").write_text("#!/bin/sh\n")
    (folder / "proton").chmod(0o755)
    return folder


def test_find_runners_scans_known_folders_and_dedupes(tmp_path):
    steam = tmp_path / ".local/share/Steam"
    _proton(steam / "compatibilitytools.d/GE-Proton9-1")
    _proton(steam / "steamapps/common/Proton 9.0")
    _proton(steam / "steamapps/common/Other Tool")  # not a Proton build
    _proton(tmp_path / ".config/heroic/tools/proton/Proton-CachyOS")
    (steam / "compatibilitytools.d/NoScript").mkdir()
    (tmp_path / ".steam").mkdir()
    (tmp_path / ".steam/root").symlink_to(steam)  # the same folders reached through the symlink
    found = [(r.name, r.origin) for r in find_runners(tmp_path)]
    assert found == [("GE-Proton9-1", "steam"), ("Proton 9.0", "steam"), ("Proton-CachyOS", "heroic")]


def test_resolve_runner_by_name_or_path_and_unknown(tmp_path):
    _proton(tmp_path / ".local/share/Steam/compatibilitytools.d/GE-Proton9-1")
    elsewhere = _proton(tmp_path / "opt/MyProton")
    assert resolve_runner("GE-Proton9-1", tmp_path).origin == "steam"
    assert resolve_runner(str(elsewhere), tmp_path).path == elsewhere
    with pytest.raises(LudexError) as info:
        resolve_runner("nope", tmp_path)
    assert info.value.code == "runner_not_found"


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "db.sqlite3")
    import_account(connection, "disk", [OwnedGame("local", "g", "G")], store="local")
    return connection


def test_settings_merge_validate_and_clear(conn, tmp_path):
    assert get_settings(conn, "local", "g").as_dict()["env"] == {}
    update_settings(conn, "local", "g", prefix=str(tmp_path / "pfx"), env={"A": "1", "B": "2"}, args=["-w", "x y"])
    update_settings(conn, "local", "g", executable="game.exe", env={"B": "3"}, unset_env=["A"])
    s = get_settings(conn, "local", "g")
    assert (s.prefix, s.executable, s.args, s.env) == (str(tmp_path / "pfx"), "game.exe", ("-w", "x y"), {"B": "3"})
    for bad in ({"prefix": "relative"}, {"env": {"1X": "v"}}, {"executable": " "}, {"runner": "missing"}):
        with pytest.raises(LudexError) as info:
            update_settings(conn, "local", "g", **bad)
        assert info.value.code in ("invalid_setting", "runner_not_found")
    assert get_settings(conn, "local", "g") == s  # rejected changes leave it untouched
    update_settings(conn, "local", "g", clear=True, executable="other.exe")
    assert get_settings(conn, "local", "g").as_dict() == {"runner": None, "prefix": None, "executable": "other.exe", "args": [], "env": {}}


def test_settings_survive_reimport_and_go_with_the_last_copy(conn):
    update_settings(conn, "local", "g", executable="a.exe")
    import_account(conn, "disk", [OwnedGame("local", "g", "G")], store="local")
    assert get_settings(conn, "local", "g").executable == "a.exe"
    delete_account_records(conn, "disk", store="local")
    assert get_settings(conn, "local", "g").executable is None


def test_pick_copy_needs_a_choice_between_stores(conn):
    import_account(conn, "m", [OwnedGame("steam", "1", "G")], store="steam")
    assert pick_copy(conn, 1, "local") == ("local", "g")
    with pytest.raises(LudexError) as info:
        pick_copy(conn, 1)
    assert info.value.code == "copy_ambiguous"
    with pytest.raises(LudexError) as info:
        pick_copy(conn, 1, "epic")
    assert info.value.code == "not_owned"
