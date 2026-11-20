from __future__ import annotations

from ludex.details import fetch_missing_details, games_without_details
from ludex.library import import_account, list_games, list_genres
from ludex.metadata import cached_metadata
from ludex.paths import StatePaths
from ludex.plugins import Metadata, OwnedGame, Provider
from ludex.storage import connect

DETAILS = {
    "1": Metadata("a", ("Action", "Roguelike")),
    "2": Metadata("b", ("action",)),
    "3": Metadata("c", ("Puzzle",)),
}


def _paths(tmp_path) -> StatePaths:
    root = tmp_path / "home"
    root.mkdir(mode=0o700)
    return StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")


def _library(tmp_path):
    paths = _paths(tmp_path)
    conn = connect(paths.database)
    import_account(conn, "m", [OwnedGame("shop", "1", "Hades"), OwnedGame("shop", "2", "Doom"), OwnedGame("shop", "3", "Portal"), OwnedGame("shop", "4", "Quiet")], store="shop")
    return paths, conn


def _shop(calls: list[str], broken: str = "") -> Provider:
    def metadata(store_id: str):
        calls.append(store_id)
        if store_id == broken:
            raise RuntimeError("boom")
        return DETAILS.get(store_id)

    return Provider("shop", "s", (), metadata=metadata)


def test_fetching_missing_details_fills_the_cache_once_and_survives_a_failing_game(tmp_path):
    paths, conn = _library(tmp_path)
    calls: list[str] = []
    seen: list[tuple[int, int]] = []
    summary = fetch_missing_details(paths, conn, {"shop": _shop(calls, broken="3")}, report=lambda done, total: seen.append((done, total)))
    assert (summary.fetched, summary.unavailable, summary.failed, summary.stopped) == (2, 1, 1, False)
    assert seen[-1] == (4, 4) and cached_metadata(conn, "shop", "1").genres == ("Action", "Roguelike")
    calls.clear()
    fetch_missing_details(paths, conn, {"shop": _shop(calls)})
    assert calls == ["3", "4"]  # what is cached is not asked again
    assert games_without_details(conn) == [4]


def test_fetching_can_be_stopped_and_continued(tmp_path):
    paths, conn = _library(tmp_path)
    calls: list[str] = []
    summary = fetch_missing_details(paths, conn, {"shop": _shop(calls)}, should_stop=lambda: len(calls) >= 2)
    assert summary.stopped and len(calls) == 2
    assert not fetch_missing_details(paths, conn, {"shop": _shop([])}).stopped


def test_games_filter_and_genre_counts_follow_cached_details_ignoring_case_and_removed_games(tmp_path):
    paths, conn = _library(tmp_path)
    fetch_missing_details(paths, conn, {"shop": _shop([])})
    assert [g["title"] for g in list_games(conn, genre="ACTION")] == ["Doom", "Hades"]
    assert [g["title"] for g in list_games(conn, genre="puzzle", query="port")] == ["Portal"]
    assert list_games(conn, genre="Strategy") == []
    assert list_genres(conn) == [("Action", 2), ("Puzzle", 1), ("Roguelike", 1)]
    import_account(conn, "m", [OwnedGame("shop", "3", "Portal"), OwnedGame("shop", "4", "Quiet")], store="shop")  # Hades and Doom are removed
    assert dict(list_genres(conn)) == {"Puzzle": 1}
    assert list_games(conn, genre="action") == []
