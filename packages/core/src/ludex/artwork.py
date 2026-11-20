"""Cover art for graphical frontends: ask the plugins that offer ``cover`` and keep the image locally.

The core never fetches an image itself (the network belongs to plugins, see ``ludex.plugins``). It
accepts only bytes that are at most ``MAX_COVER_BYTES`` long and start with a PNG, JPEG or WebP
signature, never decodes them, and keeps one private file per cover under ``<state>/covers``.
A plugin that has no cover for a game is not asked again for a week.
"""
from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path

from .errors import LudexError
from .library import get_game
from .metadata import cached_match
from .paths import StatePaths
from .plugins import MAX_COVER_BYTES, Provider
from .private_io import atomic_write_private

_RETRY_AFTER_SECONDS = 7 * 24 * 3600


def _is_image(data: object) -> bool:
    if not isinstance(data, bytes) or not 12 <= len(data) <= MAX_COVER_BYTES:
        return False
    return data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")


def _candidates(conn: sqlite3.Connection, game_id: int) -> list[tuple[str, str]]:
    """``(provider key, store id)`` that may hold the cover: each copy you own, then the title match its metadata kept."""
    found: list[tuple[str, str]] = []
    for copy in (o for o in get_game(conn, game_id)["ownership"] if not o["removed"]):
        store, store_id = copy["store"], str(copy["store_id"])
        found.append((store, store_id))
        matched = cached_match(conn, store, store_id)
        if matched and matched["id"]:
            found.append((matched["plugin"], matched["id"]))
    return found


def _file(paths: StatePaths, key: str, store_id: str) -> Path:
    return paths.root / "covers" / hashlib.sha256(f"{key}\0{store_id}".encode()).hexdigest()[:40]


def cached_cover(paths: StatePaths, conn: sqlite3.Connection, game_id: int) -> Path | None:
    """The game's cover file (PNG, JPEG or WebP) when one is kept locally; no network."""
    for key, store_id in _candidates(conn, game_id):
        file = _file(paths, key, store_id)
        if file.is_file():
            return file
    return None


def fetch_cover(paths: StatePaths, conn: sqlite3.Connection, sources: Mapping[str, Provider], game_id: int) -> Path | None:
    """``cached_cover``, else ask the plugins that offer ``cover`` (network, inside the plugin) and keep the answer.

    Returns ``None`` when no plugin has a cover (remembered for a week). A plugin failure is raised
    as ``LudexError`` only when no other plugin supplied one; nothing is remembered about failures.
    """
    existing = cached_cover(paths, conn, game_id)
    if existing is not None:
        return existing
    failure: LudexError | None = None
    for key, store_id in _candidates(conn, game_id):
        provider = sources.get(key)
        if provider is None or provider.cover is None:
            continue
        file = _file(paths, key, store_id)
        miss = file.with_suffix(".none")
        try:
            if time.time() - miss.stat().st_mtime < _RETRY_AFTER_SECONDS:
                continue
        except FileNotFoundError:
            pass
        try:
            data = provider.cover(store_id)
        except LudexError as error:
            failure = failure or error
            continue
        except (Exception, SystemExit):
            failure = failure or LudexError("cover_failed", "plugin cover failed")
            continue
        if data is None:
            atomic_write_private(miss, b"")
            continue
        if not _is_image(data):
            failure = failure or LudexError("invalid_cover", "plugin returned an invalid cover")
            continue
        atomic_write_private(file, data)
        return file
    if failure is not None:
        raise failure
    return None
