from __future__ import annotations

import httpx
import pytest

from ludex.artwork import cached_cover, fetch_cover
from ludex.errors import LudexError
from ludex.library import get_game, import_account
from ludex.metadata import game_metadata
from ludex.paths import state_paths
from ludex.plugins import MAX_COVER_BYTES, ConfigField, Metadata, OwnedGame, Provider, SearchHit, SourceError
from ludex.provider_settings import set_value
from ludex.sources import rawg, steam, steamgriddb
from ludex.storage import connect

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 32


@pytest.fixture
def state(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("LUDEX_HOME", str(home))
    paths = state_paths()
    conn = connect(paths.database)
    yield paths, conn
    conn.close()


def owned(conn, store="steam", store_id="10", title="Hades"):
    import_account(conn, "a", [OwnedGame(store, store_id, title)], store=store)
    return conn.execute("SELECT id FROM games WHERE title = ?", (title,)).fetchone()["id"]


def provider(name, cover, **extra):
    return Provider(name, "x", (), cover=cover, **extra)


def test_cover_is_fetched_once_kept_privately_and_then_served_without_the_plugin(state):
    paths, conn = state
    game = owned(conn)
    calls = []
    sources = {"steam": provider("steam", lambda store_id: calls.append(store_id) or PNG)}
    assert cached_cover(paths, conn, game) is None
    file = fetch_cover(paths, conn, sources, game)
    assert file.read_bytes() == PNG and file.stat().st_mode & 0o077 == 0 and file.parent.stat().st_mode & 0o077 == 0
    assert cached_cover(paths, conn, game) == file
    assert fetch_cover(paths, conn, {}, game) == file and calls == ["10"]


def test_no_cover_is_remembered_and_a_failure_is_not(state):
    paths, conn = state
    game = owned(conn)
    calls = []

    def nothing(store_id):
        calls.append(store_id)

    assert fetch_cover(paths, conn, {"steam": provider("steam", nothing)}, game) is None
    assert fetch_cover(paths, conn, {"steam": provider("steam", nothing)}, game) is None and calls == ["10"]

    other = owned(conn, "gog", "5", "Celeste")

    def down(store_id):
        calls.append(store_id)
        raise SourceError("gog_down", "GOG is unavailable")

    for _ in range(2):
        with pytest.raises(LudexError) as caught:
            fetch_cover(paths, conn, {"gog": provider("gog", down)}, other)
        assert caught.value.code == "gog_down"
    assert calls == ["10", "5", "5"]


@pytest.mark.parametrize("bad", ["not bytes", b"short", b"GIF89a" + b"\0" * 40, b"\x89PNG\r\n\x1a\n" + b"\0" * MAX_COVER_BYTES])
def test_invalid_plugin_data_is_refused_and_never_stored(state, bad):
    paths, conn = state
    game = owned(conn)
    with pytest.raises(LudexError) as caught:
        fetch_cover(paths, conn, {"steam": provider("steam", lambda _: bad)}, game)
    assert caught.value.code == "invalid_cover"
    assert cached_cover(paths, conn, game) is None


def test_a_plugin_exception_never_leaks_its_text(state):
    paths, conn = state
    game = owned(conn)

    def broken(store_id):
        raise RuntimeError("secret-token-123")

    with pytest.raises(LudexError) as caught:
        fetch_cover(paths, conn, {"steam": provider("steam", broken)}, game)
    assert caught.value.code == "cover_failed" and "secret-token-123" not in caught.value.message


def test_a_working_plugin_wins_over_a_failing_one(state):
    paths, conn = state
    game = owned(conn)

    def down(store_id):
        raise SourceError("steam_down", "down")

    steam_copy = provider("steam", down)
    import_account(conn, "b", [OwnedGame("gog", "5", "Hades")], store="gog")
    sources = {"steam": steam_copy, "gog": provider("gog", lambda _: JPEG)}
    assert fetch_cover(paths, conn, sources, game).read_bytes() == JPEG


def test_a_game_matched_by_title_takes_the_cover_of_its_match(state):
    paths, conn = state
    game = owned(conn, "local", "Hades_v1", "Hades_v1")
    asked = []
    db = Provider(
        "db", "x", (),
        metadata=lambda store_id: Metadata(genres=("Action",)),
        match=lambda title: [SearchHit("db", "77", "Hades", "https://x/hades")],
        cover=lambda store_id: asked.append(store_id) or PNG,
    )
    sources = {"db": db}
    game_metadata(conn, sources, game, match=True)
    assert get_game(conn, game)["title"] == "Hades"
    assert fetch_cover(paths, conn, sources, game).read_bytes() == PNG and asked == ["77"]


def test_steam_cover_prefers_portrait_art_then_the_banner_and_bounds_the_download():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("library_600x900.jpg"):
            return httpx.Response(404)
        return httpx.Response(200, stream=httpx.ByteStream(JPEG))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert steam.cover("10", client=client) == JPEG
        assert steam.cover("../x", client=client) is None
    assert seen == ["/steam/apps/10/library_600x900.jpg", "/steam/apps/10/header.jpg"]

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, stream=httpx.ByteStream(b"\0" * (MAX_COVER_BYTES + 1))))) as client:
        with pytest.raises(SourceError) as caught:
            steam.cover("10", client=client)
        assert caught.value.code == "steam_bad_response"

    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as client:
        with pytest.raises(SourceError) as caught:
            steam.cover("10", client=client)
        assert caught.value.code == "steam_unavailable"


