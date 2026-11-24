"""SteamGridDB (steamgriddb.com): portrait cover art found by a game's title. Needs the user's own API key.

The key is the plugin setting ``api_key`` (``ludex config steamgriddb.api_key --secret``) and travels in
an ``Authorization`` header to the API only, never to the image host. Setting it is the consent to send
the titles of games that have no cover to SteamGridDB (see ``cover_by_title`` in ``ludex.plugins``).
Only a game whose name equals the title is used, and only a portrait grid, so a card never shows art
of a different game or a landscape banner.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .. import __version__
from ..plugins import MAX_COVER_BYTES, ConfigField, Provider, SourceError
from ..storage import normalize_title

BASE_URL = "https://www.steamgriddb.com/api/v2"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_TITLE = 200
PORTRAIT = "600x900,342x482,660x930"  # the library-capsule shapes
_RAW = {"Accept-Encoding": "identity"}  # an image is already compressed; never let a response inflate past the cap


def _bad_response() -> SourceError:
    return SourceError("steamgriddb_bad_response", "SteamGridDB returned an unexpected response")


def _get(path: str, params: dict[str, str], settings: Mapping[str, str], client: httpx.Client, base_url: str) -> Any:
    key = settings.get("api_key")
    if not key:
        raise SourceError("steamgriddb_no_key", "set a SteamGridDB API key: ludex config steamgriddb.api_key --secret")
    try:
        with client.stream("GET", f"{base_url}/{path}", params=params, headers={"Authorization": f"Bearer {key}"}) as response:
            if response.status_code in (401, 403):
                raise SourceError("steamgriddb_auth_failed", "SteamGridDB rejected the API key")
            if response.status_code == 429:
                raise SourceError("steamgriddb_rate_limited", "SteamGridDB rate limit reached; try again later")
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise SourceError("steamgriddb_unavailable", "SteamGridDB is unavailable")
            body = bytearray()
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BODY_BYTES:
                    raise _bad_response()
    except httpx.HTTPError:
        raise SourceError("steamgriddb_unavailable", "SteamGridDB is unavailable") from None
    try:
        return json.loads(body)
    except ValueError:
        raise _bad_response() from None


def _image(client: httpx.Client, url: object) -> bytes | None:
    parts = urlsplit(url) if isinstance(url, str) else None
    if parts is None or parts.scheme != "https" or not (parts.hostname or "").endswith(".steamgriddb.com"):
        return None  # only SteamGridDB's own hosts, over https
    try:
        with client.stream("GET", url, headers=_RAW) as response:
            if response.status_code in (403, 404):
                return None
            if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() != "identity":
                raise SourceError("steamgriddb_unavailable", "SteamGridDB is unavailable")
            body = bytearray()
            for chunk in response.iter_raw():
                body += chunk
                if len(body) > MAX_COVER_BYTES:
                    raise _bad_response()
            return bytes(body)
    except httpx.HTTPError:
        raise SourceError("steamgriddb_unavailable", "SteamGridDB is unavailable") from None


def cover_by_title(title: str, *, settings: Mapping[str, str], client: httpx.Client | None = None, base_url: str = BASE_URL) -> bytes | None:
    """The best portrait grid of the game named exactly ``title``; ``None`` when SteamGridDB has none."""
    title = title.strip()
    if not title or len(title) > MAX_TITLE:
        return None
    own = client is None
    client = client or httpx.Client(timeout=10.0, headers={"User-Agent": f"ludex/{__version__}"})
    try:
        found = _get(f"search/autocomplete/{quote(title, safe='')}", {}, settings, client, base_url)
        games = found.get("data") if isinstance(found, dict) else None
        wanted = normalize_title(title)
        game = next((g for g in games if isinstance(g, dict) and isinstance(g.get("name"), str) and normalize_title(g["name"]) == wanted), None) if isinstance(games, list) else None
        game_id = game.get("id") if game else None
        if type(game_id) is not int:
            return None
        grids = _get(
            f"grids/game/{game_id}",
            {"dimensions": PORTRAIT, "types": "static", "mimes": "image/png,image/jpeg,image/webp", "nsfw": "false", "humor": "false", "epilepsy": "false", "limit": "5"},
            settings, client, base_url,
        )
        rows = grids.get("data") if isinstance(grids, dict) else None
        for row in rows if isinstance(rows, list) else ():
            image = _image(client, row.get("url") if isinstance(row, dict) else None)
            if image is not None:
                return image
        return None
    finally:
        if own:
            client.close()


PLUGIN = Provider(
    name="steamgriddb",
    help="SteamGridDB: portrait cover art for games your stores give none for (needs your own key)",
    config_fields=(),
    cover_by_title=cover_by_title,
    settings=(ConfigField("api_key", "your SteamGridDB API key (steamgriddb.com/profile/preferences/api)", secret=True),),
)
