from __future__ import annotations

import json

import httpx
import pytest

from ludex.plugins import SourceError, Provider
from ludex.sources.steam import MAX_BODY_BYTES, PLUGIN, fetch_owned

KEY = "0123456789abcdef0123456789ABCDEF"
CONFIG = {"steam_id": "76561198000000000", "api_key": KEY}


def run(handler, config=CONFIG):
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        return fetch_owned(config, client=client)


def respond(status=200, payload=None, content=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if content is not None:
            return httpx.Response(status, content=content)
        return httpx.Response(status, json=payload)

    return handler


def assert_failure(handler, code):
    with pytest.raises(SourceError) as info:
        run(handler)
    assert info.value.code == code
    text = f"{info.value.code} {info.value.message}"
    assert KEY not in text
    assert "api.steampowered.com" not in text


def test_success_mapping():
    games = [
        {"appid": 10, "name": "  Counter-Strike "},
        {"appid": 20},
        {"appid": 30, "name": ""},
    ]
    result = run(respond(payload={"response": {"game_count": 3, "games": games}}))
    assert [(g.store, g.store_id, g.title) for g in result] == [
        ("steam", "10", "Counter-Strike"),
        ("steam", "20", "Steam app 20"),
        ("steam", "30", "Steam app 30"),
    ]
    assert result[0].extra == games[0]


def test_games_without_count_accepted():
    assert len(run(respond(payload={"response": {"games": [{"appid": 1}]}}))) == 1


def test_request_params():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"response": {"game_count": 0}})

    run(handler)
    request = seen[0]
    assert request.url.path == "/IPlayerService/GetOwnedGames/v0001/"
    assert request.url.params["key"] == KEY
    assert request.url.params["steamid"] == CONFIG["steam_id"]
    assert request.url.params["include_appinfo"] == "1"
    assert request.url.params["include_played_free_games"] == "1"
    assert "authorization" not in request.headers


def test_private_profile():
    assert_failure(respond(payload={"response": {}}), "profile_private")


def test_empty_library():
    assert run(respond(payload={"response": {"game_count": 0}})) == []


def test_game_count_mismatch():
    payload = {"response": {"game_count": 2, "games": [{"appid": 1}]}}
    assert_failure(respond(payload=payload), "steam_bad_response")


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (401, "steam_auth_failed"),
        (403, "steam_auth_failed"),
        (429, "steam_rate_limited"),
        (500, "steam_unavailable"),
        (302, "steam_unavailable"),
    ],
)
def test_http_status(status, code):
    assert_failure(respond(status=status, payload={}), code)


def test_timeout():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout(f"timed out {request.url}", request=request)

    assert_failure(handler, "steam_unavailable")


@pytest.mark.parametrize(
    "content",
    [
        b"not json",
        json.dumps([1]).encode(),
        json.dumps({"response": []}).encode(),
        json.dumps({"response": {"game_count": "2", "games": []}}).encode(),
        json.dumps({"response": {"games": {"appid": 1}}}).encode(),
        json.dumps({"response": {"games": [1]}}).encode(),
        json.dumps({"response": {"games": [{"appid": "1"}]}}).encode(),
        json.dumps({"response": {"games": [{"appid": True}]}}).encode(),
        json.dumps({"response": {"games": [{"appid": 0}]}}).encode(),
        json.dumps({"response": {"games": [{"name": "x"}]}}).encode(),
        b" " * (MAX_BODY_BYTES + 1),
    ],
)
def test_bad_response(content):
    assert_failure(respond(content=content), "steam_bad_response")


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"steam_id": CONFIG["steam_id"]},
        {"api_key": KEY},
        {"steam_id": "123", "api_key": KEY},
        {"steam_id": CONFIG["steam_id"], "api_key": "short"},
        {"steam_id": CONFIG["steam_id"], "api_key": "g" * 32},
    ],
)
def test_invalid_config(config):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(SourceError) as info:
        run(handler, config)
    assert info.value.code == "invalid_config"
    assert "short" not in info.value.message


def test_plugin_definition():
    assert isinstance(PLUGIN, Provider)
    assert PLUGIN.name == "steam"
    assert [f.name for f in PLUGIN.config_fields if f.secret] == ["api_key"]


def _steam_tree(tmp_path):
    steam, lib2 = tmp_path / "Steam", tmp_path / "lib2"
    for root in (steam, lib2):
        (root / "steamapps").mkdir(parents=True)
    (steam / "config").mkdir()
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        f'"libraryfolders"\n{{\n"0"\n{{\n"path" "{steam}"\n}}\n"1"\n{{\n"path" "{lib2}"\n}}\n}}\n'
    )

    def manifest(root, appid, name):
        (root / "steamapps" / f"appmanifest_{appid}.acf").write_text(f'"AppState"\n{{\n"appid" "{appid}"\n"name" "{name}"\n}}\n')

    manifest(steam, 10, "Counter-Strike")
    manifest(lib2, 20, "Team Fortress Classic")
    manifest(steam, 1493710, "Proton Experimental")
    (steam / "steamapps" / "appmanifest_99.acf").write_text("not vdf {{{")
    (steam / "config" / "loginusers.vdf").write_text(
        '"users"\n{\n"76561198000000001"\n{\n"MostRecent" "0"\n}\n"76561198000000002"\n{\n"MostRecent" "1"\n}\n}\n'
    )
    return steam


def test_local_mode_reads_installed_games_and_is_incomplete(tmp_path):
    steam = _steam_tree(tmp_path)
    result = PLUGIN.fetch({"steam_dir": str(steam)})
    assert (result.complete, result.mode) == (False, "local")
    assert sorted((g.store_id, g.title) for g in result.games) == [("10", "Counter-Strike"), ("20", "Team Fortress Classic")]


def test_local_mode_without_steam_folder_raises(tmp_path):
    with pytest.raises(SourceError) as info:
        PLUGIN.fetch({"steam_dir": str(tmp_path / "missing")})
    assert info.value.code == "steam_not_found"


def test_api_mode_is_complete_and_detects_steam_id(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr("ludex.sources.steam.fetch_owned", lambda config: seen.update(config) or [])
    result = PLUGIN.fetch({"api_key": "a" * 32, "steam_dir": str(_steam_tree(tmp_path))})
    assert (result.complete, result.mode) == (True, "api")
    assert seen["steam_id"] == "76561198000000002"


def test_api_mode_explicit_steam_id_skips_detection(monkeypatch):
    seen = {}
    monkeypatch.setattr("ludex.sources.steam.fetch_owned", lambda config: seen.update(config) or [])
    PLUGIN.fetch({"api_key": "a" * 32, "steam_id": "76561198000000009"})
    assert seen["steam_id"] == "76561198000000009"
