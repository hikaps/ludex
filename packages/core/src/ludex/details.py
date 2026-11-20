"""Fetch the details of every game that has none yet (the stores or database plugins see each game's id or title)."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .errors import LudexError
from .metadata import game_metadata
from .paths import StatePaths
from .plugins import Provider
from .storage import writer_lock


@dataclass(frozen=True, slots=True)
class DetailsSummary:
    fetched: int = 0  # games that now have details
    unavailable: int = 0  # no plugin supplies details for them, or it had none
    failed: int = 0  # a plugin raised; the rest still ran
    stopped: bool = False  # the caller asked to stop; run again to continue

    def as_dict(self) -> dict[str, object]:
        return {"fetched": self.fetched, "unavailable": self.unavailable, "failed": self.failed, "stopped": self.stopped}


def games_without_details(conn: sqlite3.Connection) -> list[int]:
    """Ids of owned games none of whose copies has cached details, in id order."""
    rows = conn.execute(
        "SELECT g.id FROM games g WHERE EXISTS (SELECT 1 FROM ownership o WHERE o.game_id = g.id AND o.removed = 0) "
        "AND NOT EXISTS (SELECT 1 FROM ownership o JOIN game_metadata m ON m.store = o.store AND m.store_id = o.store_id "
        "WHERE o.game_id = g.id) ORDER BY g.id"
    ).fetchall()
    return [row["id"] for row in rows]


def fetch_missing_details(
    paths: StatePaths,
    conn: sqlite3.Connection,
    sources: Mapping[str, Provider],
    *,
    match: bool = False,
    report: Callable[[int, int], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> DetailsSummary:
    """Ask for each missing game's details in turn (network inside the plugins). The writer lock is held per game, not throughout.

    ``report(done, total)`` runs after each game; one game's failure never stops the rest. ponytail: sequential on
    purpose, so a plugin's own rate limit is never exceeded; a large library takes minutes.
    """
    wanted = games_without_details(conn)
    fetched = unavailable = failed = 0
    for done, game_id in enumerate(wanted, 1):
        if should_stop is not None and should_stop():
            return DetailsSummary(fetched, unavailable, failed, True)
        try:
            with writer_lock(paths.import_lock):
                found = game_metadata(conn, sources, game_id, False, match)
        except LudexError as exc:
            if exc.code == "metadata_unavailable":
                unavailable += 1
            else:
                failed += 1
        except Exception:  # a broken plugin must not stop the rest
            failed += 1
        else:
            if found is None:
                unavailable += 1
            else:
                fetched += 1
        if report is not None:
            report(done, len(wanted))
    return DetailsSummary(fetched, unavailable, failed)
