from __future__ import annotations

import pytest

import ludex.library as library
from ludex.errors import LudexError
from ludex.library import ImportSummary, get_game, import_account, list_games, run_import
from ludex.plugins import FetchResult, OwnedGame, SourceError, SourcePlugin
from ludex.storage import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "db.sqlite3")
    yield connection
    connection.close()


def g(store_id, title, store="steam", **extra):
    return OwnedGame(store, store_id, title, extra)


def counts(conn):
    return (
        conn.execute("SELECT COUNT(*) FROM games").fetchone()[0],
        conn.execute("SELECT COUNT(*) FROM ownership").fetchone()[0],
    )


def snapshot(conn):
    return [tuple(r) for r in conn.execute("SELECT * FROM ownership ORDER BY id")]


def plugin(fetch):
    return SourcePlugin("fake", "fake source", (), lambda config: FetchResult(fetch(config), True, "test"))


def test_first_import_adds_games(conn):
    summary = import_account(conn, "main", [g("1", "Alpha", genre="rpg"), g("2", "Beta")])
    assert summary == ImportSummary(added=2, restored=0, removed=0, total=2)
    assert summary.as_dict() == {"added": 2, "restored": 0, "removed": 0, "total": 2, "complete": True, "mode": ""}
    assert counts(conn) == (2, 2)
    raw = conn.execute("SELECT raw_json FROM ownership WHERE store_id = '1'").fetchone()[0]
    assert raw == '{"extra": {"genre": "rpg"}}'


def test_reimport_is_idempotent(conn):
    games = [g("1", "Alpha"), g("2", "Beta")]
    import_account(conn, "main", games)
    before = counts(conn)
    ids = [r["id"] for r in conn.execute("SELECT id FROM games ORDER BY id")]
    summary = import_account(conn, "main", games)
    assert (summary.added, summary.restored, summary.removed, summary.total) == (0, 0, 0, 2)
    assert counts(conn) == before
    assert [r["id"] for r in conn.execute("SELECT id FROM games ORDER BY id")] == ids


def test_reimport_refreshes_title_but_not_game(conn):
    import_account(conn, "main", [g("1", "Alpha")])
    import_account(conn, "main", [g("1", "Alpha Remastered", v=2)])
    detail = get_game(conn, 1)
    assert detail["title"] == "Alpha"
    assert detail["ownership"][0]["title"] == "Alpha Remastered"
    assert counts(conn) == (1, 1)


def test_missing_game_is_marked_removed_not_deleted(conn):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    last_seen = conn.execute("SELECT last_seen FROM ownership WHERE store_id = '2'").fetchone()[0]
    summary = import_account(conn, "main", [g("1", "Alpha")])
    assert (summary.added, summary.restored, summary.removed, summary.total) == (0, 0, 1, 1)
    row = conn.execute("SELECT removed, last_seen FROM ownership WHERE store_id = '2'").fetchone()
    assert row["removed"] == 1 and row["last_seen"] == last_seen
    assert counts(conn) == (2, 2)
    # already-removed records are not counted again
    assert import_account(conn, "main", [g("1", "Alpha")]).removed == 0


def test_removed_game_is_restored_with_same_game_id(conn):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    game_id = conn.execute("SELECT game_id FROM ownership WHERE store_id = '2'").fetchone()[0]
    import_account(conn, "main", [g("1", "Alpha")])
    summary = import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    assert (summary.added, summary.restored, summary.removed) == (0, 1, 0)
    row = conn.execute("SELECT game_id, removed FROM ownership WHERE store_id = '2'").fetchone()
    assert (row["game_id"], row["removed"]) == (game_id, 0)
    assert counts(conn) == (2, 2)


def test_empty_complete_fetch_removes_everything(conn):
    import_account(conn, "main", [g("1", "Alpha")])
    assert import_account(conn, "main", []).removed == 1
    assert list_games(conn) == []


def test_duplicate_keys_in_one_fetch_collapse_last_wins(conn):
    summary = import_account(conn, "main", [g("1", "Old"), g("1", "New"), g("2", "Other")])
    assert (summary.added, summary.total) == (2, 2)
    assert counts(conn) == (2, 2)
    assert conn.execute("SELECT title FROM ownership WHERE store_id = '1'").fetchone()[0] == "New"


