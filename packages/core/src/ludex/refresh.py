"""Import every account again (what ``ludex import --all`` does), for callers that want the outcome per account."""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from .accounts import get_account, list_accounts
from .library import run_import
from .metadata import merge_matched
from .paths import StatePaths
from .plugins import Provider


@dataclass(frozen=True, slots=True)
class Refreshed:
    ref: str  # source:account
    added: int = 0
    restored: int = 0
    removed: int = 0
    error: str | None = None  # a fixed, secret-free reason


def refresh_all(paths: StatePaths, conn: sqlite3.Connection, providers: Mapping[str, Provider]) -> list[Refreshed]:
    """Import each account in turn; one that fails is reported and the rest still run. The caller holds the writer lock."""
    results = []
    for name, source in list_accounts(paths):
        ref = f"{source}:{name}"
        provider = providers.get(source)
        if provider is None:
            results.append(Refreshed(ref, error=f"plugin {source} is not loaded"))
            continue
        try:
            summary = run_import(conn, name, provider, get_account(paths, ref).config)
        except Exception as exc:  # a broken plugin or account must not stop the others
            results.append(Refreshed(ref, error=getattr(exc, "message", f"failed ({type(exc).__name__})")))
            continue
        results.append(Refreshed(ref, summary.added, summary.restored, summary.removed))
    merge_matched(conn)  # new copies may share a database entry with a game already matched
    return results


def get_auto_refresh(conn: sqlite3.Connection) -> bool:
    """Whether the TUI imports every account when it starts (default yes)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'auto_refresh'").fetchone()
    return row is None or row["value"] != "0"


def set_auto_refresh(conn: sqlite3.Connection, on: bool | None) -> None:
    """Turn it on or off; ``None`` goes back to the default (on)."""
    with conn:
        if on is None or on:
            conn.execute("DELETE FROM meta WHERE key = 'auto_refresh'")
        else:
            conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('auto_refresh', '0')")