def test_rawg_cover_follows_only_https_image_links_and_never_shows_the_key():
    key = "k3y-secret"

    def handler(request):
        if request.url.host == "api.rawg.io":
            assert request.url.params["key"] == key
            return httpx.Response(200, json={"background_image": "https://media.rawg.io/h.jpg"})
        assert request.url.params.get("key") is None
        return httpx.Response(200, stream=httpx.ByteStream(PNG))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert rawg.cover("7", settings={"api_key": key}, client=client) == PNG

    plain = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"background_image": "http://media.rawg.io/h.jpg"})))
    with plain:
        assert rawg.cover("7", settings={"api_key": key}, client=plain) is None

    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with httpx.Client(transport=httpx.MockTransport(boom)) as client:
        with pytest.raises(SourceError) as caught:
            rawg.cover("7", settings={"api_key": key}, client=client)
        assert key not in caught.value.message


def test_a_compressed_cover_response_is_refused_before_it_can_inflate():
    gzip = httpx.Response(200, headers={"content-encoding": "gzip"}, stream=httpx.ByteStream(b"x"))
    with httpx.Client(transport=httpx.MockTransport(lambda r: gzip)) as client:
        with pytest.raises(SourceError):
            steam.cover("570", base_url="https://x", client=client)


def test_steam_cover_falls_back_to_the_hashed_banner_a_newer_app_names_in_its_store_entry():
    seen = []

    def handler(request):
        seen.append(request.url.host + request.url.path)
        if request.url.path == "/api/appdetails":
            assert request.url.params["appids"] == "10"
            return httpx.Response(200, json={"10": {"success": True, "data": {"header_image": "https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/10/abc/header.jpg?t=1"}}})
        if request.url.host == "shared.akamai.steamstatic.com":
            return httpx.Response(200, stream=httpx.ByteStream(JPEG))
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert steam.cover("10", client=client) == JPEG
    assert seen[-1] == "shared.akamai.steamstatic.com/store_item_assets/steam/apps/10/abc/header.jpg"

    def elsewhere(request):  # a banner link on another host is never followed
        if request.url.path == "/api/appdetails":
            return httpx.Response(200, json={"10": {"success": True, "data": {"header_image": "https://evil.example/h.jpg"}}})
        assert request.url.host != "evil.example"
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(elsewhere)) as client:
        assert steam.cover("10", client=client) is None


