"""Yes/no settings that add or remove a built-in local source.

Turning one on adds an auto-detecting account named ``default`` and imports it (nothing is left
behind if the import fails). Turning one off removes every account of that source and deletes its
games from the library, exactly like ``ludex account rm``; turning it on again brings them back.
The caller holds the writer lock.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Mapping

from .accounts import add_account, list_accounts, remove_account
from .errors import LudexError
from .library import delete_account_records, run_import
from .paths import StatePaths
from .plugins import Provider

SWITCHES = {"steam_shortcuts": "shortcuts", "heroic_sideload": "heroic"}


def _source(key: str) -> str:
    if key not in SWITCHES:
        raise LudexError("invalid_setting", f"unknown setting {key}")
    return SWITCHES[key]


def get_switch(paths: StatePaths, key: str) -> bool:
    source = _source(key)
    return any(s == source for _, s in list_accounts(paths))


def set_switch(paths: StatePaths, conn: sqlite3.Connection, providers: Mapping[str, Provider], key: str, on: bool) -> int:
    """Apply the switch; returns games imported (on) or ownership records deleted (off)."""
    source = _source(key)
    names = [n for n, s in list_accounts(paths) if s == source]
    if on:
        if names:
            return 0
        plugin = providers.get(source)
        if plugin is None:
            raise LudexError("unknown_source", f"provider {source} is not available")
        add_account(paths, "default", source, {})
        try:
            return run_import(conn, "default", plugin, {}).total
        except LudexError:
            remove_account(paths, f"{source}:default")
            delete_account_records(conn, "default", store=source)
            raise
    deleted = 0
    for name in names:
        remove_account(paths, f"{source}:{name}")
        deleted += delete_account_records(conn, name, store=source)
    return deleted
