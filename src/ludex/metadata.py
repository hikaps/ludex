"""Game metadata: asked of a plugin on request, then kept in the library database."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict

from .errors import LudexError
from .library import get_game
from .plugins import Metadata, Provider


def cached_metadata(conn: sqlite3.Connection, store: str, store_id: str) -> Metadata | None:
    row = conn.execute("SELECT data FROM game_metadata WHERE store = ? AND store_id = ?", (store, store_id)).fetchone()
    if row is None:
        return None
    data = json.loads(row["data"])
    return Metadata(data.get("description"), tuple(data.get("genres", ())), tuple(data.get("developers", ())), data.get("released"))


def game_metadata(conn: sqlite3.Connection, sources: Mapping[str, Provider], game_id: int, refresh: bool = False) -> Metadata | None:
    """Cached metadata for a game, else ask the first provider that owns a copy and can supply it."""
    copies = [(o["store"], str(o["store_id"])) for o in get_game(conn, game_id)["ownership"] if not o["removed"]]
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
        with conn:
            conn.execute(
                "INSERT INTO game_metadata(store, store_id, data) VALUES (?, ?, ?) "
                "ON CONFLICT(store, store_id) DO UPDATE SET data = excluded.data",
                (store, store_id, json.dumps(asdict(found))),
            )
        return found
    if not any(sources.get(store) is not None and sources[store].metadata for store, _ in copies):
        raise LudexError("metadata_unavailable", "no installed plugin supplies metadata for this game's stores")
    return None