def test_a_game_no_store_has_a_cover_for_is_looked_up_by_title_once_the_plugin_is_configured(state):
    paths, conn = state
    game = owned(conn, "heroic", "app1", "Hades")
    asked = []
    art = Provider("art", "x", (), cover_by_title=lambda title: asked.append(title) or PNG, settings=(ConfigField("api_key", "k", secret=True),))
    sources = {"art": art}
    assert fetch_cover(paths, conn, sources, game) is None and asked == []  # no key yet: nothing is sent
    set_value(paths, art, "api_key", "k3y")
    file = fetch_cover(paths, conn, sources, game)
    assert file.read_bytes() == PNG and asked == ["Hades"]
    assert cached_cover(paths, conn, game) == file and fetch_cover(paths, conn, {}, game) == file and asked == ["Hades"]


def test_a_stores_own_cover_wins_and_a_title_miss_is_remembered_per_plugin(state):
    paths, conn = state
    game = owned(conn, "heroic", "app1", "Hades")
    asked = []
    none = Provider("none", "x", (), cover_by_title=lambda title: asked.append("none"))
    late = Provider("late", "x", (), cover_by_title=lambda title: asked.append("late") or JPEG)
    store = Provider("heroic", "x", (), cover=lambda store_id: PNG)
    assert fetch_cover(paths, conn, {"heroic": store, "none": none}, game).read_bytes() == PNG and asked == []
    second = owned(conn, "local", "x", "Doom")
    assert fetch_cover(paths, conn, {"none": none}, second) is None
    assert fetch_cover(paths, conn, {"none": none}, second) is None and asked == ["none"]  # not asked again
    assert fetch_cover(paths, conn, {"none": none, "late": late}, second).read_bytes() == JPEG and asked == ["none", "late"]


def test_steamgriddb_takes_a_portrait_grid_of_the_exactly_named_game_and_keeps_the_key_to_its_api():
    key = "k3y-secret"
    seen = []

    def handler(request):
        seen.append((request.url.host, request.headers.get("authorization")))
        if request.url.path.startswith("/api/v2/search/autocomplete/"):
            return httpx.Response(200, json={"success": True, "data": [{"id": 1, "name": "Hades II"}, {"id": 2, "name": "hades"}]})
        if request.url.path == "/api/v2/grids/game/2":
            assert request.url.params["dimensions"] == steamgriddb.PORTRAIT and request.url.params["nsfw"] == "false"
            return httpx.Response(200, json={"data": [{"url": "http://cdn2.steamgriddb.com/a.png"}, {"url": "https://evil.example/b.png"}, {"url": "https://cdn2.steamgriddb.com/c.png"}]})
        return httpx.Response(200, stream=httpx.ByteStream(PNG))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert steamgriddb.cover_by_title("Hades", settings={"api_key": key}, client=client) == PNG
    assert ("cdn2.steamgriddb.com", None) in seen and all(auth == f"Bearer {key}" for host, auth in seen if host == "www.steamgriddb.com")
    assert not any(host == "evil.example" for host, _ in seen)  # only SteamGridDB's hosts, over https


def test_steamgriddb_never_guesses_a_similar_title_and_its_errors_hide_the_key():
    key = "k3y-secret"
    similar = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"id": 1, "name": "Hades II"}]})))
    with similar:
        assert steamgriddb.cover_by_title("Hades", settings={"api_key": key}, client=similar) is None
    with pytest.raises(SourceError) as caught:
        steamgriddb.cover_by_title("Hades", settings={})
    assert caught.value.code == "steamgriddb_no_key"

    def boom(request):
        raise httpx.ConnectError(f"cannot reach {request.url} with {request.headers['authorization']}")

    for handler, code in ((boom, "steamgriddb_unavailable"), (lambda r: httpx.Response(401), "steamgriddb_auth_failed"), (lambda r: httpx.Response(429), "steamgriddb_rate_limited")):
        with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(SourceError) as caught:
            steamgriddb.cover_by_title("Hades", settings={"api_key": key}, client=client)
        assert caught.value.code == code and key not in caught.value.message
