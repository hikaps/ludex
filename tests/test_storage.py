from __future__ import annotations

import pytest

from ludex.errors import LudexError
from ludex.storage import SCHEMA_VERSION, connect, normalize_title, utc_now, writer_lock


def test_fresh_database_has_schema_version_and_wal(tmp_path):
    conn = connect(tmp_path / "db.sqlite3")
    version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
    assert version == str(SCHEMA_VERSION)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_reopen_keeps_data(tmp_path):
    path = tmp_path / "db.sqlite3"
    conn = connect(path)
    conn.execute("INSERT INTO games(title, normalized_title, created_at) VALUES ('A', 'a', ?)", (utc_now(),))
    conn.close()
    conn = connect(path)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 1
    conn.close()


def test_refuses_newer_schema(tmp_path):
    path = tmp_path / "db.sqlite3"
    conn = connect(path)
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.close()
    with pytest.raises(LudexError) as info:
        connect(path)
    assert info.value.code == "schema_too_new"


def test_utc_now_format():
    stamp = utc_now()
    assert stamp.endswith("Z") and "+" not in stamp and len(stamp) == len("2026-01-01T00:00:00Z")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Café", "cafe"),
        ("  THE   Witcher 3: Wild Hunt!  ", "the witcher 3 wild hunt"),
        ("Pokémon™ — Red/Blue", "pokemontm red blue"),
        ("ＡＢＣ", "abc"),
        ("snake_case-name", "snake case name"),
        ("!!!", ""),
        ("Ünïcödé", "unicode"),
    ],
)
def test_normalize_title(title, expected):
    assert normalize_title(title) == expected


def test_writer_lock_contention_and_release(tmp_path):
    lock = tmp_path / "import.lock"
    with writer_lock(lock):
        with pytest.raises(LudexError) as info:
            with writer_lock(lock):
                pass
        assert info.value.code == "import_in_progress"
    with writer_lock(lock):
        pass


def test_writer_lock_released_after_exception(tmp_path):
    lock = tmp_path / "import.lock"
    with pytest.raises(RuntimeError):
        with writer_lock(lock):
            raise RuntimeError("boom")
    with writer_lock(lock):
        pass
    assert (lock.stat().st_mode & 0o777) == 0o600


def test_older_databases_are_migrated_step_by_step(tmp_path):
    import sqlite3
    from ludex import storage

    path = tmp_path / "old.sqlite3"
    raw = sqlite3.connect(path)
    for statement in storage._SCHEMA_V1:
        raw.execute(statement)
    raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '1')")
    raw.commit()
    raw.close()
    conn = storage.connect(path)
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(storage.SCHEMA_VERSION)
    assert conn.execute("SELECT COUNT(*) FROM review_queue").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM game_settings").fetchone()[0] == 0
    conn.close()

    raw = sqlite3.connect(tmp_path / "v2.sqlite3")  # a v2 database only gains the settings table
    for statement in storage._SCHEMA_V1 + storage._SCHEMA_V2:
        raw.execute(statement)
    raw.execute("INSERT INTO meta(key, value) VALUES ('schema_version', '2')")
    raw.commit()
    raw.close()
    conn = storage.connect(tmp_path / "v2.sqlite3")
    assert conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == "3"
    assert conn.execute("SELECT COUNT(*) FROM game_settings").fetchone()[0] == 0
    conn.close()
