from __future__ import annotations

import pytest

from ludex.account_setup import create_account, delete_account
from ludex.accounts import get_account, list_accounts
from ludex.errors import LudexError
from ludex.library import import_account, list_games
from ludex.paths import StatePaths
from ludex.plugins import ConfigField, FetchResult, OwnedGame, Provider
from ludex.storage import connect


def _paths(tmp_path) -> StatePaths:
    root = tmp_path / "home"
    root.mkdir(mode=0o700)
    return StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")


PLUGIN = Provider("shop", "s", (ConfigField("token", "t", secret=True), ConfigField("note", "n", optional=True)), fetch=lambda c: FetchResult([], True, "x"))


def test_create_account_requires_known_non_empty_fields_and_leaves_out_blank_optional_ones(tmp_path):
    paths = _paths(tmp_path)
    for values, code in (({}, "empty_value"), ({"token": "a", "bogus": "b"}, "unknown_field")):
        with pytest.raises(LudexError) as caught:
            create_account(paths, PLUGIN, "mine", values)
        assert caught.value.code == code
    create_account(paths, PLUGIN, "mine", {"token": "a", "note": ""})
    assert dict(get_account(paths, "shop:mine").config) == {"token": "a"}
    with pytest.raises(LudexError):
        create_account(paths, Provider("view", "v", ()), "x", {})


def test_delete_account_removes_its_records_and_keeps_games_another_account_owns(tmp_path):
    paths = _paths(tmp_path)
    create_account(paths, PLUGIN, "mine", {"token": "a"})
    conn = connect(paths.database)
    import_account(conn, "mine", [OwnedGame("shop", "1", "Hades"), OwnedGame("shop", "2", "Doom")], store="shop")
    import_account(conn, "other", [OwnedGame("shop", "2", "Doom")], store="shop")
    conn.close()
    assert delete_account(paths, "shop:mine") > 0
    assert list_accounts(paths) == []
    conn = connect(paths.database)
    assert [g["title"] for g in list_games(conn)] == ["Doom"]
