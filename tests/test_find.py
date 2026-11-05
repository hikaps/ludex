from __future__ import annotations

import json

import httpx
import pytest

from ludex.find import find_games
from ludex.plugins import Provider, SearchHit, SourceError
from ludex.sources import steam

BODY = {"total": 3, "items": [
    {"type": "app", "id": 1145360, "name": "Hades", "price": {"currency": "USD", "initial": 2499, "final": 1249}},
    {"type": "bundle", "id": 5, "name": "A bundle"},
    {"type": "app", "id": 7, "name": "Free Thing"},
]}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_steam_search_parses_apps_prices_and_links():
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=BODY)

    hits = steam.search("hades", client=_client(handler))
    assert seen == [{"term": "hades", "l": "english", "cc": "us"}]
    assert [(h.store_id, h.title, h.price, h.url) for h in hits] == [
        ("1145360", "Hades", "12.49 USD", "https://store.steampowered.com/app/1145360"),
        ("7", "Free Thing", None, "https://store.steampowered.com/app/7"),
    ]


@pytest.mark.parametrize("response, code", [
    (httpx.Response(429), "steam_rate_limited"),
    (httpx.Response(500), "steam_unavailable"),
    (httpx.Response(200, content=b"not json"), "steam_bad_response"),
    (httpx.Response(200, json={"items": "x"}), "steam_bad_response"),
])
def test_steam_search_errors_are_stable(response, code):
    with pytest.raises(SourceError) as info:
        steam.search("x", client=_client(lambda request: response))
    assert info.value.code == code


def test_find_marks_owned_skips_failures_and_rejects_plain_http_links():
    good = Provider("good", "g", (), search=lambda q: [
        SearchHit("good", "1", "Hades", "https://x/1", "1 USD"), SearchHit("good", "2", "Bad link", "http://x/2")])

    def boom(query):
        raise SourceError("nope", "cannot search")

    providers = {"good": good, "bad": Provider("bad", "b", (), search=boom), "plain": Provider("plain", "p", (), launch_url=str)}
    hits, problems = find_games(providers, "h", {("good", "1")})
    assert [(h["title"], h["owned"]) for h in hits] == [("Hades", True)]
    assert problems == {"bad": "cannot search"}
