"""RAWG (rawg.io) game database: match a title and supply its details. Needs the user's own API key.

The key is the plugin setting ``api_key`` (``ludex config rawg.api_key --secret``). It travels in the
request URL, as RAWG requires, so errors never include the URL. RAWG asks that its data is credited
with a link to rawg.io; the core shows "matched to RAWG" with every result that came from here.
ponytail: no pagination or caching here (the core caches metadata); one request per call.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

import httpx

from .. import __version__
from ..plugins import ConfigField, Metadata, Provider, SearchHit, SourceError

BASE_URL = "https://api.rawg.io/api"
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_DESCRIPTION = 600
_SLUG = re.compile(r"[A-Za-z0-9._-]+\Z")


def _bad_response() -> SourceError:
    return SourceError("rawg_bad_response", "RAWG returned an unexpected response")


def _get(path: str, params: dict[str, str], settings: Mapping[str, str], client: httpx.Client | None, base_url: str) -> Any:
    key = settings.get("api_key")
    if not key:
        raise SourceError("rawg_no_key", "set a RAWG API key: ludex config rawg.api_key --secret")
    own = client is None
    client = client or httpx.Client(timeout=10.0, headers={"User-Agent": f"ludex/{__version__}"})
    try:
        with client.stream("GET", f"{base_url}/{path}", params={**params, "key": key}) as response:
            if response.status_code in (401, 403):
                raise SourceError("rawg_auth_failed", "RAWG rejected the API key")
            if response.status_code == 429:
                raise SourceError("rawg_rate_limited", "RAWG rate limit reached; try again later")
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                raise SourceError("rawg_unavailable", "RAWG is unavailable")
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    raise _bad_response()
                chunks.append(chunk)
    except httpx.HTTPError:
        raise SourceError("rawg_unavailable", "RAWG is unavailable") from None  # the URL holds the key
    finally:
        if own:
            client.close()
    try:
        return json.loads(b"".join(chunks))
    except ValueError:
        raise _bad_response() from None


def match(query: str, *, settings: Mapping[str, str], client: httpx.Client | None = None, base_url: str = BASE_URL) -> list[SearchHit]:
    """RAWG games whose name resembles ``query``, best first."""
    data = _get("games", {"search": query, "search_precise": "true", "page_size": "5"}, settings, client, base_url)
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise _bad_response()
    hits = []
    for item in results:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        game_id, slug = item.get("id"), item.get("slug")
        if isinstance(game_id, int) and not isinstance(game_id, bool) and game_id > 0 and isinstance(slug, str) and _SLUG.match(slug):
            hits.append(SearchHit("rawg", str(game_id), item["name"], f"https://rawg.io/games/{slug}"))
    return hits


def metadata(store_id: str, *, settings: Mapping[str, str], client: httpx.Client | None = None, base_url: str = BASE_URL) -> Metadata | None:
    """RAWG details for one game id; ``None`` when RAWG has no such game."""
    if not store_id.isascii() or not store_id.isdigit():
        return None
    data = _get(f"games/{store_id}", {}, settings, client, base_url)
    if data is None:
        return None
    if not isinstance(data, dict):
        raise _bad_response()

    def names(key: str) -> tuple[str, ...]:
        items = data.get(key)
        return tuple(x["name"] for x in items if isinstance(x, dict) and isinstance(x.get("name"), str)) if isinstance(items, list) else ()

    description = data.get("description_raw")
    if isinstance(description, str):
        description = description.strip()
        if len(description) > MAX_DESCRIPTION:
            description = description[:MAX_DESCRIPTION].rsplit(" ", 1)[0] + "…"
    released = data.get("released")
    return Metadata(
        description if isinstance(description, str) and description else None,
        names("genres"),
        names("developers"),
        released if isinstance(released, str) and released else None,
    )


PLUGIN = Provider(
    name="rawg",
    help="RAWG game database: titles and details for games your stores give none for (needs your own key)",
    config_fields=(),
    metadata=metadata,
    match=match,
    settings=(ConfigField("api_key", "your RAWG API key (rawg.io/apidocs)", secret=True),),
)
