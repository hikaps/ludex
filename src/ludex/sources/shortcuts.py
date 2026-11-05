"""Non-Steam shortcuts: the games added to Steam by hand (``userdata/*/config/shortcuts.vdf``).

Each shortcut is one owned game; the store id is the 64-bit game id Steam launches it by
(``steam://rungameid/<id>``), so the Steam client keeps applying its own compatibility-tool
settings. Complete: the file is the whole list. A missing or unreadable file raises instead of
returning nothing, so a Steam update never wipes the library. Installed means the shortcut's
executable exists. ponytail: reads the name, executable and id only (no launch options, no
compatibility tool, no artwork); add when ludex launches shortcuts itself.
"""
from __future__ import annotations

import zlib
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import quote

import vdf

from ..plugins import ConfigField, FetchResult, OwnedGame, Provider, SourceError
from .steam import _steam_dir

_MAX_BYTES = 4 * 1024 * 1024


def _field(entry: Mapping[str, object], name: str) -> object:
    return next((v for k, v in entry.items() if k.lower() == name), None)


def _game_id(entry: Mapping[str, object], exe: str, name: str) -> str:
    appid = _field(entry, "appid")
    if not isinstance(appid, int):  # older files carry no appid: Steam derives it from the exe and name
        appid = zlib.crc32((exe + name).encode()) | 0x80000000
    return str(((appid & 0xFFFFFFFF) << 32) | 0x02000000)


def _shortcuts(config: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """(game id, title, executable) for every shortcut of every Steam user."""
    steam = _steam_dir(config)
    files = sorted((steam / "userdata").glob("*/config/shortcuts.vdf"))
    if not files:
        raise SourceError("shortcuts_not_found", "no shortcuts.vdf found under the Steam folder")
    found: dict[str, tuple[str, str, str]] = {}
    for path in files:
        try:
            if path.stat().st_size > _MAX_BYTES:
                raise SourceError("shortcuts_unreadable", "shortcuts.vdf is too large")
            data = vdf.binary_loads(path.read_bytes())
        except OSError:
            raise SourceError("shortcuts_unreadable", "shortcuts.vdf could not be read") from None
        except (SyntaxError, ValueError, KeyError, UnicodeDecodeError):
            raise SourceError("shortcuts_unreadable", "shortcuts.vdf is not in the expected format") from None
        entries = next((v for k, v in data.items() if k.lower() == "shortcuts"), {})
        for entry in entries.values() if isinstance(entries, dict) else ():
            name, exe = _field(entry, "appname"), _field(entry, "exe")
            if isinstance(name, str) and isinstance(exe, str) and name:
                found[_game_id(entry, exe, name)] = (_game_id(entry, exe, name), name, exe.strip('"'))
    return list(found.values())


def fetch(config: Mapping[str, str]) -> FetchResult:
    games = [OwnedGame("shortcuts", game_id, title) for game_id, title, _ in _shortcuts(config)]
    return FetchResult(games, True, "shortcuts.vdf")


def installed(config: Mapping[str, str]) -> list[str]:
    return [game_id for game_id, _, exe in _shortcuts(config) if Path(exe).exists()]


PLUGIN = Provider(
    name="shortcuts",
    help="Non-Steam games added to Steam as shortcuts (read from the local Steam folder)",
    config_fields=(ConfigField("steam_dir", "Steam folder; blank to auto-detect", optional=True, path=True),),
    fetch=fetch,
    installed=installed,
    launch_url=lambda store_id: f"steam://rungameid/{quote(store_id, safe='')}",
)
