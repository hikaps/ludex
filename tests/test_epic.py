from __future__ import annotations

import json

import pytest

from ludex.plugins import SourceError
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
