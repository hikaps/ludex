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
        skipped = 0
        for hit in found:
            if not isinstance(hit, SearchHit):
                continue
            secure = hit.url.startswith("https://")
            if not secure and provider.acquire is None:  # ludex would open the link, so only https
                skipped += 1
                continue
            # a plugin that downloads itself needs no link: keep the hit, drop a link that is not https
            hits.append({"store": hit.store, "store_id": hit.store_id, "title": hit.title, "url": hit.url if secure else "",
                         "price": hit.price, "owned": (hit.store, hit.store_id) in owned})
        if skipped:
            problems[name] = f"{skipped} result{'s' if skipped != 1 else ''} skipped (link is not https)"
    return hits, problems
