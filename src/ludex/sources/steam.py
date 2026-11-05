"""Steam ownership source with two modes chosen by the account config.

With an ``api_key`` the Web API ``IPlayerService/GetOwnedGames`` returns the whole library
(complete: missing games are marked removed). Without a key the local Steam folder is read:
installed games (manifests) plus licensed games from the client cache (``steam_cache``). That is
``complete=False``: nothing is ever removed. The local layout
(``steamapps/libraryfolders.vdf``, ``appmanifest_*.acf``, ``config/loginusers.vdf``) is from public
documentation of the Steam client, not verified against a live install.

Endpoint assumption: the response shape (``{"response": {"game_count": N, "games": [...]}}``) and
the private-profile behavior (an empty ``{"response": {}}``) come from the public Web API docs and
are not live-verified. An empty ``response`` is treated as a private profile and raises, because
it cannot be told apart from a failed fetch; only an explicit ``game_count: 0`` is an empty library.
"""
from __future__ import annotations

from urllib.parse import quote

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import vdf

from .. import __version__
from ..plugins import ConfigField, FetchResult, Metadata, OwnedGame, Provider, SearchHit, SourceError
from .steam_cache import cached_games

DEFAULT_BASE_URL = "https://api.steampowered.com"
MAX_BODY_BYTES = 8 * 1024 * 1024
_STEAM_ID = re.compile(r"\d{17}")
_API_KEY = re.compile(r"[0-9A-Fa-f]{32}")
_STEAM_DIRS = (
    "~/.local/share/Steam",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
    "~/.steam/steam",
)
_TOOLS = re.compile(r"(Proton|Steam Linux Runtime|Steamworks Common Redistributables)")
_MAX_VDF_BYTES = 1024 * 1024


def _bad_response() -> SourceError:
    return SourceError("steam_bad_response", "Steam returned an unexpected response")


def _read_body(response: httpx.Response) -> bytes:
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_bytes():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            raise _bad_response()
        chunks.append(chunk)
    return b"".join(chunks)


def _request(client: httpx.Client, base_url: str, params: dict[str, str]) -> bytes:
    url = f"{base_url.rstrip('/')}/IPlayerService/GetOwnedGames/v0001/"
    try:
        with client.stream("GET", url, params=params) as response:
            status = response.status_code
            if status in (401, 403):
                raise SourceError("steam_auth_failed", "Steam rejected the API key or SteamID")
            if status == 429:
                raise SourceError("steam_rate_limited", "Steam rate limit reached; try again later")
            if status != 200:
                raise SourceError("steam_unavailable", "Steam is unavailable")
            return _read_body(response)
    except httpx.HTTPError:
        raise SourceError("steam_unavailable", "Steam is unavailable") from None


def _parse(body: bytes) -> list[OwnedGame]:
    try:
        payload = json.loads(body)
    except ValueError:
        raise _bad_response() from None
    if not isinstance(payload, dict) or not isinstance(payload.get("response"), dict):
        raise _bad_response()
    data: dict[str, Any] = payload["response"]
    count = data.get("game_count")
    games = data.get("games")
    if count is not None and (not isinstance(count, int) or isinstance(count, bool)):
        raise _bad_response()
    if games is None:
        if count is None:
            raise SourceError(
                "profile_private",
                "Steam returned no game list; set Game details to public in your Steam privacy settings",
            )
        if count != 0:
            raise _bad_response()
        return []
    if not isinstance(games, list) or (count is not None and count != len(games)):
        raise _bad_response()
    owned: list[OwnedGame] = []
    for entry in games:
        if not isinstance(entry, dict):
            raise _bad_response()
        appid = entry.get("appid")
        if not isinstance(appid, int) or isinstance(appid, bool) or appid <= 0:
            raise _bad_response()
        name = entry.get("name")
        title = name.strip() if isinstance(name, str) else ""
        owned.append(OwnedGame("steam", str(appid), title or f"Steam app {appid}", entry))
    return owned


