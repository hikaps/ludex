"""SQLite storage: connection setup, schema v1, title normalization and the writer lock."""
from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .errors import LudexError

SCHEMA_VERSION = 5

_SCHEMA_V1 = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT NOT NULL, "
    "normalized_title TEXT NOT NULL, created_at TEXT NOT NULL)",
    "CREATE INDEX games_normalized_title_idx ON games(normalized_title)",
    "CREATE TABLE ownership (id INTEGER PRIMARY KEY, "
    "game_id INTEGER NOT NULL REFERENCES games(id), "
    "store TEXT NOT NULL, store_id TEXT NOT NULL, account TEXT NOT NULL, title TEXT NOT NULL, "
    "raw_json TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, "
    "removed INTEGER NOT NULL DEFAULT 0 CHECK(removed IN (0,1)), "
    "UNIQUE(store, store_id, account))",
    "CREATE INDEX ownership_game_idx ON ownership(game_id)",
)

_SCHEMA_V2 = (
    "CREATE TABLE review_queue (id INTEGER PRIMARY KEY, "
    "ownership_id INTEGER NOT NULL UNIQUE REFERENCES ownership(id), candidates_json TEXT NOT NULL)",
)

_SCHEMA_V3 = (
    "CREATE TABLE game_settings (store TEXT NOT NULL, store_id TEXT NOT NULL, runner TEXT, prefix TEXT, "
    "executable TEXT, args_json TEXT NOT NULL DEFAULT '[]', env_json TEXT NOT NULL DEFAULT '{}', "
    "PRIMARY KEY(store, store_id))",
)
_SCHEMA_V4 = (
    "CREATE TABLE game_metadata (store TEXT NOT NULL, store_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (store, store_id))",
)
_SCHEMA_V5 = (
    "CREATE TABLE jobs (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, game_id INTEGER NOT NULL, target TEXT NOT NULL, "
    "title TEXT NOT NULL, pid INTEGER NOT NULL, pid_start TEXT NOT NULL, log TEXT NOT NULL, exit_file TEXT NOT NULL, "
    "started_at TEXT NOT NULL, ended_at TEXT, exit_code INTEGER, "
    "state TEXT NOT NULL CHECK(state IN ('running','done','failed','stopped','lost')))",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_title(title: str) -> str:
    decomposed = unicodedata.normalize("NFKD", title)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[\W_]+", " ", stripped.casefold()).strip()


def _enable_wal(connection: sqlite3.Connection) -> None:
    deadline = time.monotonic() + 5.0
    while True:
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            return
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                raise
            time.sleep(0.05)


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        has_meta = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
        ).fetchone()
        if has_meta is None:
            for statement in _SCHEMA_V1 + _SCHEMA_V2 + _SCHEMA_V3 + _SCHEMA_V4 + _SCHEMA_V5:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO meta(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
            )
        else:
            row = connection.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            try:
                stored = int(row["value"])
            except (TypeError, ValueError):
                raise LudexError("schema_invalid", "database has no valid schema version") from None
            if stored > SCHEMA_VERSION:
                raise LudexError(
                    "schema_too_new",
                    f"database schema {stored} is newer than supported version {SCHEMA_VERSION}",
                )
            for version, statements in ((2, _SCHEMA_V2), (3, _SCHEMA_V3), (4, _SCHEMA_V4), (5, _SCHEMA_V5)):
                if stored < version:
                    for statement in statements:
                        connection.execute(statement)
                    connection.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(version),))
        connection.execute("COMMIT")
    except BaseException:
        connection.execute("ROLLBACK")
        raise


def connect(database: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        _enable_wal(connection)
        _initialize(connection)
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def writer_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive non-blocking lock so only one import writes at a time."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LudexError("import_in_progress", "another import is already running") from None
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)
