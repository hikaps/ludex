from __future__ import annotations

import pytest

from ludex.plugins import SourceError
from ludex.sources.local import PLUGIN


def test_each_visible_subfolder_is_a_complete_game(tmp_path):
    for name in ("Hades", "Celeste", ".cache"):
        (tmp_path / name).mkdir()
    (tmp_path / "notes.txt").write_text("x")
    result = PLUGIN.fetch({"path": str(tmp_path)})
    assert [(g.store, g.store_id, g.title) for g in result.games] == [("local", "Celeste", "Celeste"), ("local", "Hades", "Hades")]
    assert (result.complete, result.mode) == (True, "directory")


@pytest.mark.parametrize("make", [False, True])
def test_missing_or_empty_directory_raises_instead_of_removing_everything(tmp_path, make):
    target = tmp_path / "games"
    if make:
        target.mkdir()
    with pytest.raises(SourceError) as info:
        PLUGIN.fetch({"path": str(target)})
    assert info.value.code == ("directory_empty" if make else "directory_unreadable")


def test_glob_path_searches_every_matching_folder_and_qualifies_ids(tmp_path):
    for parent, game in [("A", "Hades"), ("B", "Hades"), ("B", "Celeste")]:
        (tmp_path / parent / game).mkdir(parents=True)
    (tmp_path / "notes.txt").write_text("x")
    result = PLUGIN.fetch({"path": str(tmp_path / "*")})
    assert [(g.store_id, g.title) for g in result.games] == [("A/Hades", "Hades"), ("B/Celeste", "Celeste"), ("B/Hades", "Hades")]


def test_glob_matching_nothing_raises(tmp_path):
    with pytest.raises(SourceError) as info:
        PLUGIN.fetch({"path": str(tmp_path / "nope*")})
    assert info.value.code == "directory_unreadable"


def _game(root, name, files):
    folder = root / name
    folder.mkdir(parents=True)
    for file, mode in files.items():
        (folder / file).write_text("#!/bin/sh\n")
        (folder / file).chmod(mode)
    return folder


def test_launch_command_picks_start_sh_or_the_only_native_launcher(tmp_path):
    from ludex.sources.local import launch_command

    _game(tmp_path, "one", {"run.sh": 0o755, "readme.txt": 0o755, "data.sh": 0o644})
    _game(tmp_path, "two", {"start.sh": 0o755, "other.sh": 0o755})
    _game(tmp_path, "many", {"a.sh": 0o755, "b.AppImage": 0o755})
    _game(tmp_path, "none", {"game.exe": 0o755})
    config = {"path": str(tmp_path)}
    assert launch_command(config, "one") == [str((tmp_path / "one" / "run.sh").resolve())]
    assert launch_command(config, "two") == [str((tmp_path / "two" / "start.sh").resolve())]
    for ambiguous in ("many", "none", "absent"):
        with pytest.raises(SourceError) as info:
            launch_command(config, ambiguous)
        assert info.value.code == "not_launchable"


def test_launch_command_resolves_glob_store_ids(tmp_path):
    from ludex.sources.local import launch_command

    _game(tmp_path / "d1", "g", {"start.sh": 0o755})
    _game(tmp_path / "d2", "g", {"start.sh": 0o755})
    config = {"path": str(tmp_path / "d*")}
    assert launch_command(config, "d2/g") == [str((tmp_path / "d2" / "g" / "start.sh").resolve())]


def test_every_game_folder_counts_as_installed_and_qualified_ids_match(tmp_path):
    for name in ("a/g1", "b/g2", "b/.hidden"):
        (tmp_path / name).mkdir(parents=True)
    config = {"path": str(tmp_path / "*")}
    assert PLUGIN.installed(config) == {g.store_id for g in PLUGIN.fetch(config).games} == {"a/g1", "b/g2"}
    with pytest.raises(SourceError):
        PLUGIN.installed({"path": str(tmp_path / "missing")})


def test_excluded_folders_are_skipped_by_name_pattern_or_qualified_id(tmp_path):
    for name in ("a/Hades", "a/_unsorted", "a/Backup old", "b/Hades", "b/Celeste"):
        (tmp_path / name).mkdir(parents=True)
    ids = lambda **extra: sorted(g.store_id for g in PLUGIN.fetch({"path": str(tmp_path / "*"), **extra}).games)
    assert ids() == ["a/Backup old", "a/Hades", "a/_unsorted", "b/Celeste", "b/Hades"]
    assert ids(exclude="_unsorted, BACKUP*") == ["a/Hades", "b/Celeste", "b/Hades"]  # case-insensitive, comma-separated
    assert ids(exclude="b/Hades\n_*") == ["a/Backup old", "a/Hades", "b/Celeste"]  # a qualified id and a newline
    assert PLUGIN.installed({"path": str(tmp_path / "*"), "exclude": "Hades"}) == {"a/Backup old", "a/_unsorted", "b/Celeste"}
    with pytest.raises(SourceError):  # excluding everything is an empty directory, not a wipe
        PLUGIN.fetch({"path": str(tmp_path / "a"), "exclude": "*"})
