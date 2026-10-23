"""Search the stores' catalogs through every provider that has the search capability."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from .plugins import Provider, SearchHit


def owned_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    return {(row["store"], row["store_id"]) for row in conn.execute("SELECT store, store_id FROM ownership WHERE removed = 0")}


def find_games(
    providers: Mapping[str, Provider], query: str, owned: set[tuple[str, str]]
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return ``(hits, {provider: reason})``; each hit says whether you already own it."""
    hits: list[dict[str, Any]] = []
    problems: dict[str, str] = {}
    for name, provider in sorted(providers.items()):
        if provider.search is None:
            continue
        try:
            found = list(provider.search(query))
        except Exception as exc:
            problems[name] = getattr(exc, "message", f"failed ({type(exc).__name__})")
            continue
        for hit in found:
            if isinstance(hit, SearchHit) and hit.url.startswith("https://"):
                hits.append({"store": hit.store, "store_id": hit.store_id, "title": hit.title, "url": hit.url,
                             "price": hit.price, "owned": (hit.store, hit.store_id) in owned})
    return hits, problems
