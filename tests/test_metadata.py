from __future__ import annotations

import asyncio
import dataclasses

import httpx
import pytest

from ludex.errors import LudexError
from ludex.library import import_account
from ludex.metadata import cached_metadata, game_metadata
from ludex.plugins import Metadata, OwnedGame, Provider, SourceError
from ludex.sources import steam
from ludex.storage import connect
from ludex.tui import LudexApp
from textual.widgets import Static


def ask(payload, status=200, appid="10"):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(status, json=payload))) as client:
        return steam.metadata(appid, client=client)


def test_steam_metadata_reads_description_genres_developers_and_date():
    data = {"short_description": "Slash.", "genres": [{"id": "1", "description": "Action"}, {"description": 3}], "developers": ["Supergiant"], "release_date": {"date": "17 Sep, 2020"}}
    assert ask({"10": {"success": True, "data": data}}) == Metadata("Slash.", ("Action",), ("Supergiant",), "17 Sep, 2020")


def test_steam_metadata_unknown_app_is_none_and_bad_answers_are_stable_errors():
    assert ask({"10": {"success": False}}) is None
    with pytest.raises(SourceError) as exc:
        ask({"other": {}})
    assert exc.value.code == "steam_bad_response"
    with pytest.raises(SourceError) as exc:
        ask({}, status=503)
    assert exc.value.code == "steam_unavailable"


def provider(calls):
    def metadata(store_id):
        calls.append(store_id)
        return Metadata("About", ("RPG",))
    return Provider("s", "x", (), metadata=metadata)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "db.sqlite3")
    import_account(c, "m", [OwnedGame("s", "1", "Hades")], store="s")
    return c


def test_metadata_is_asked_once_kept_and_refreshable(conn):
    calls = []
    sources = {"s": provider(calls)}
    assert game_metadata(conn, sources, 1) == Metadata("About", ("RPG",))
    assert game_metadata(conn, {}, 1) == Metadata("About", ("RPG",))  # kept: no provider needed
    assert calls == ["1"] and cached_metadata(conn, "s", "1") is not None
    game_metadata(conn, sources, 1, refresh=True)
    assert calls == ["1", "1"]


def test_a_game_nobody_can_describe_is_an_error_or_none(conn):
    with pytest.raises(LudexError) as exc:
        game_metadata(conn, {"s": Provider("s", "x", (), lambda c: None)}, 1)
    assert exc.value.code == "metadata_unavailable"
    assert game_metadata(conn, {"s": Provider("s", "x", (), metadata=lambda i: None)}, 1) is None


def test_details_key_fetches_and_the_pane_shows_it(tmp_path):
    db = tmp_path / "db.sqlite3"
    c = connect(db)
    import_account(c, "m", [OwnedGame("s", "1", "Hades")], store="s")
    c.close()

    async def scenario():
        app = LudexApp(db, {"s": provider([])})
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("m")
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = str(app.query_one("#detail", Static).render())
            assert "About" in text and "RPG" in text

    asyncio.run(scenario())