def fetch_owned(
    config: Mapping[str, str],
    *,
    client: httpx.Client | None = None,
    base_url: str = DEFAULT_BASE_URL,
) -> list[OwnedGame]:
    steam_id = config.get("steam_id")
    api_key = config.get("api_key")
    if (
        not isinstance(steam_id, str)
        or not isinstance(api_key, str)
        or not _STEAM_ID.fullmatch(steam_id)
        or not _API_KEY.fullmatch(api_key)
    ):
        raise SourceError("invalid_config", "steam_id must be 17 digits and api_key 32 hex characters")
    params = {
        "key": api_key,
        "steamid": steam_id,
        "include_appinfo": "1",
        "include_played_free_games": "1",
        "format": "json",
    }
    if client is not None:
        return _parse(_request(client, base_url, params))
    with httpx.Client(
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0),
        follow_redirects=False,
        trust_env=False,
        headers={"User-Agent": f"ludex/{__version__}"},
    ) as own:
        return _parse(_request(own, base_url, params))


def _load_vdf(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > _MAX_VDF_BYTES:
            return {}
        with path.open(encoding="utf-8", errors="replace") as handle:
            return vdf.load(handle)
    except (OSError, SyntaxError, ValueError):
        return {}


def _steam_dir(config: Mapping[str, str]) -> Path:
    explicit = config.get("steam_dir")
    for candidate in (explicit,) if explicit else _STEAM_DIRS:
        path = Path(candidate).expanduser()
        if (path / "steamapps").is_dir():
            return path
    raise SourceError("steam_not_found", "Steam folder not found; set steam_dir to your Steam directory")


def _detect_steam_id(steam_dir: Path) -> str | None:
    users = _load_vdf(steam_dir / "config" / "loginusers.vdf").get("users")
    if not isinstance(users, dict):
        return None
    ids = [key for key in users if _STEAM_ID.fullmatch(key)]
    recent = [key for key in ids if isinstance(users[key], dict) and users[key].get("MostRecent") == "1"]
    pick = recent or ids
    return pick[0] if len(pick) == 1 else None


def _libraries(steam_dir: Path) -> list[Path]:
    libraries = [steam_dir]
    folders = _load_vdf(steam_dir / "steamapps" / "libraryfolders.vdf").get("libraryfolders")
    if isinstance(folders, dict):
        libraries += [Path(v["path"]) for v in folders.values() if isinstance(v, dict) and isinstance(v.get("path"), str)]
    return libraries


def installed(config: Mapping[str, str]) -> set[str]:
    """App ids whose manifest says fully installed (StateFlags bit 4; a missing flag counts as installed)."""
    found: set[str] = set()
    for library in _libraries(_steam_dir(config)):
        for manifest in (library / "steamapps").glob("appmanifest_*.acf"):
            state = _load_vdf(manifest).get("AppState")
            if not isinstance(state, dict) or not str(state.get("appid", "")).isdigit() or int(state["appid"]) <= 0:
                continue
            flags = str(state.get("StateFlags", "4"))
            if flags.isdigit() and int(flags) & 4:
                found.add(str(int(state["appid"])))
    return found


def _local(steam_dir: Path) -> list[OwnedGame]:
    libraries = _libraries(steam_dir)
    games: dict[str, OwnedGame] = {
        str(app_id): OwnedGame("steam", str(app_id), name, {"installed": False})
        for app_id, name in cached_games(steam_dir).items()
        if not _TOOLS.match(name)
    }
    for library in libraries:
        for manifest in sorted((library / "steamapps").glob("appmanifest_*.acf")):
            state = _load_vdf(manifest).get("AppState")
            if not isinstance(state, dict) or not str(state.get("appid", "")).isdigit() or int(state["appid"]) <= 0:
                continue
            appid = str(int(state["appid"]))
            name = state.get("name")
            title = name.strip() if isinstance(name, str) else ""
            if _TOOLS.match(title):
                continue
            # ponytail: local refresh overwrites raw_json with this stub; API-only fields return on the next API import
            games[appid] = OwnedGame("steam", appid, title or f"Steam app {appid}", {"installed": True})
    return list(games.values())


STORE_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"


def search(query: str, *, url: str = STORE_SEARCH_URL, client: httpx.Client | None = None) -> list[SearchHit]:
    """Steam store catalog search (public endpoint, no key). Prices are US storefront prices."""
    own = client is None
    client = client or httpx.Client(timeout=10.0, headers={"User-Agent": f"ludex/{__version__}"})
    try:
        with client.stream("GET", url, params={"term": query, "l": "english", "cc": "us"}) as response:
            if response.status_code == 429:
                raise SourceError("steam_rate_limited", "Steam rate limit reached; try again later")
            if response.status_code != 200:
                raise SourceError("steam_unavailable", "Steam is unavailable")
            body = _read_body(response)
    except httpx.HTTPError:
        raise SourceError("steam_unavailable", "Steam is unavailable") from None
    finally:
        if own:
            client.close()
    try:
        items = json.loads(body)["items"]
    except (ValueError, KeyError, TypeError):
        raise _bad_response() from None
    if not isinstance(items, list):
        raise _bad_response()
    hits: list[SearchHit] = []
    for item in items:
        if not isinstance(item, dict) or item.get("type") != "app" or not isinstance(item.get("name"), str):
            continue
        app_id = item.get("id")
        if not isinstance(app_id, int) or isinstance(app_id, bool) or app_id <= 0:
            continue
        price = item.get("price")
        label = None
        if isinstance(price, dict) and isinstance(price.get("final"), int) and isinstance(price.get("currency"), str):
            label = f"{price['final'] / 100:.2f} {price['currency']}"
        hits.append(SearchHit("steam", str(app_id), item["name"], f"https://store.steampowered.com/app/{app_id}", label))
    return hits


APP_DETAILS_URL = "https://store.steampowered.com/api/appdetails"


def metadata(store_id: str, *, url: str = APP_DETAILS_URL, client: httpx.Client | None = None) -> Metadata | None:
    """Steam store details for one app (public endpoint, no key); ``None`` when Steam has no entry."""
    own = client is None
    client = client or httpx.Client(timeout=10.0, headers={"User-Agent": f"ludex/{__version__}"})
    try:
        with client.stream("GET", url, params={"appids": store_id, "l": "english"}) as response:
            if response.status_code == 429:
                raise SourceError("steam_rate_limited", "Steam rate limit reached; try again later")
            if response.status_code != 200:
                raise SourceError("steam_unavailable", "Steam is unavailable")
            body = _read_body(response)
    except httpx.HTTPError:
        raise SourceError("steam_unavailable", "Steam is unavailable") from None
    finally:
        if own:
            client.close()
    try:
        entry = json.loads(body)[store_id]
    except (ValueError, KeyError, TypeError):
        raise _bad_response() from None
    if not isinstance(entry, dict):
        raise _bad_response()
    data = entry.get("data")
    if not entry.get("success") or not isinstance(data, dict):
        return None

    def names(value: object, key: str | None = None) -> tuple[str, ...]:
        items = value if isinstance(value, list) else []
        return tuple(x if key is None else x.get(key) for x in items if isinstance(x, str if key is None else dict) and isinstance(x if key is None else x.get(key), str))

    description = data.get("short_description")
    released = data.get("release_date")
    return Metadata(
        description if isinstance(description, str) and description else None,
        names(data.get("genres"), "description"),
        names(data.get("developers")),
        released.get("date") if isinstance(released, dict) and isinstance(released.get("date"), str) and released["date"] else None,
    )


def fetch(config: Mapping[str, str]) -> FetchResult:
    if config.get("api_key"):
        steam_id = config.get("steam_id")
        if not steam_id:
            try:
                steam_id = _detect_steam_id(_steam_dir(config))
            except SourceError:
                steam_id = None
        return FetchResult(fetch_owned({**config, "steam_id": steam_id or ""}), True, "api")
    return FetchResult(_local(_steam_dir(config)), False, "local")


PLUGIN = Provider(
    name="steam",
    help="Steam library: Web API with a key (full, needs public game details), otherwise the local Steam folder (installed and cached licensed games)",
    config_fields=(
        ConfigField("api_key", "Steam Web API key; blank to read the local Steam folder only", secret=True, optional=True),
        ConfigField("steam_id", "SteamID64; blank to detect from the local Steam folder", optional=True),
        ConfigField("steam_dir", "Steam folder; blank to auto-detect", optional=True),
    ),
    fetch=fetch,
    installed=installed,
    search=search,
    metadata=metadata,
    match=search,
    install_url=lambda store_id: f"steam://install/{quote(store_id, safe='')}",
    launch_url=lambda store_id: f"steam://rungameid/{quote(store_id, safe='')}",
)
