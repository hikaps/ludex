"""Per-game launch settings (runner, prefix, executable, arguments, environment).

Keyed by (store, store_id) so imports never touch them; they are deleted only when the last
ownership record of that game copy is deleted (``library.delete_account_records``).
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .errors import LudexError
from .library import get_game
from .runners import resolve_runner

_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


@dataclass(frozen=True, slots=True)
class GameSettings:
    runner: str | None = None
    prefix: str | None = None
    executable: str | None = None
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {"runner": self.runner, "prefix": self.prefix, "executable": self.executable, "args": list(self.args), "env": dict(self.env)}


def get_settings(conn: sqlite3.Connection, store: str, store_id: str) -> GameSettings:
    row = conn.execute("SELECT * FROM game_settings WHERE store = ? AND store_id = ?", (store, store_id)).fetchone()
    if row is None:
        return GameSettings()
    return GameSettings(row["runner"], row["prefix"], row["executable"], tuple(json.loads(row["args_json"])), json.loads(row["env_json"]))


def pick_copy(conn: sqlite3.Connection, game_id: int, store: str | None = None) -> tuple[str, str]:
    """The (store, store_id) of the game's one owned copy, or the one in ``store``."""
    copies = sorted(
        {(o["store"], o["store_id"]) for o in get_game(conn, game_id)["ownership"] if not o["removed"]}
    )
    if store is not None:
        copies = [c for c in copies if c[0] == store]
    if not copies:
        raise LudexError("not_owned", f"game {game_id} has no owned copy" + (f" in {store}" if store else ""))
    if len(copies) > 1:
        raise LudexError("copy_ambiguous", f"game {game_id} has copies in {', '.join(sorted({c[0] for c in copies}))}; pass --store")
    return copies[0]


def _clean(value: str, what: str) -> str:
    if "\0" in value or not value.strip():
        raise LudexError("invalid_setting", f"{what} must be non-empty text without NUL")
    return value


def update_settings(
    conn: sqlite3.Connection,
    store: str,
    store_id: str,
    *,
    runner: str | None = None,
    prefix: str | None = None,
    executable: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    unset_env: list[str] = (),
    clear: bool = False,
) -> GameSettings:
    """Change the given settings (``None`` leaves one alone); ``clear`` first resets everything."""
    current = GameSettings() if clear else get_settings(conn, store, store_id)
    if runner is not None:
        found = resolve_runner(_clean(runner, "runner"))
        runner = str(found.path) if found.origin == "path" else found.name
    if prefix is not None:
        prefix = str(Path(_clean(prefix, "prefix")).expanduser())
        if not Path(prefix).is_absolute():
            raise LudexError("invalid_setting", "prefix must be an absolute path")
    merged_env = {k: v for k, v in current.env.items() if k not in set(unset_env)}
    for key, value in (env or {}).items():
        if not _ENV_NAME.match(key) or "\0" in value:
            raise LudexError("invalid_setting", f"invalid environment variable {key!r}")
        merged_env[key] = value
    result = GameSettings(
        runner if runner is not None else current.runner,
        prefix if prefix is not None else current.prefix,
        _clean(executable, "executable") if executable is not None else current.executable,
        tuple(_clean(a, "argument") for a in args) if args is not None else current.args,
        merged_env,
    )
    with conn:
        conn.execute(
            "INSERT INTO game_settings(store, store_id, runner, prefix, executable, args_json, env_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(store, store_id) DO UPDATE SET runner = excluded.runner, "
            "prefix = excluded.prefix, executable = excluded.executable, args_json = excluded.args_json, "
            "env_json = excluded.env_json",
            (store, store_id, result.runner, result.prefix, result.executable, json.dumps(list(result.args)), json.dumps(result.env)),
        )
    return result


def get_prefix_root(conn: sqlite3.Connection, default: Path) -> Path:
    """The folder default Wine prefixes are created in (a setting, else ``default``)."""
    row = conn.execute("SELECT value FROM meta WHERE key = 'prefix_dir'").fetchone()
    return Path(row["value"]) if row else default


def set_prefix_root(conn: sqlite3.Connection, path: str | None) -> None:
    """Set the default prefix folder; ``None`` goes back to the built-in one."""
    with conn:
        if path is None:
            conn.execute("DELETE FROM meta WHERE key = 'prefix_dir'")
            return
        folder = Path(_clean(path, "prefix folder")).expanduser()
        if not folder.is_absolute():
            raise LudexError("invalid_setting", "the prefix folder must be an absolute path")
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('prefix_dir', ?)", (str(folder),))
