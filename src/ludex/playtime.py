"""How long each game has been played, and when it was last played.

Two sources, never added together for one store. A provider that declares ``playtime`` is trusted for its
own games: Steam and Heroic record play themselves, also when a game is started outside ludex. For a
provider without it, the sessions ludex timed itself (``play`` jobs, see ``ludex.jobs``) count. A game's
figure is the sum over its owned copies. Read live, never stored.
ponytail: if two accounts of one store report the same game, the larger figure wins (the usual cause is two
accounts pointing at one folder; a shared game played by both is under-counted). Sessions are wall-clock time,
suspend included.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from .accounts import get_account, list_accounts
from .jobs import finished_plays
from .paths import StatePaths
from .plugins import PlayRecord, Provider


@dataclass(frozen=True, slots=True)
class Played:
    minutes: int
    last_played: str | None  # ISO 8601 UTC


def epoch(text: str) -> int:
    return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())


def play_stats(paths: StatePaths, providers: Mapping[str, Provider], conn: sqlite3.Connection) -> tuple[dict[int, Played], dict[str, str]]:
    """Return ``({game id: Played}, {account ref: reason})``; a failing account is reported and skipped."""
    problems: dict[str, str] = {}
    reported: dict[tuple[str, str], PlayRecord] = {}
    for name, source in list_accounts(paths):
        provider = providers.get(source)
        if provider is None or provider.playtime is None:
            continue
        ref = f"{source}:{name}"
        try:
            records = provider.playtime(get_account(paths, ref).config)
        except Exception as exc:
            problems[ref] = getattr(exc, "message", f"failed ({type(exc).__name__})")
            continue
        for store_id, record in records.items():
            key = (source, str(store_id))
            if key not in reported or record.minutes > reported[key].minutes:
                reported[key] = record
    seconds: dict[int, int] = {}
    last: dict[int, str] = {}

    def note(game_id: int, when: str | None) -> None:
        if when and (game_id not in last or epoch(when) > epoch(last[game_id])):
            last[game_id] = when

    minutes: dict[int, int] = {}
    for row in conn.execute("SELECT game_id, store, store_id FROM ownership").fetchall():
        record = reported.get((row["store"], row["store_id"]))
        if record is not None:
            minutes[row["game_id"]] = minutes.get(row["game_id"], 0) + record.minutes
            note(row["game_id"], record.last_played)
    for game_id, target, spent, ended in finished_plays(conn):
        provider = providers.get(target.partition(":")[0])
        if provider is not None and provider.playtime is not None:
            continue  # that store keeps its own record; adding ours would count the session twice
        seconds[game_id] = seconds.get(game_id, 0) + spent
        note(game_id, ended)
    stats = {g: Played(minutes.get(g, 0) + seconds.get(g, 0) // 60, last.get(g)) for g in {*minutes, *seconds, *last}}
    return stats, problems


def format_minutes(minutes: int) -> str:
    return "<1m" if minutes < 1 else f"{minutes}m" if minutes < 60 else f"{minutes // 60}h {minutes % 60:02d}m"


def describe_played(played: Played | None) -> str:
    """``12h 05m, last 2026-11-08``, or ``never`` for a game with no record."""
    if played is None or (played.minutes == 0 and played.last_played is None):
        return "never"
    last = f", last {played.last_played[:10]}" if played.last_played else ""
    return f"{format_minutes(played.minutes)}{last}"