def test_removal_is_isolated_per_account(conn):
    import_account(conn, "a", [g("1", "Alpha")])
    import_account(conn, "b", [g("1", "Alpha")])
    summary = import_account(conn, "a", [])
    assert summary.removed == 1
    removed = {r["account"]: r["removed"] for r in conn.execute("SELECT account, removed FROM ownership")}
    assert removed == {"a": 1, "b": 0}
    # same key in another account is a separate ownership of the same game
    assert counts(conn) == (1, 2)


def test_failing_fetch_leaves_state_untouched(conn):
    import_account(conn, "main", [g("1", "Alpha")])
    before = snapshot(conn)

    def fetch(config):
        raise SourceError("private_profile", "profile is private")

    with pytest.raises(SourceError):
        run_import(conn, "main", plugin(fetch), {})
    assert snapshot(conn) == before


def test_partial_failure_midway_through_iterable_removes_nothing(conn):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    before = snapshot(conn)

    def fetch(config):
        yield g("1", "Alpha")
        raise SourceError("truncated", "page failed")

    with pytest.raises(SourceError):
        run_import(conn, "main", plugin(fetch), {})
    assert snapshot(conn) == before


def test_database_error_mid_import_rolls_back(conn, monkeypatch):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    before = snapshot(conn)
    games_before = counts(conn)
    real = library.normalize_title
    calls = []

    def flaky(title):
        calls.append(title)
        if len(calls) == 2:
            raise RuntimeError("disk on fire")
        return real(title)

    monkeypatch.setattr(library, "normalize_title", flaky)
    with pytest.raises(RuntimeError):
        # Gamma is inserted before Delta raises; that insert must not survive
        import_account(conn, "main", [g("1", "Alpha"), g("3", "Gamma"), g("4", "Delta")])
    assert snapshot(conn) == before
    assert counts(conn) == games_before
    assert not conn.in_transaction
    # connection remains usable
    monkeypatch.setattr(library, "normalize_title", real)
    assert import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")]).added == 0


def test_constraint_violation_rolls_back(conn):
    import_account(conn, "main", [g("1", "Alpha")])
    before = snapshot(conn)
    bad = OwnedGame("steam", "9", None)  # type: ignore[arg-type]
    with pytest.raises(Exception):
        import_account(conn, "main", [g("2", "Beta"), bad])
    assert snapshot(conn) == before
    assert counts(conn) == (1, 1)


def test_run_import_wraps_generic_exception_without_text(conn):
    def fetch(config):
        raise ValueError("secret-token-123")

    with pytest.raises(LudexError) as info:
        run_import(conn, "main", plugin(fetch), {})
    assert info.value.code == "source_failed"
    assert "secret-token-123" not in info.value.message
    assert info.value.message == "source fake failed (ValueError)"


def test_run_import_wraps_failure_during_iteration(conn):
    def fetch(config):
        yield g("1", "Alpha")
        raise OSError("secret")

    with pytest.raises(LudexError) as info:
        run_import(conn, "main", plugin(fetch), {})
    assert info.value.code == "source_failed" and "secret" not in info.value.message
    assert counts(conn) == (0, 0)


def test_run_import_passes_source_error_through(conn):
    error = SourceError("rate_limited", "slow down")

    def fetch(config):
        raise error

    with pytest.raises(SourceError) as info:
        run_import(conn, "main", plugin(fetch), {})
    assert info.value is error


@pytest.mark.parametrize(
    "bad",
    ["just a string", {"store": "steam"}, OwnedGame("", "1", "T"), OwnedGame("s", "", "T"), OwnedGame("s", "1", "")],
)
def test_run_import_rejects_invalid_items(conn, bad):
    with pytest.raises(LudexError) as info:
        run_import(conn, "main", plugin(lambda config: [g("1", "Alpha"), bad]), {})
    assert info.value.code == "source_failed"
    assert counts(conn) == (0, 0)


def test_run_import_passes_config_and_imports(conn):
    seen = {}

    def fetch(config):
        seen.update(config)
        return iter([g("1", "Alpha")])

    summary = run_import(conn, "main", plugin(fetch), {"key": "v"})
    assert seen == {"key": "v"}
    assert summary.added == 1


def test_list_games_default_hides_removed(conn):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    import_account(conn, "main", [g("1", "Alpha")])
    assert [x["title"] for x in list_games(conn)] == ["Alpha"]
    everything = list_games(conn, include_removed=True)
    assert [(x["title"], x["removed"]) for x in everything] == [("Alpha", False), ("Beta", True)]


