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
