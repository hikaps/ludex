"""Import and query the library of owned games.

Removal policy (source of truth):

- ``import_account`` is called with the games a source returned and whether that list is COMPLETE
  (``FetchResult.complete``). ``run_import`` forwards it: a source that fails or cannot tell if it
  saw everything raises, and nothing is written.
- An ownership record of that account that is absent from a complete fetch is marked ``removed``
  and keeps its old ``last_seen``. An incomplete fetch (for example local-only Steam data) adds and
  updates games but removes nothing. Records of other accounts are never touched.
- Ownership rows and games are never deleted.
- A removed record that appears in a later fetch is restored (``removed`` cleared) and keeps its
  game, so game-level data is untouched.
- The whole import is one transaction; any error rolls back to the last good state.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .errors import LudexError
from .plugins import FetchResult, OwnedGame, SourcePlugin
from .storage import normalize_title, utc_now

_MAX_LIMIT = 500


@dataclass(frozen=True, slots=True)
class ImportSummary:
    added: int
    restored: int
    removed: int
    total: int
    complete: bool = True
    mode: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "added": self.added,
            "restored": self.restored,
            "removed": self.removed,
            "total": self.total,
            "complete": self.complete,
            "mode": self.mode,
        }


def _raw_json(extra: Mapping[str, Any]) -> str:
    return json.dumps({"extra": dict(extra)}, sort_keys=True, ensure_ascii=False, default=str)


def import_account(
    conn: sqlite3.Connection, account: str, games: Sequence[OwnedGame], *, complete: bool = True
) -> ImportSummary:
    fetched = {(game.store, game.store_id): game for game in games}
    now = utc_now()
    added = restored = removed = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = {
            (row["store"], row["store_id"]): row
            for row in conn.execute(
                "SELECT id, store, store_id, removed FROM ownership WHERE account = ?", (account,)
            )
        }
        for key, game in fetched.items():
            raw = _raw_json(game.extra)
            row = existing.get(key)
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO games(title, normalized_title, created_at) VALUES (?, ?, ?)",
                    (game.title, normalize_title(game.title), now),
                )
                conn.execute(
                    "INSERT INTO ownership(game_id, store, store_id, account, title, raw_json, "
                    "first_seen, last_seen, removed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (cursor.lastrowid, game.store, game.store_id, account, game.title, raw, now, now),
                )
                added += 1
                continue
            conn.execute(
                "UPDATE ownership SET title = ?, raw_json = ?, last_seen = ?, removed = 0 WHERE id = ?",
                (game.title, raw, now, row["id"]),
            )
            if row["removed"]:
                restored += 1
        for key, row in existing.items():
            if complete and key not in fetched and not row["removed"]:
                conn.execute("UPDATE ownership SET removed = 1 WHERE id = ?", (row["id"],))
                removed += 1
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return ImportSummary(added=added, restored=restored, removed=removed, total=len(fetched), complete=complete)


def run_import(
    conn: sqlite3.Connection, account: str, plugin: SourcePlugin, config: Mapping[str, str]
) -> ImportSummary:
    try:
        result = plugin.fetch(config)
        if not isinstance(result, FetchResult) or not isinstance(result.complete, bool):
            raise LudexError("source_failed", f"source {plugin.name} returned an invalid fetch result")
        items = list(result.games)
    except LudexError:
        raise
    except Exception as exc:
        raise LudexError("source_failed", f"source {plugin.name} failed ({type(exc).__name__})") from None
    for item in items:
        if not (
            isinstance(item, OwnedGame)
            and all(isinstance(value, str) and value for value in (item.store, item.store_id, item.title))
        ):
            raise LudexError("source_failed", f"source {plugin.name} returned an invalid game record")
    return replace(import_account(conn, account, items, complete=result.complete), mode=result.mode)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_games(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    store: str | None = None,
    account: str | None = None,
    include_removed: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if not 1 <= limit <= _MAX_LIMIT:
        raise LudexError("invalid_pagination", f"limit must be between 1 and {_MAX_LIMIT}")
    if offset < 0:
        raise LudexError("invalid_pagination", "offset must be 0 or greater")
    own_clauses = ["o.game_id = g.id"]
    params: list[Any] = []
    if not include_removed:
        own_clauses.append("o.removed = 0")
    if store is not None:
        own_clauses.append("o.store = ?")
        params.append(store)
    if account is not None:
        own_clauses.append("o.account = ?")
        params.append(account)
    where = [f"EXISTS (SELECT 1 FROM ownership o WHERE {' AND '.join(own_clauses)})"]
    if query is not None:
        where.append("g.normalized_title LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(normalize_title(query))}%")
    rows = conn.execute(
        f"SELECT g.id, g.title FROM games g WHERE {' AND '.join(where)} "
        "ORDER BY g.normalized_title, g.id LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    result = []
    for row in rows:
        owned = conn.execute(
            "SELECT store, account, removed FROM ownership WHERE game_id = ?", (row["id"],)
        ).fetchall()
        result.append(
            {
                "id": row["id"],
                "title": row["title"],
                "stores": sorted({o["store"] for o in owned}),
                "accounts": sorted({o["account"] for o in owned}),
                "removed": all(o["removed"] for o in owned),
            }
        )
    return result


def get_game(conn: sqlite3.Connection, game_id: int) -> dict[str, Any]:
    game = conn.execute("SELECT id, title, created_at FROM games WHERE id = ?", (game_id,)).fetchone()
    if game is None:
        raise LudexError("game_not_found", f"no game with id {game_id}")
    ownership = conn.execute(
        "SELECT id, store, store_id, account, title, first_seen, last_seen, removed "
        "FROM ownership WHERE game_id = ? ORDER BY id",
        (game_id,),
    ).fetchall()
    return {
        "id": game["id"],
        "title": game["title"],
        "created_at": game["created_at"],
        "ownership": [{**dict(o), "removed": bool(o["removed"])} for o in ownership],
    }
