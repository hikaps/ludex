"""Which games are running now, for the stores whose provider can tell.

Read live from the provider's ``running`` (see ``ludex.plugins``), never stored. A game runs when one of
its owned copies does; a provider that fails or cannot tell is skipped (a game it would have named
shows as not running). Games ludex started itself are ``play`` jobs (``ludex.jobs``), not this.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .accounts import get_account, list_accounts
from .paths import StatePaths
from .plugins import Provider


def running_games(paths: StatePaths, providers: Mapping[str, Provider], conn: sqlite3.Connection) -> set[int]:
    """The ids of the games with a copy that its store's client has running."""
    live: set[tuple[str, str]] = set()
    for name, source in list_accounts(paths):
        provider = providers.get(source)
        if provider is None or provider.running is None:
            continue
        try:
            live.update((source, str(store_id)) for store_id in provider.running(get_account(paths, f"{source}:{name}").config))
        except Exception:  # a client that cannot be read is simply not seen running
            continue
    if not live:
        return set()
    return {row["game_id"] for row in conn.execute("SELECT game_id, store, store_id FROM ownership WHERE removed = 0") if (row["store"], row["store_id"]) in live}
