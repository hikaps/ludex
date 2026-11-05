from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from ludex.accounts import add_account, get_account, list_accounts, remove_account
from ludex.errors import LudexError
from ludex.paths import state_paths


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "home"
    root.mkdir()
    root.chmod(0o700)
    monkeypatch.setenv("LUDEX_HOME", str(root))
    return root


def test_state_paths_honors_ludex_home(home: Path) -> None:
    paths = state_paths()
    assert paths.root == home
    assert paths.accounts.parent == home
    assert paths.database.parent == home
    assert paths.import_lock.parent == home


def test_state_paths_creates_private_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LUDEX_HOME", str(tmp_path / "new" / "state"))
    paths = state_paths()
    assert stat.S_IMODE(paths.root.stat().st_mode) == 0o700


def test_state_paths_uses_xdg_data_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LUDEX_HOME", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert state_paths().root == tmp_path / "xdg" / "ludex"


def test_state_paths_rejects_open_mode(home: Path) -> None:
    home.chmod(0o755)
    with pytest.raises(PermissionError):
        state_paths()


def test_state_paths_rejects_symlink_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real)
    monkeypatch.setenv("LUDEX_HOME", str(link))
    with pytest.raises(PermissionError):
        state_paths()


def test_missing_accounts_file_means_no_accounts(home: Path) -> None:
    assert list_accounts(state_paths()) == []


def test_add_get_round_trip_and_modes(home: Path) -> None:
    paths = state_paths()
    add_account(paths, "main", "steam", {"api_key": "SECRET", "steam_id": "1"})
    assert stat.S_IMODE(paths.accounts.stat().st_mode) == 0o600
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    account = get_account(paths, "main")
    assert (account.name, account.source) == ("main", "steam")
    assert dict(account.config) == {"api_key": "SECRET", "steam_id": "1"}
    assert json.loads(paths.accounts.read_text()) == {"steam:main": {"source": "steam", "config": {"api_key": "SECRET", "steam_id": "1"}}}
    assert [p.name for p in home.iterdir() if p.name.endswith(".tmp")] == []


def test_duplicate_account_rejected_and_original_kept(home: Path) -> None:
    paths = state_paths()
    add_account(paths, "main", "steam", {"k": "1"})
    with pytest.raises(LudexError) as caught:
        add_account(paths, "main", "steam", {"k": "2"})
    assert caught.value.code == "account_exists"
    assert dict(get_account(paths, "main").config) == {"k": "1"}


def test_same_name_in_two_sources_needs_qualifying_and_legacy_files_load(home: Path) -> None:
    paths = state_paths()
    paths.accounts.write_text(json.dumps({"main": {"source": "steam", "config": {}}}))
    paths.accounts.chmod(0o600)
    assert get_account(paths, "main").source == "steam"
    add_account(paths, "main", "epic", {})
    with pytest.raises(LudexError) as caught:
        get_account(paths, "main")
    assert caught.value.code == "account_ambiguous"
    assert get_account(paths, "epic:main").source == "epic"
    remove_account(paths, "steam:main")
    assert list_accounts(paths) == [("main", "epic")]


@pytest.mark.parametrize("name", ["", "Main", "1abc", "a b", "a/b", "../x", "a" * 33, "-a"])
def test_invalid_names_rejected(home: Path, name: str) -> None:
    with pytest.raises(LudexError) as caught:
        add_account(state_paths(), name, "steam", {})
    assert caught.value.code == "invalid_account_name"
    assert not state_paths().accounts.exists()


def test_name_length_boundary(home: Path) -> None:
    add_account(state_paths(), "a" * 32, "steam", {})


def test_list_accounts_never_exposes_config(home: Path) -> None:
    paths = state_paths()
    add_account(paths, "zed", "steam", {"api_key": "SECRET"})
    add_account(paths, "alpha", "epic", {"token": "SECRET2"})
    listing = list_accounts(paths)
    assert listing == [("alpha", "epic"), ("zed", "steam")]
    assert "SECRET" not in repr(listing)
    assert "SECRET" not in repr(get_account(paths, "zed"))


def test_remove_account(home: Path) -> None:
    paths = state_paths()
    add_account(paths, "main", "steam", {})
    remove_account(paths, "main")
    assert list_accounts(paths) == []
    with pytest.raises(LudexError) as caught:
        get_account(paths, "main")
    assert caught.value.code == "account_not_found"
    with pytest.raises(LudexError) as caught:
        remove_account(paths, "main")
    assert caught.value.code == "account_not_found"


def test_accounts_file_with_open_mode_is_refused(home: Path) -> None:
    paths = state_paths()
    add_account(paths, "main", "steam", {})
    paths.accounts.chmod(0o644)
    with pytest.raises(PermissionError):
        list_accounts(paths)
