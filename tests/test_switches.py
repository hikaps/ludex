from __future__ import annotations

import pytest

from ludex.accounts import add_account, list_accounts
from ludex.errors import LudexError
from ludex.library import list_games
from ludex.paths import StatePaths
from ludex.plugins import FetchResult, OwnedGame, Provider, SourceError
from ludex.storage import connect
from ludex.switches import get_switch, set_switch


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    paths = StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")
    return paths, connect(paths.database)


def _provider(name, games=None, fail=False):
    def fetch(config):
        if fail:
            raise SourceError("nope", "no folder")
        return FetchResult([OwnedGame(name, "1", "Hades")], True, None)

    return {name: Provider(name, name, (), fetch)}


def test_on_adds_an_account_and_imports_then_off_deletes_both(env):
    paths, conn = env
    providers = _provider("shortcuts")
    assert not get_switch(paths, "steam_shortcuts")
    assert set_switch(paths, conn, providers, "steam_shortcuts", True) == 1
    assert get_switch(paths, "steam_shortcuts") and [g["title"] for g in list_games(conn)] == ["Hades"]
    assert set_switch(paths, conn, providers, "steam_shortcuts", True) == 0  # already on: nothing more
    set_switch(paths, conn, providers, "steam_shortcuts", False)
    assert not get_switch(paths, "steam_shortcuts") and list_games(conn) == []
    assert set_switch(paths, conn, providers, "steam_shortcuts", True) == 1  # comes back


def test_off_removes_every_account_of_that_source_only(env):
    paths, conn = env
    add_account(paths, "mine", "shortcuts", {})
    add_account(paths, "keep", "steam", {})
    set_switch(paths, conn, {}, "steam_shortcuts", False)
    assert list_accounts(paths) == [("keep", "steam")]


def test_failed_import_leaves_the_switch_off(env):
    paths, conn = env
    with pytest.raises(LudexError):
        set_switch(paths, conn, _provider("heroic", fail=True), "heroic_sideload", True)
    assert not get_switch(paths, "heroic_sideload") and list_accounts(paths) == []


def test_unknown_switch_is_rejected(env):
    paths, conn = env
    with pytest.raises(LudexError):
        set_switch(paths, conn, {}, "nope", True)