def test_list_games_dict_shape(conn):
    import_account(conn, "zed", [g("1", "Alpha")])
    item = list_games(conn)[0]
    assert item == {"id": 1, "title": "Alpha", "stores": ["steam"], "accounts": ["zed"], "removed": False}


def test_list_games_store_and_account_filters(conn):
    import_account(conn, "a", [g("1", "Alpha"), g("2", "Beta", store="epic")])
    import_account(conn, "b", [g("3", "Gamma")])
    assert [x["title"] for x in list_games(conn, store="epic")] == ["Beta"]
    assert [x["title"] for x in list_games(conn, account="b")] == ["Gamma"]
    assert [x["title"] for x in list_games(conn, store="steam", account="a")] == ["Alpha"]
    assert list_games(conn, store="gog") == []
    # removed ownership does not match the filter unless include_removed
    import_account(conn, "a", [])
    assert list_games(conn, account="a") == []
    assert [x["title"] for x in list_games(conn, account="a", include_removed=True)] == ["Alpha", "Beta"]


def test_list_games_search_is_case_and_accent_insensitive(conn):
    import_account(conn, "main", [g("1", "Pokémon Red"), g("2", "Half-Life"), g("3", "Other")])
    assert [x["title"] for x in list_games(conn, query="POKEMON")] == ["Pokémon Red"]
    assert [x["title"] for x in list_games(conn, query="pokémon r")] == ["Pokémon Red"]
    assert [x["title"] for x in list_games(conn, query="half life")] == ["Half-Life"]
    assert list_games(conn, query="zzz") == []


def test_list_games_wildcards_are_not_patterns(conn):
    import_account(conn, "main", [g("1", "100% Orange Juice"), g("2", "Alpha"), g("3", "A_B")])
    assert list_games(conn, query="al%a") == []
    assert list_games(conn, query="a_pha") == []
    assert list_games(conn, query="a\\pha") == []
    assert [x["title"] for x in list_games(conn, query="100% orange")] == ["100% Orange Juice"]
    assert [x["title"] for x in list_games(conn, query="alpha")] == ["Alpha"]


def test_list_games_ordering_and_pagination(conn):
    import_account(conn, "main", [g(str(i), t) for i, t in enumerate(["delta", "Alpha", "charlie", "Bravo", "echo"])])
    titles = lambda **kw: [x["title"] for x in list_games(conn, **kw)]
    assert titles() == ["Alpha", "Bravo", "charlie", "delta", "echo"]
    assert titles(limit=2) == ["Alpha", "Bravo"]
    assert titles(limit=2, offset=2) == ["charlie", "delta"]
    assert titles(limit=2, offset=4) == ["echo"]
    assert titles(offset=10) == []


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 501}, {"limit": -1}, {"offset": -1}])
def test_list_games_invalid_pagination(conn, kwargs):
    with pytest.raises(LudexError) as info:
        list_games(conn, **kwargs)
    assert info.value.code == "invalid_pagination"


def test_list_games_limit_bounds_accepted(conn):
    assert list_games(conn, limit=1) == []
    assert list_games(conn, limit=500) == []


def test_removed_flag_requires_every_ownership_removed(conn):
    import_account(conn, "a", [g("1", "Alpha")])
    import_account(conn, "b", [g("1", "Alpha")])
    import_account(conn, "a", [])
    # one game owned through both accounts; it is removed only when every ownership is
    assert [x["removed"] for x in list_games(conn, include_removed=True)] == [False]
    import_account(conn, "b", [])
    assert [x["removed"] for x in list_games(conn, include_removed=True)] == [True]


def test_get_game_returns_ownership_records(conn):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    import_account(conn, "main", [g("1", "Alpha")])
    detail = get_game(conn, 2)
    assert set(detail) == {"id", "title", "created_at", "ownership"}
    assert detail["title"] == "Beta" and detail["created_at"].endswith("Z")
    (record,) = detail["ownership"]
    assert set(record) == {"id", "store", "store_id", "account", "title", "first_seen", "last_seen", "removed"}
    assert (record["store"], record["store_id"], record["account"]) == ("steam", "2", "main")
    assert record["removed"] is True
    assert get_game(conn, 1)["ownership"][0]["removed"] is False


def test_get_game_not_found(conn):
    with pytest.raises(LudexError) as info:
        get_game(conn, 42)
    assert info.value.code == "game_not_found"


