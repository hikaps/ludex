"""Game metadata: asked of a plugin on request, then kept in the library database."""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict

from .errors import LudexError
from .library import get_game
from .plugins import Metadata, Provider
from .storage import normalize_title

_BRACKETS = re.compile(r"[(\[{][^)\]}]*[)\]}]")
_VERSION = re.compile(r"[ _.-]+(v\d.*|\d+(\.\d+)+.*)$", re.IGNORECASE)


def clean_title(name: str) -> str:
    """A folder name without bracketed tags and a trailing version: ``Hades_v1.2_(GOG)`` -> ``Hades``."""
    text = _VERSION.sub("", _BRACKETS.sub(" ", name))
    return re.sub(r"[\s_]+", " ", text).strip(" -.") or name


def cached_metadata(conn: sqlite3.Connection, store: str, store_id: str) -> Metadata | None:
    row = conn.execute("SELECT data FROM game_metadata WHERE store = ? AND store_id = ?", (store, store_id)).fetchone()
    if row is None:
        return None
    data = json.loads(row["data"])
    return Metadata(data.get("description"), tuple(data.get("genres", ())), tuple(data.get("developers", ())), data.get("released"))


def cached_match(conn: sqlite3.Connection, store: str, store_id: str) -> dict[str, str] | None:
    """``{"plugin", "title", "url"}`` when the cached metadata of this copy came from a title match.

    ``url`` is the match's page (an ``https`` link, the credit some databases require) or ``""``.
    """
    row = conn.execute("SELECT data FROM game_metadata WHERE store = ? AND store_id = ?", (store, store_id)).fetchone()
    matched = json.loads(row["data"]).get("matched") if row else None
    if not isinstance(matched, dict):
        return None
    url = matched.get("url")
    return {"plugin": str(matched["plugin"]), "title": str(matched["title"]), "url": url if isinstance(url, str) and url.startswith("https://") else ""}


def _store(conn: sqlite3.Connection, store: str, store_id: str, found: Metadata, extra: dict | None = None) -> None:
    with conn:
        conn.execute(
            "INSERT INTO game_metadata(store, store_id, data) VALUES (?, ?, ?) "
            "ON CONFLICT(store, store_id) DO UPDATE SET data = excluded.data",
            (store, store_id, json.dumps({**asdict(found), **(extra or {})})),
        )


def _match_by_title(conn: sqlite3.Connection, sources: Mapping[str, Provider], game_id: int, store: str, store_id: str, folder_name: str) -> Metadata | None:
    """Find the game by its cleaned name in a plugin that offers ``match``; on an exact title match keep its details and title."""
    query = clean_title(folder_name)
    for name, provider in sorted(sources.items()):
        if provider.match is None or provider.metadata is None:
            continue
        try:
            hit = next((h for h in provider.match(query) if normalize_title(h.title) == normalize_title(query)), None)
            found = provider.metadata(hit.store_id) if hit else None
        except Exception:  # a plugin that is down or has no key is skipped; the next one may know the game
            continue
        if found is None:
            continue
        _store(conn, store, store_id, found, {"matched": {"plugin": name, "id": hit.store_id, "title": hit.title, "url": hit.url}})
        with conn:
            conn.execute("UPDATE games SET title = ?, normalized_title = ? WHERE id = ?", (hit.title, normalize_title(hit.title), game_id))
        return found
    return None


def game_metadata(conn: sqlite3.Connection, sources: Mapping[str, Provider], game_id: int, refresh: bool = False, match: bool = False) -> Metadata | None:
    """Cached metadata for a game, else ask the first provider that owns a copy and can supply it.

    With ``match`` a game no owning provider can describe is looked up by its cleaned folder name
    in the plugins that offer ``match`` (the game's title and details then come from the match).
    """
    live = [o for o in get_game(conn, game_id)["ownership"] if not o["removed"]]
    copies = [(o["store"], str(o["store_id"])) for o in live]
    if not refresh:
        for store, store_id in copies:
            found = cached_metadata(conn, store, store_id)
            if found is not None:
                return found
    for store, store_id in copies:
        provider = sources.get(store)
        if provider is None or provider.metadata is None:
            continue
        found = provider.metadata(store_id)
        if found is None:
            continue
        _store(conn, store, store_id, found)
        return found
    if not any(sources.get(store) is not None and sources[store].metadata for store, _ in copies):
        if match and live:
            return _match_by_title(conn, sources, game_id, copies[0][0], copies[0][1], live[0]["title"])
        raise LudexError("metadata_unavailable", "no installed plugin supplies metadata for this game's stores")
    return None


def get_auto_details(conn: sqlite3.Connection) -> bool:
    """Whether the TUI fetches details for the highlighted game by itself (default yes)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'auto_details'").fetchone()
    return row is None or row["value"] != "0"


def set_auto_details(conn: sqlite3.Connection, on: bool | None) -> None:
    """Turn it on or off; ``None`` goes back to the default (on)."""
    with conn:
        if on is None or on:
            conn.execute("DELETE FROM meta WHERE key = 'auto_details'")
        else:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('auto_details', '0')")


def get_auto_match(conn: sqlite3.Connection) -> bool:
    """Whether games no store can describe are matched by title in a database plugin (default no)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'auto_match'").fetchone()
    return row is not None and row["value"] == "1"


def set_auto_match(conn: sqlite3.Connection, on: bool | None) -> None:
    """Turn it on or off; ``None`` goes back to the default (off)."""
    with conn:
        if on:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('auto_match', '1')")
        else:
            conn.execute("DELETE FROM meta WHERE key = 'auto_match'")
