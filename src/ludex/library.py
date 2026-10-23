"""Import and query the library of owned games.

Removal policy (source of truth):

- ``import_account`` is called with the games a source returned and whether that list is COMPLETE
  (``FetchResult.complete``). ``run_import`` forwards it: a source that fails or cannot tell if it
  saw everything raises, and nothing is written.
- An ownership record of that account that is absent from a complete fetch is marked ``removed``
  and keeps its old ``last_seen``. An incomplete fetch (for example local-only Steam data) adds and
  updates games but removes nothing. Records of other accounts are never touched.
- Removal is scoped to one account of one source: a source's games must carry its own name as
  ``store``, and only records with that store are compared (account names repeat across sources).
- Imports and merges never delete ownership rows or games; the only deletion is
  ``delete_account_records``, run when a user removes an account. ``merge_games`` moves ownership to the kept game and
  leaves the emptied game row behind; a game with no ownership is not listed.
- Matching applies only when an ownership record is first created (existing records keep their
  game, so manual merges survive re-imports). The same (store, store_id) under another account
  joins that game. Otherwise a single existing game with the same normalized title and no
  ownership in the same store is joined. Any other title match is never auto-merged: the new game
  stays separate and is queued in ``review_queue`` with its candidate games.
- A removed record that appears in a later fetch is restored (``removed`` cleared) and keeps its
  game, so game-level data is untouched.
- The whole import is one transaction; any error rolls back to the last good state.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from .errors import LudexError
from .plugins import FetchResult, OwnedGame, Provider
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


def _match(conn: sqlite3.Connection, game: OwnedGame) -> tuple[int | None, list[int]]:
    same = conn.execute(
        "SELECT game_id FROM ownership WHERE store = ? AND store_id = ? ORDER BY game_id LIMIT 1",
        (game.store, game.store_id),
    ).fetchone()
    if same is not None:
        return same["game_id"], []
    normalized = normalize_title(game.title)
    if not normalized:
        return None, []
    candidates = [
        row["id"]
        for row in conn.execute("SELECT id FROM games WHERE normalized_title = ? ORDER BY id", (normalized,))
    ]
    if len(candidates) == 1 and not conn.execute(
        "SELECT 1 FROM ownership WHERE game_id = ? AND store = ?", (candidates[0], game.store)
    ).fetchone():
        return candidates[0], []
    return None, candidates


def import_account(
    conn: sqlite3.Connection,
    account: str,
    games: Sequence[OwnedGame],
    *,
    complete: bool = True,
    store: str | None = None,
) -> ImportSummary:
    fetched = {(game.store, game.store_id): game for game in games}
    now = utc_now()
    added = restored = removed = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        # account names are only unique per source, so removal must stay inside the source's store
        existing = {
            (row["store"], row["store_id"]): row
            for row in conn.execute(
                "SELECT id, store, store_id, removed FROM ownership WHERE account = ? AND (? IS NULL OR store = ?)",
                (account, store, store),
            )
        }
        for key, game in fetched.items():
            raw = _raw_json(game.extra)
            row = existing.get(key)
            if row is None:
                game_id, candidates = _match(conn, game)
                if game_id is None:
                    game_id = conn.execute(
                        "INSERT INTO games(title, normalized_title, created_at) VALUES (?, ?, ?)",
                        (game.title, normalize_title(game.title), now),
                    ).lastrowid
                ownership_id = conn.execute(
                    "INSERT INTO ownership(game_id, store, store_id, account, title, raw_json, "
                    "first_seen, last_seen, removed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
                    (game_id, game.store, game.store_id, account, game.title, raw, now, now),
                ).lastrowid
                if candidates:
                    conn.execute(
                        "INSERT INTO review_queue(ownership_id, candidates_json) VALUES (?, ?)",
                        (ownership_id, json.dumps(candidates)),
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
    conn: sqlite3.Connection, account: str, plugin: Provider, config: Mapping[str, str]
) -> ImportSummary:
    if plugin.fetch is None:
        raise LudexError("no_owned_capability", f"provider {plugin.name} cannot list owned games")
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
        ) or item.store != plugin.name:
            raise LudexError("source_failed", f"source {plugin.name} returned an invalid game record")
    summary = import_account(conn, account, items, complete=result.complete, store=plugin.name)
    return replace(summary, mode=result.mode)


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_games(
    conn: sqlite3.Connection,
    *,
    query: str | None = None,
    store: str | None = None,
    account: str | None = None,
    include_removed: bool = False,
    only: Collection[tuple[str, str]] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """``only``: restrict to games owning one of these (store, store_id) pairs."""
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
    if only is not None:
        # ponytail: one bound parameter per pair, fine for an installed list; use a temp table if it grows large
        own_clauses.append(f"(o.store || char(31) || o.store_id) IN ({','.join('?' * len(only)) or 'NULL'})")
        params.extend(f"{store}\x1f{store_id}" for store, store_id in only)
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


def list_review(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    items = []
    for row in conn.execute(
        "SELECT q.id, q.candidates_json, o.store, o.account, o.title, o.game_id "
        "FROM review_queue q JOIN ownership o ON o.id = q.ownership_id ORDER BY q.id"
    ):
        candidates = [
            {"id": g["id"], "title": g["title"]}
            for g in (
                conn.execute(
                    "SELECT g.id, g.title FROM games g WHERE g.id = ? "
                    "AND EXISTS (SELECT 1 FROM ownership WHERE game_id = g.id)",
                    (game_id,),
                ).fetchone()
                for game_id in json.loads(row["candidates_json"])
            )
            if g is not None
        ]
        if candidates:
            items.append(
                {
                    "id": row["id"],
                    "game_id": row["game_id"],
                    "store": row["store"],
                    "account": row["account"],
                    "title": row["title"],
                    "candidates": candidates,
                }
            )
    return items


def dismiss_review(conn: sqlite3.Connection, review_id: int) -> None:
    if conn.execute("DELETE FROM review_queue WHERE id = ?", (review_id,)).rowcount == 0:
        raise LudexError("review_not_found", f"no review item with id {review_id}")


def merge_games(conn: sqlite3.Connection, keep: int, drop: int) -> int:
    """Move every ownership record of game ``drop`` to ``keep``; returns how many moved."""
    if keep == drop:
        raise LudexError("invalid_merge", "cannot merge a game into itself")
    for game_id in (keep, drop):
        if conn.execute("SELECT 1 FROM games WHERE id = ?", (game_id,)).fetchone() is None:
            raise LudexError("game_not_found", f"no game with id {game_id}")
    conn.execute("BEGIN IMMEDIATE")
    try:
        moved = conn.execute("UPDATE ownership SET game_id = ? WHERE game_id = ?", (keep, drop)).rowcount
        for row in conn.execute(
            "SELECT q.id, q.candidates_json FROM review_queue q JOIN ownership o ON o.id = q.ownership_id "
            "WHERE o.game_id = ?",
            (keep,),
        ).fetchall():
            if {keep, drop} & set(json.loads(row["candidates_json"])):
                conn.execute("DELETE FROM review_queue WHERE id = ?", (row["id"],))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    return moved


def export_games(conn: sqlite3.Connection, *, include_removed: bool = False) -> list[dict[str, Any]]:
    """Every listed game with its ownership records (no raw store data), ordered by game id."""
    games: dict[int, dict[str, Any]] = {}
    for row in conn.execute(
        "SELECT g.id AS game_id, g.title AS game_title, o.store, o.store_id, o.account, o.title, "
        "o.removed, o.first_seen, o.last_seen FROM games g JOIN ownership o ON o.game_id = g.id "
        "WHERE (? OR o.removed = 0) ORDER BY g.id, o.id",
        (int(include_removed),),
    ):
        entry = games.setdefault(row["game_id"], {"id": row["game_id"], "title": row["game_title"], "ownership": []})
        entry["ownership"].append(
            {
                "store": row["store"],
                "store_id": row["store_id"],
                "account": row["account"],
                "title": row["title"],
                "removed": bool(row["removed"]),
                "first_seen": row["first_seen"],
                "last_seen": row["last_seen"],
            }
        )
    return list(games.values())


def delete_account_records(
    conn: sqlite3.Connection, account: str, *, store: str | None = None, keep_stores: Sequence[str] = ()
) -> int:
    """Delete an account's ownership records, including ones already marked removed.

    ``store`` limits it to one source; ``keep_stores`` spares stores where the same account name is
    still configured. Games stay (a game left without ownership is simply not listed). Returns how
    many records were deleted.
    """
    where = "account = ? AND (? IS NULL OR store = ?)" + (
        f" AND store NOT IN ({','.join('?' * len(keep_stores))})" if keep_stores else ""
    )
    params = (account, store, store, *keep_stores)
    with conn:
        conn.execute(f"DELETE FROM review_queue WHERE ownership_id IN (SELECT id FROM ownership WHERE {where})", params)
        cursor = conn.execute(f"DELETE FROM ownership WHERE {where}", params)
        conn.execute(
            "DELETE FROM game_settings WHERE NOT EXISTS (SELECT 1 FROM ownership o "
            "WHERE o.store = game_settings.store AND o.store_id = game_settings.store_id)"
        )
    return cursor.rowcount


def resolve_game(conn: sqlite3.Connection, ref: str) -> int:
    """A game id (digits) or a title: an exact title match, else the only partial match."""
    if ref.isdigit():
        return int(ref)
    matches = list_games(conn, query=ref, limit=_MAX_LIMIT)
    exact = [g for g in matches if normalize_title(g["title"]) == normalize_title(ref)]
    found = exact if len(exact) == 1 else matches
    if not found:
        raise LudexError("game_not_found", f"no game matches {ref!r}")
    if len(found) > 1:
        shown = "; ".join(f"{g['id']} {g['title']}" for g in found[:5]) + ("; ..." if len(found) > 5 else "")
        raise LudexError("game_ambiguous", f"{len(found)} games match {ref!r}, use an id: {shown}")
    return found[0]["id"]
