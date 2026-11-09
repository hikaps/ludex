from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from ludex import playtime as playtime_mod
from ludex.accounts import add_account
from ludex.library import import_account, list_games
from ludex.paths import state_paths
from ludex.plugins import OwnedGame, PlayRecord, Provider, SourceError
from ludex.sources import epic, heroic, steam
from ludex.storage import connect

STEAM_ID = "76561198051524999"  # account id 91259271
def _vdf(apps: dict, other: dict) -> str:
    def block(name, body, depth):
        pad = "\t" * depth
        inner = "".join(
            block(k, v, depth + 1) if isinstance(v, dict) else f'{pad}\t"{k}"\t\t"{v}"\n' for k, v in body.items()
        )
        return f'{pad}"{name}"\n{pad}{{\n{inner}{pad}}}\n'

    return block("UserLocalConfigStore", {"Software": {"valve": {"Steam": {"apps": apps}}}, "apps": other}, 0)


VDF = _vdf(
    {"480": {"LastPlayed": "1791780844", "Playtime": "920", "PlaytimeDisconnected": "1"}, "550": {"LastPlayed": "0", "Playtime": "0"},
     "570": {"Playtime": "twelve"}, "-9": {"Playtime": "5"}},
    {"480": {"Playtime": "999999"}},
)


def steam_folder(tmp_path, users=("91259271",)):
    root = tmp_path / "Steam"
    (root / "steamapps").mkdir(parents=True)
    for user in users:
        (root / "userdata" / user / "config").mkdir(parents=True)
        (root / "userdata" / user / "config" / "localconfig.vdf").write_text(VDF)
    return root


def test_steam_reads_playtime_for_the_account_user_and_ignores_unusable_entries(tmp_path):
    root = steam_folder(tmp_path)
    found = steam.playtime({"steam_dir": str(root), "steam_id": STEAM_ID})
    assert found == {"480": PlayRecord(920, "2026-10-12T04:54:04Z")}  # not the second "apps" block, not 0/0, not unparsable ids
    assert steam.playtime({"steam_dir": str(root)}) == found  # the only user folder
    two = steam_folder(tmp_path / "two", users=("91259271", "5"))
    with pytest.raises(SourceError) as info:
        steam.playtime({"steam_dir": str(two)})
    assert info.value.code == "steam_user_unknown"
    assert steam.playtime({"steam_dir": str(two), "steam_id": STEAM_ID}) == found
    with pytest.raises(SourceError) as info:  # a user without a local config
        steam.playtime({"steam_dir": str(root), "steam_id": "76561197960265729"})
    assert info.value.code == "steam_no_localconfig"


def test_heroic_playtime_reads_minutes_and_dates_and_survives_bad_entries(tmp_path):
    (tmp_path / "store").mkdir()
    (tmp_path / "store" / "timestamp.json").write_text(json.dumps({
        "a": {"firstPlayed": "2026-01-01T00:00:00.000Z", "lastPlayed": "2026-11-08T19:38:29.017Z", "totalPlayed": 2021},
        "b": {"totalPlayed": "many"}, "c": {"lastPlayed": "yesterday", "totalPlayed": 3}, "d": "x", "e": {"totalPlayed": -1},
    }))
    assert heroic.heroic_playtime(tmp_path) == {"a": PlayRecord(2021, "2026-11-08T19:38:29Z"), "c": PlayRecord(3, None)}
    assert heroic.heroic_playtime(tmp_path / "nowhere") == {}  # Heroic has recorded nothing yet
    (tmp_path / "store" / "timestamp.json").write_text("[1]")
    with pytest.raises(SourceError) as info:
        heroic.heroic_playtime(tmp_path)
    assert info.value.code == "heroic_unreadable"


