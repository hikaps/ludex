from __future__ import annotations

import json

import pytest

from ludex.plugins import SourceError
from pathlib import Path

from ludex.sources import epic
from ludex.sources.epic import PLUGIN


def _app(root, app_name, title, main_game=()):
    (root / "metadata").mkdir(exist_ok=True)
    (root / "metadata" / f"{app_name}.json").write_text(
        json.dumps({"app_name": app_name, "app_title": title, "metadata": {"mainGameItemList": list(main_game), "namespace": "ns"}})
    )


def test_lists_base_games_only_and_is_incomplete(tmp_path):
    _app(tmp_path, "a1", "Alpha")
    _app(tmp_path, "d1", "Alpha DLC", main_game=[{"id": "x"}])
    (tmp_path / "metadata" / "broken.json").write_text("{not json")
    (tmp_path / "metadata" / "odd.json").write_text("[]")
    (tmp_path / "user.json").write_text('{"access_token": "SECRET"}')
    result = PLUGIN.fetch({"legendary_dir": str(tmp_path)})
    assert [(g.store, g.store_id, g.title) for g in result.games] == [("epic", "a1", "Alpha")]
    assert (result.complete, result.mode) == (False, "local")


def test_missing_folder_raises(tmp_path):
    with pytest.raises(SourceError) as info:
        PLUGIN.fetch({"legendary_dir": str(tmp_path / "nope")})
    assert info.value.code == "epic_not_found"


def test_install_command_uses_the_heroic_flatpak_on_heroics_config_or_a_native_legendary(tmp_path, monkeypatch):
    flatpak = tmp_path / "home" / ".var" / "app" / "com.heroicgameslauncher.hgl" / "config" / "heroic" / "legendaryConfig" / "legendary"
    (flatpak / "metadata").mkdir(parents=True)
    monkeypatch.setattr(epic.Path, "home", classmethod(lambda cls: tmp_path / "home"))
    monkeypatch.setattr(epic.shutil, "which", lambda name: f"/usr/bin/{name}")
    argv = epic.install_command({"legendary_dir": str(flatpak)}, "Quail")
    assert argv[:2] == ["/usr/bin/flatpak", "run"] and f"--env=LEGENDARY_CONFIG_PATH={flatpak}" in argv
    assert argv[argv.index("com.heroicgameslauncher.hgl") + 1:] == ["-y", "install", "Quail", "--base-path", str(Path("~/Games/Heroic").expanduser()), "--skip-sdl"]
    native = tmp_path / "native"
    (native / "metadata").mkdir(parents=True)
    argv = epic.install_command({"legendary_dir": str(native), "install_dir": str(tmp_path / "g")}, "Quail")
    assert argv[:3] == ["/usr/bin/env", f"LEGENDARY_CONFIG_PATH={native}", "/usr/bin/legendary"] and str(tmp_path / "g") in argv
    for bad_id in ("--force", "a b", "", "../x"):
        with pytest.raises(SourceError, match="cannot be installed"):
            epic.install_command({"legendary_dir": str(native)}, bad_id)
    with pytest.raises(SourceError, match="absolute"):
        epic.install_command({"legendary_dir": str(native), "install_dir": "games"}, "Quail")
    monkeypatch.setattr(epic.shutil, "which", lambda name: None)
    with pytest.raises(SourceError, match="not installed"):
        epic.install_command({"legendary_dir": str(native)}, "Quail")
