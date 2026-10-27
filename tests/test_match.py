from __future__ import annotations

import httpx
import pytest

from ludex.errors import LudexError
from ludex.library import get_game, import_account
from ludex.loader import load_providers
from ludex.metadata import cached_match, choose_match, clean_title, clear_match, default_query, game_metadata, get_auto_match, match_candidates, set_auto_match
from ludex.plugins import ConfigField, Metadata, OwnedGame, Provider, SearchHit, SourceError
from ludex.provider_settings import set_value
from ludex.sources import rawg
from ludex.storage import connect

KEY = "k3y-secret"


@pytest.mark.parametrize("folder,clean", [
    ("Hades_v1.2_(GOG)", "Hades"), ("Celeste.v1.4.3.0", "Celeste"), ("Doom 3", "Doom 3"),
    ("Half-Life 2 [Linux]", "Half-Life 2"), ("The Witcher 3 - 1.31", "The Witcher 3"), ("(only tags)", "(only tags)"),
])
def test_clean_title_drops_tags_and_versions_only(folder, clean):
    assert clean_title(folder) == clean


def rawg_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_rawg_match_and_metadata_send_the_key_and_map_the_answer():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("/games"):
            return httpx.Response(200, json={"results": [{"id": 7, "slug": "hades-2018", "name": "Hades"}, {"id": "x", "slug": "a", "name": "Bad"}, {"id": 8, "slug": "../evil", "name": "Evil"}]})
        return httpx.Response(200, json={"description_raw": "Slash. " + "word " * 300, "genres": [{"name": "Action"}, {"x": 1}], "developers": [{"name": "Supergiant"}], "released": "2020-09-17"})

    with rawg_client(handler) as client:
        hits = rawg.match("Hades", settings={"api_key": KEY}, client=client)
        found = rawg.metadata("7", settings={"api_key": KEY}, client=client)
    assert hits == [SearchHit("rawg", "7", "Hades", "https://rawg.io/games/hades-2018")]
    assert all(r.url.params["key"] == KEY for r in seen)
    assert found.genres == ("Action",) and found.developers == ("Supergiant",) and found.released == "2020-09-17"
    assert found.description.startswith("Slash.") and len(found.description) <= rawg.MAX_DESCRIPTION + 1


def test_rawg_errors_are_stable_and_never_contain_the_key():
    def failing(request):
        raise httpx.ConnectError("boom " + str(request.url))

    for handler, code in ((failing, "rawg_unavailable"), (lambda r: httpx.Response(401), "rawg_auth_failed"), (lambda r: httpx.Response(429), "rawg_rate_limited"), (lambda r: httpx.Response(200, text="<html>"), "rawg_bad_response")):
        with rawg_client(handler) as client, pytest.raises(SourceError) as caught:
            rawg.match("Hades", settings={"api_key": KEY}, client=client)
        assert caught.value.code == code and KEY not in caught.value.message
    with pytest.raises(SourceError) as caught:
        rawg.match("Hades", settings={})
    assert caught.value.code == "rawg_no_key"
    with rawg_client(lambda r: httpx.Response(404)) as client:
        assert rawg.metadata("7", settings={"api_key": KEY}, client=client) is None
    assert rawg.metadata("7/../x", settings={"api_key": KEY}) is None  # never builds a URL from a non-id


def test_functions_that_declare_settings_receive_the_plugins_settings(tmp_path, monkeypatch):
    from importlib.metadata import EntryPoint

    monkeypatch.setenv("LUDEX_HOME", str(tmp_path))
    tmp_path.chmod(0o700)
    got = []
    plugin = Provider("keyed", "k", (), metadata=lambda store_id, settings: got.append(dict(settings)) or None, match=lambda title: [], settings=(ConfigField("api_key", "k", secret=True),))
    import sys, types

    module = types.ModuleType("keyed_mod")
    module.PLUGIN = plugin
    monkeypatch.setitem(sys.modules, "keyed_mod", module)
    from ludex.paths import state_paths

    set_value(state_paths(), plugin, "api_key", "abc")
    loaded, problems = load_providers([EntryPoint("keyed", "keyed_mod:PLUGIN", "ludex.providers")])
    assert not problems
    assert loaded["keyed"].metadata("1") is None and got == [{"api_key": "abc"}]
    assert loaded["keyed"].match("x") == []  # no settings parameter: called as before


def database(tmp_path, folder="Hades_v1.2_(GOG)"):
    conn = connect(tmp_path / "db.sqlite3")
    import_account(conn, "disk", [OwnedGame("local", "Hades_v1.2_(GOG)", folder)], store="local")
    return conn, get_game(conn, 1)["id"]


def db_provider(hits, found=Metadata("Slash.", ("Action",), ("Supergiant",), "2020"), calls=None):
    def match(title):
        if calls is not None:
            calls.append(title)
        if isinstance(hits, Exception):
            raise hits
        return hits

    return Provider("db", "d", (), metadata=lambda store_id: found, match=match)


def test_match_sets_title_and_details_once_and_is_cached(tmp_path):
    conn, game_id = database(tmp_path)
    calls = []
    sources = {"db": db_provider([SearchHit("db", "7", "Hades", "https://x/hades")], calls=calls)}
    with pytest.raises(LudexError, match="no installed plugin"):
        game_metadata(conn, sources, game_id)  # off by default
    found = game_metadata(conn, sources, game_id, match=True)
    assert found.genres == ("Action",) and calls == ["Hades"]
    assert get_game(conn, game_id)["title"] == "Hades"
    assert cached_match(conn, "local", "Hades_v1.2_(GOG)") == {"plugin": "db", "title": "Hades", "url": "https://x/hades", "manual": False}
    assert game_metadata(conn, sources, game_id, match=True) == found and calls == ["Hades"]


