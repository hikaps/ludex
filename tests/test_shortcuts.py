from __future__ import annotations

import zlib

import pytest
import vdf

from ludex.plugins import SourceError
from ludex.sources.shortcuts import PLUGIN, fetch, installed


def _write(steam, user, entries):
    folder = steam / "userdata" / user / "config"
    folder.mkdir(parents=True)
    (folder / "shortcuts.vdf").write_bytes(vdf.binary_dumps({"shortcuts": entries}))


@pytest.fixture
def steam(tmp_path):
    (tmp_path / "steamapps").mkdir()
    return tmp_path


def test_fetch_reads_every_users_shortcuts_with_steams_game_id(steam, tmp_path):
    exe = tmp_path / "game.exe"
    exe.write_text("")
    _write(steam, "1", {"0": {"appid": 0x8CCAE2B8 - 2**32, "AppName": "Kill It", "exe": f'"{exe}"'}, "1": {"appid": 5, "appname": "", "exe": "x"}})
    _write(steam, "2", {"0": {"AppName": "Old Style", "exe": "/nope/old.exe"}})  # no appid: derived from exe + name
    config = {"steam_dir": str(steam)}
    result = fetch(config)
    old_id = str((((zlib.crc32(b"/nope/old.exeOld Style") | 0x80000000) << 32) | 0x02000000))
    kill_id = str((0x8CCAE2B8 << 32) | 0x02000000)
    assert result.complete and sorted((g.store_id, g.title) for g in result.games) == sorted([(kill_id, "Kill It"), (old_id, "Old Style")])
    assert installed(config) == [kill_id]  # only the exe that exists
    assert PLUGIN.launch_url(old_id) == f"steam://rungameid/{old_id}"


@pytest.mark.parametrize("content", [None, b"\x08garbage"])
def test_missing_or_broken_file_raises_instead_of_returning_nothing(steam, content):
    if content is not None:
        folder = steam / "userdata" / "1" / "config"
        folder.mkdir(parents=True)
        (folder / "shortcuts.vdf").write_bytes(content)
    with pytest.raises(SourceError) as info:
        fetch({"steam_dir": str(steam)})
    assert info.value.code in ("shortcuts_not_found", "shortcuts_unreadable")