def test_incomplete_fetch_adds_but_never_removes(conn):
    import_account(conn, "main", [g("1", "Alpha"), g("2", "Beta")])
    summary = import_account(conn, "main", [g("1", "Alpha"), g("3", "Gamma")], complete=False)
    assert (summary.added, summary.removed, summary.complete) == (1, 0, False)
    assert conn.execute("SELECT COUNT(*) FROM ownership WHERE removed = 1").fetchone()[0] == 0


def test_run_import_forwards_completeness_and_mode(conn):
    partial = SourcePlugin("fake", "fake", (), lambda config: FetchResult([g("1", "Alpha")], False, "local"))
    summary = run_import(conn, "main", partial, {})
    assert (summary.complete, summary.mode) == (False, "local")


def test_run_import_rejects_bare_list(conn):
    with pytest.raises(LudexError) as info:
        run_import(conn, "main", SourcePlugin("fake", "fake", (), lambda config: [g("1", "Alpha")]), {})
    assert info.value.code == "source_failed"


def _games(conn):
    return [tuple(r) for r in conn.execute("SELECT o.store, o.account, o.game_id FROM ownership o ORDER BY o.id")]


def test_same_title_in_another_store_joins_one_game(conn):
    import_account(conn, "s", [g("1", "Hades")])
    import_account(conn, "e", [g("a", "HADES!", store="epic")])
    assert _games(conn) == [("steam", "s", 1), ("epic", "e", 1)]
    assert conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 0


def test_same_store_id_under_another_account_joins_even_if_title_differs(conn):
    import_account(conn, "local", [g("10", "Counter-Strike")])
    import_account(conn, "api", [g("10", "Counter Strike: Global")])
    assert [r[2] for r in _games(conn)] == [1, 1]


def test_second_game_with_same_title_in_same_store_is_queued_not_merged(conn):
    import_account(conn, "s", [g("1", "Doom"), g("2", "DOOM")])
    assert [r[2] for r in _games(conn)] == [1, 2]
    items = library.list_review(conn)
    assert [(i["game_id"], [c["id"] for c in i["candidates"]]) for i in items] == [(2, [1])]


def test_ambiguous_title_across_stores_is_queued(conn):
    import_account(conn, "s", [g("1", "Doom"), g("2", "Doom ")])
    import_account(conn, "e", [g("a", "Doom", store="epic")])
    assert [r[2] for r in _games(conn)] == [1, 2, 3]
    assert [c["id"] for c in library.list_review(conn)[-1]["candidates"]] == [1, 2]


def test_reimport_keeps_manual_merge(conn):
    import_account(conn, "s", [g("1", "Doom"), g("2", "DOOM")])
    assert library.merge_games(conn, 1, 2) == 1
    assert library.list_review(conn) == []
    import_account(conn, "s", [g("1", "Doom"), g("2", "DOOM")])
    assert [r[2] for r in _games(conn)] == [1, 1]
    assert [x["id"] for x in list_games(conn)] == [1]


def test_merge_validates_and_dismiss(conn):
    import_account(conn, "s", [g("1", "Doom"), g("2", "DOOM")])
    for args, code in [((1, 1), "invalid_merge"), ((1, 9), "game_not_found")]:
        with pytest.raises(LudexError) as info:
            library.merge_games(conn, *args)
        assert info.value.code == code
    library.dismiss_review(conn, 1)
    assert library.list_review(conn) == []
    with pytest.raises(LudexError):
        library.dismiss_review(conn, 1)


def _raw_games(conn, rows):
    # simulate libraries imported before matching: one game per ownership
    for store, store_id, title in rows:
        gid = conn.execute("INSERT INTO games(title, normalized_title, created_at) VALUES (?, ?, 'x')", (title, library.normalize_title(title))).lastrowid
        conn.execute(
            "INSERT INTO ownership(game_id, store, store_id, account, title, raw_json, first_seen, last_seen) "
            "VALUES (?, ?, ?, 'a', ?, '{}', 'x', 'x')",
            (gid, store, store_id, title),
        )


def test_dedupe_merges_distinct_store_groups_and_queues_the_rest(conn):
    _raw_games(conn, [("steam", "1", "Hades"), ("epic", "a", "Hades!"), ("steam", "2", "Doom"), ("steam", "3", "DOOM"), ("epic", "b", "Solo")])
    assert library.dedupe(conn) == (1, 1)
    assert len(list_games(conn)) == 4
    assert [(i["game_id"], [c["id"] for c in i["candidates"]]) for i in library.list_review(conn)] == [(4, [3])]
    assert library.dedupe(conn) == (0, 0)