def test_only_an_exact_title_is_accepted_and_failing_plugins_are_skipped(tmp_path):
    conn, game_id = database(tmp_path)
    inexact = db_provider([SearchHit("db", "9", "Hades II", "https://x/2"), SearchHit("db", "8", "Hades Star", "https://x/3")])
    broken = db_provider(SourceError("rawg_no_key", "no key"))
    assert game_metadata(conn, {"a": broken, "b": inexact}, game_id, match=True) is None
    assert get_game(conn, game_id)["title"] == "Hades_v1.2_(GOG)"
    good = db_provider([SearchHit("db", "7", "HADES", "https://x/hades")])
    assert game_metadata(conn, {"a": broken, "b": inexact, "c": good}, game_id, match=True) is not None
    assert get_game(conn, game_id)["title"] == "HADES"


def test_a_game_a_store_can_describe_is_never_matched(tmp_path):
    conn = connect(tmp_path / "db.sqlite3")
    import_account(conn, "m", [OwnedGame("steam", "1", "Hades")], store="steam")
    calls = []
    steam_like = Provider("steam", "s", (), metadata=lambda store_id: None, match=lambda t: calls.append(t) or [])
    assert game_metadata(conn, {"steam": steam_like}, 1, match=True) is None and calls == []


def test_auto_match_is_off_until_turned_on(tmp_path):
    conn = connect(tmp_path / "db.sqlite3")
    assert get_auto_match(conn) is False
    set_auto_match(conn, True)
    assert get_auto_match(conn) is True
    set_auto_match(conn, None)
    assert get_auto_match(conn) is False


def test_the_detail_pane_credits_the_match_with_a_link(tmp_path):
    import asyncio

    from textual.widgets import Static

    from ludex.tui import LudexApp

    conn, game_id = database(tmp_path)
    game_metadata(conn, {"db": db_provider([SearchHit("db", "7", "Hades", "https://x/hades")])}, game_id, match=True)
    conn.close()

    async def scenario():
        app = LudexApp(tmp_path / "db.sqlite3", {})
        async with app.run_test() as pilot:
            await pilot.pause()
            app._show_game(game_id)
            await pilot.pause()
            content = app.query_one("#detail", Static).visual
            assert "matched to db: Hades" in str(content)
            assert any("https://x/hades" in str(span.style) for span in content.spans)

    asyncio.run(scenario())


def test_the_users_pick_replaces_an_automatic_match_survives_refresh_and_can_be_cleared(tmp_path):
    conn, game_id = database(tmp_path)
    auto = SearchHit("db", "7", "Hades", "https://x/hades")
    other = SearchHit("db", "9", "Hades (2016)", "https://x/hades-2016")
    sources = {"db": Provider("db", "d", (), metadata=lambda store_id: Metadata("D" + store_id, (), (), None), match=lambda title: [auto, other])}
    assert default_query(conn, game_id) == "Hades"
    hits, problems = match_candidates(sources, "Hades")
    assert [(p, h.store_id) for p, h in hits] == [("db", "7"), ("db", "9")] and not problems
    game_metadata(conn, sources, game_id, match=True)
    assert get_game(conn, game_id)["title"] == "Hades"
    assert choose_match(conn, sources, game_id, "db", other).description == "D9"
    assert get_game(conn, game_id)["title"] == "Hades (2016)"
    assert cached_match(conn, "local", "Hades_v1.2_(GOG)")["manual"] is True
    assert game_metadata(conn, sources, game_id, refresh=True, match=True).description == "D9"  # not replaced by the automatic match
    assert clear_match(conn, game_id) is True and clear_match(conn, game_id) is False
    assert get_game(conn, game_id)["title"] == "Hades_v1.2_(GOG)"
    assert cached_match(conn, "local", "Hades_v1.2_(GOG)") is None
    with pytest.raises(LudexError, match="no details"):
        choose_match(conn, {"db": Provider("db", "d", (), metadata=lambda s: None, match=lambda t: [])}, game_id, "db", other)
    with pytest.raises(LudexError, match="no installed plugin"):
        choose_match(conn, {}, game_id, "db", other)


def test_match_candidates_report_failing_plugins_and_skip_plugins_without_match():
    broken = db_provider(SourceError("rawg_no_key", "set a key"))
    plain = Provider("plain", "p", (), metadata=lambda s: None)
    hits, problems = match_candidates({"a": broken, "b": plain, "c": db_provider([SearchHit("db", "1", "X", "https://x/1")])}, "x")
    assert [p for p, _ in hits] == ["c"] and problems == {"a": "set a key"}


def test_m_opens_the_picker_and_a_choice_sets_the_title_and_details(tmp_path):
    import asyncio

    from textual.widgets import OptionList

    from ludex.tui import LudexApp

    conn, game_id = database(tmp_path)
    conn.close()
    hit = SearchHit("db", "7", "Hades", "https://x/hades")
    sources = {"db": Provider("db", "d", (), metadata=lambda store_id: Metadata("Slash.", (), (), None), match=lambda title: [hit])}

    async def scenario():
        app = LudexApp(tmp_path / "db.sqlite3", sources)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause(0.5)
            results = app.screen.query_one(OptionList)
            assert results.option_count == 1
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause(0.5)
            assert str(app.query_one("#owned-table").get_row_at(0)[1]) == "Hades"
            await pilot.press("m", "ctrl+r")
            await app.workers.wait_for_complete()
            await pilot.pause(0.5)
            assert str(app.query_one("#owned-table").get_row_at(0)[1]) == "Hades_v1.2_(GOG)"

    asyncio.run(scenario())