def test_epic_reads_the_heroic_record_beside_its_legendary_folder_and_not_a_plain_legendary(tmp_path):
    legendary = tmp_path / "heroic" / "legendaryConfig" / "legendary"
    (legendary / "metadata").mkdir(parents=True)
    (tmp_path / "heroic" / "store").mkdir()
    (tmp_path / "heroic" / "store" / "timestamp.json").write_text(json.dumps({"Cowbird": {"totalPlayed": 7}}))
    assert epic.playtime({"legendary_dir": str(legendary)}) == {"Cowbird": PlayRecord(7, None)}
    plain = tmp_path / "legendary"
    (plain / "metadata").mkdir(parents=True)
    assert epic.playtime({"legendary_dir": str(plain)}) == {}


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setenv("LUDEX_HOME", str(tmp_path / "home"))
    paths = state_paths()
    conn = connect(paths.database)
    return paths, conn


def _session(conn, game_id, target, seconds, state="done"):
    start = datetime(2026, 11, 2, 10, tzinfo=timezone.utc).timestamp()
    stamp = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO jobs(kind, game_id, target, title, pid, pid_start, log, exit_file, started_at, ended_at, state) VALUES ('play', ?, ?, 't', 1, '', 'l', 'e', ?, ?, ?)",
        (game_id, target, stamp(start), stamp(start + seconds), state),
    )


def test_a_store_figure_replaces_our_own_timing_and_only_our_own_finished_sessions_count(world):
    paths, conn = world
    import_account(conn, "a", [OwnedGame("store", "1", "Recorded"), OwnedGame("store", "3", "Never")], store="store")
    import_account(conn, "b", [OwnedGame("disk", "x", "Timed"), OwnedGame("disk", "y", "Running")], store="disk")
    store = Provider("store", "s", (), lambda c: None, playtime=lambda c: {"1": PlayRecord(100, "2026-11-01T10:00:00Z")})
    disk = Provider("disk", "d", (), lambda c: None)
    add_account(paths, "main", "store", {})
    ids = {g["title"]: g["id"] for g in list_games(conn)}
    _session(conn, ids["Recorded"], "store:1", 3000)  # the store already counts this one
    _session(conn, ids["Timed"], "disk:x", 90)
    _session(conn, ids["Timed"], "disk:x", 120)
    _session(conn, ids["Timed"], "disk:x", 5000, "lost")  # no known end
    _session(conn, ids["Running"], "disk:y", 60, "stopped")
    stats, problems = playtime_mod.play_stats(paths, {"store": store, "disk": disk}, conn)
    assert problems == {}
    assert stats[ids["Recorded"]] == playtime_mod.Played(100, "2026-11-01T10:00:00Z")
    assert stats[ids["Timed"]] == playtime_mod.Played(3, "2026-11-02T10:02:00Z")  # 210 s, newest end
    assert stats[ids["Running"]].minutes == 1 and ids["Never"] not in stats


def test_a_failing_provider_is_reported_and_the_rest_still_count(world):
    paths, conn = world
    import_account(conn, "a", [OwnedGame("store", "1", "G")], store="store")
    boom = Provider("store", "s", (), lambda c: None, playtime=lambda c: (_ for _ in ()).throw(SourceError("nope", "no data")))
    add_account(paths, "main", "store", {})
    assert playtime_mod.play_stats(paths, {"store": boom}, conn) == ({}, {"store:main": "no data"})


def test_list_games_orders_by_a_number_with_unknowns_last_and_title_breaking_ties(world):
    _, conn = world
    import_account(conn, "a", [OwnedGame("s", str(i), t) for i, t in enumerate(["Alpha", "Bravo", "Charlie", "Delta"], 1)], store="s")
    ids = {g["title"]: g["id"] for g in list_games(conn)}
    order = {ids["Delta"]: 50, ids["Bravo"]: 50, ids["Charlie"]: 0}
    assert [g["title"] for g in list_games(conn, order=order)] == ["Bravo", "Delta", "Charlie", "Alpha"]
    assert [g["title"] for g in list_games(conn, order=order, limit=2, offset=1)] == ["Delta", "Charlie"]


def test_play_time_reads_the_way_people_expect():
    d = playtime_mod.describe_played
    assert [d(None), d(playtime_mod.Played(0, None)), d(playtime_mod.Played(45, None)), d(playtime_mod.Played(725, "2026-11-08T19:38:29Z"))] == [
        "never", "never", "45m", "12h 05m, last 2026-11-08"]
