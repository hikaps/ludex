from __future__ import annotations

import json

import pytest

from ludex.plugins import SourceError
from ludex.sources.heroic import PLUGIN, fetch, installed


def _library(tmp_path, games):
    folder = tmp_path / "sideload_apps"
    folder.mkdir()
    (folder / "library.json").write_text(json.dumps({"games": games}))
    return {"heroic_dir": str(tmp_path)}


def test_fetch_lists_sideloaded_games_and_installed_state(tmp_path):
    config = _library(tmp_path, [
        {"app_name": "a1", "title": "Baldurs Gate 3", "runner": "sideload", "is_installed": True},
        {"app_name": "b2", "title": "God of War", "runner": "sideload", "is_installed": False},
        {"app_name": "c3", "title": "Not sideloaded", "runner": "legendary"},
        {"app_name": "", "title": "No id", "runner": "sideload"},
    ])
    result = fetch(config)
    assert result.complete and [(g.store, g.store_id, g.title) for g in result.games] == [("heroic", "a1", "Baldurs Gate 3"), ("heroic", "b2", "God of War")]
    assert installed(config) == ["a1"]
    assert PLUGIN.launch_url("a b") == "heroic://launch?appName=a%20b&runner=sideload"


@pytest.mark.parametrize("content", [None, "not json", '{"games": 5}', "[]"])
def test_missing_or_malformed_library_raises_instead_of_returning_nothing(tmp_path, content):
    if content is not None:
        (tmp_path / "sideload_apps").mkdir()
        (tmp_path / "sideload_apps" / "library.json").write_text(content)
    with pytest.raises(SourceError) as info:
        fetch({"heroic_dir": str(tmp_path)})
    assert info.value.code in ("heroic_not_found", "heroic_unreadable")
