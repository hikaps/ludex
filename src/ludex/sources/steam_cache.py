"""Read the games a Steam client has licensed from its local cache (no network, no key).

``appcache/packageinfo.vdf`` lists license packages and the app IDs each grants;
``appcache/appinfo.vdf`` names those apps and gives their type. Both are undocumented binary
formats: only the versions below were seen (packageinfo v40, appinfo v41, decoded from a real
install) and anything else yields no games rather than guesses. The cache can lag the account, so
callers must treat the result as incomplete.
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

_PACKAGEINFO_MAGIC = 0x06565528
_APPINFO_MAGIC = 0x07564429
_MAX_BYTES = 64 * 1024 * 1024
_MAX_DEPTH = 32


def _read(path: Path) -> bytes | None:
    try:
        if path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _kv(data: bytes, pos: int, strings: list[str] | None, depth: int = 0) -> tuple[dict[str, Any], int]:
    """Binary KeyValues; keys are NUL strings, or indexes into ``strings`` when given."""
    if depth > _MAX_DEPTH:
        raise ValueError("too deep")
    out: dict[str, Any] = {}
    while True:
        kind = data[pos]
        pos += 1
        if kind == 8:
            return out, pos
        if strings is None:
            end = data.index(b"\0", pos)
            key, pos = data[pos:end].decode("utf-8", "replace"), end + 1
        else:
            key = strings[struct.unpack_from("<I", data, pos)[0]]
            pos += 4
        if kind == 0:
            out[key], pos = _kv(data, pos, strings, depth + 1)
        elif kind == 1:
            end = data.index(b"\0", pos)
            out[key], pos = data[pos:end].decode("utf-8", "replace"), end + 1
        elif kind in (2, 3, 4, 6):
            out[key] = struct.unpack_from("<i", data, pos)[0]
            pos += 4
        elif kind in (7, 10):
            out[key] = struct.unpack_from("<q", data, pos)[0]
            pos += 8
        else:
            raise ValueError(f"unknown value type {kind}")


def _licensed_app_ids(data: bytes) -> set[int]:
    if struct.unpack_from("<I", data, 0)[0] != _PACKAGEINFO_MAGIC:
        raise ValueError("unsupported packageinfo version")
    pos, apps = 8, set()
    while True:
        package = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        if package == 0xFFFFFFFF:
            return apps
        entry, pos = _kv(data, pos + 32, None)  # sha1, change number, token precede the KeyValues
        for value in entry.values():
            if isinstance(value, dict) and isinstance(value.get("appids"), dict):
                apps.update(int(a) for a in value["appids"].values() if isinstance(a, int))


def _app_names(data: bytes, wanted: set[int]) -> dict[int, str]:
    magic, _universe, strings_at = struct.unpack_from("<IIQ", data, 0)
    if magic != _APPINFO_MAGIC:
        raise ValueError("unsupported appinfo version")
    count = struct.unpack_from("<I", data, strings_at)[0]
    strings, pos = [], strings_at + 4
    for _ in range(count):
        end = data.index(b"\0", pos)
        strings.append(data[pos:end].decode("utf-8", "replace"))
        pos = end + 1
    names: dict[int, str] = {}
    pos = 16
    while True:
        app_id, size = struct.unpack_from("<II", data, pos)
        if app_id == 0:
            return names
        body = pos + 8
        pos = body + size
        if app_id not in wanted:
            continue
        entry, _ = _kv(data, body + 60, strings)  # state, times, token, sha1s precede the KeyValues
        common = entry.get("appinfo", entry).get("common")
        if isinstance(common, dict) and str(common.get("type", "")).lower() == "game":
            name = common.get("name")
            if isinstance(name, str) and name.strip():
                names[app_id] = name.strip()


def cached_games(steam_dir: Path) -> dict[int, str]:
    """App ID -> name for licensed apps of type game; empty when the cache is missing or unreadable."""
    packages = _read(steam_dir / "appcache" / "packageinfo.vdf")
    apps = _read(steam_dir / "appcache" / "appinfo.vdf")
    if packages is None or apps is None:
        return {}
    try:
        return _app_names(apps, _licensed_app_ids(packages))
    except (ValueError, IndexError, struct.error):
        return {}
