from __future__ import annotations

import json

from ludex.accounts import add_account
from ludex.installed import installed_keys
from ludex.library import import_account, list_games
from ludex.paths import state_paths
from ludex.plugins import OwnedGame, Provider, SourceError
from ludex.sources import epic, steam
from ludex.storage import connect


def test_steam_installed_reads_manifests_across_libraries_and_needs_the_installed_flag(tmp_path):
    other = tmp_path / "lib2"
    (other / "steamapps").mkdir(parents=True)
    (tmp_path / "steamapps").mkdir()
    (tmp_path / "steamapps" / "libraryfolders.vdf").write_text(f'"libraryfolders"\n{{\n"0"\n{{\n"path" "{other}"\n}}\n}}\n')

    def manifest(folder, appid, flags):
        (folder / "steamapps" / f"appmanifest_{appid}.acf").write_text(
            f'"AppState"\n{{\n"appid" "{appid}"\n"name" "g{appid}"\n"StateFlags" "{flags}"\n}}\n'
        )

    manifest(tmp_path, 1, 4)
    manifest(other, 2, 6)  # installed, update pending
    manifest(other, 3, 1024)  # not fully installed
    assert steam.installed({"steam_dir": str(tmp_path)}) == {"1", "2"}


def test_epic_installed_lists_app_names_and_tolerates_none(tmp_path):
    (tmp_path / "metadata").mkdir()
    assert epic.installed({"legendary_dir": str(tmp_path)}) == set()
    (tmp_path / "installed.json").write_text(json.dumps({"abc": {"app_name": "abc"}}))
    assert epic.installed({"legendary_dir": str(tmp_path)}) == {"abc"}
    (tmp_path / "installed.json").write_text("{")
    try:
        epic.installed({"legendary_dir": str(tmp_path)})
    except SourceError as exc:
        assert exc.code == "epic_installed_unreadable"
    else:
        raise AssertionError


def test_installed_keys_skips_failures_and_incapable_providers(tmp_path, monkeypatch):
    monkeypatch.setenv("LUDEX_HOME", str(tmp_path / "h"))
    paths = state_paths()
    for name, source in (("a", "good"), ("b", "bad"), ("c", "plain")):
        add_account(paths, name, source, {})

    def bad(config):
        raise SourceError("boom", "cannot tell")

    providers = {
        "good": Provider("good", "g", (), installed=lambda config: ["1", 2]),
        "bad": Provider("bad", "b", (), installed=bad),
        "plain": Provider("plain", "p", (), launch_url=lambda i: i),
    }
    keys, problems = installed_keys(paths, providers)
    assert keys == {("good", "1"), ("good", "2")} and problems == {"bad:b": "cannot tell"}


def test_list_games_only_filters_by_store_pairs(tmp_path):
    conn = connect(tmp_path / "db.sqlite3")
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades"), OwnedGame("steam", "2", "Doom")], store="steam")
    assert [g["title"] for g in list_games(conn, only={("steam", "2")})] == ["Doom"]
    assert list_games(conn, only=set()) == []
    assert [g["title"] for g in list_games(conn, only={("epic", "1")})] == []
