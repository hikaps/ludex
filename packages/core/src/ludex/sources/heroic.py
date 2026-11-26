"""Heroic sideloaded games: the "Add Game" entries in ``sideload_apps/library.json``.

Every entry whose runner is ``sideload`` is one owned game (store id = Heroic's ``app_name``);
Heroic keeps launching it with its own runner, prefix and environment settings. Complete: the
file is the whole list, and a missing or unreadable file raises, never an empty result. Installed
is Heroic's ``is_installed``. The layout is from a real Heroic Flatpak install, not documented by
Heroic. ponytail: name and install state only (no executable, prefix or artwork).
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .procs import command_lines
from ..plugins import ConfigField, FetchResult, GameLocation, OwnedGame, PlayRecord, Provider, SourceError

_DIRS = (
    "~/.config/heroic",
    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic",
)
_MAX_BYTES = 8 * 1024 * 1024
_DRIVE = re.compile(r"^[A-Za-z]:(?=/)")


def _entries(config: Mapping[str, str]) -> list[dict[str, Any]]:
    explicit = config.get("heroic_dir")
    for candidate in (explicit,) if explicit else _DIRS:
        path = Path(candidate).expanduser() / "sideload_apps" / "library.json"
        if path.is_file():
            break
    else:
        raise SourceError("heroic_not_found", "Heroic folder not found; set heroic_dir to its config directory")
    try:
        if path.stat().st_size > _MAX_BYTES:
            raise SourceError("heroic_unreadable", "Heroic's sideload library is too large")
        games = json.loads(path.read_text(encoding="utf-8")).get("games")
    except OSError:
        raise SourceError("heroic_unreadable", "Heroic's sideload library could not be read") from None
    except (ValueError, AttributeError):
        raise SourceError("heroic_unreadable", "Heroic's sideload library is not in the expected format") from None
    if not isinstance(games, list):
        raise SourceError("heroic_unreadable", "Heroic's sideload library is not in the expected format")
    return [
        g for g in games
        if isinstance(g, dict) and g.get("runner") == "sideload"
        and isinstance(g.get("app_name"), str) and g["app_name"] and isinstance(g.get("title"), str) and g["title"]
    ]


def heroic_playtime(directory: Path) -> dict[str, PlayRecord]:
    """Heroic's own play record, ``store/timestamp.json``: ``{app_name: {lastPlayed, totalPlayed (minutes)}}`` for every store it runs."""
    path = directory / "store" / "timestamp.json"
    try:
        if path.stat().st_size > _MAX_BYTES:
            raise SourceError("heroic_unreadable", "Heroic's play time file is too large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}  # Heroic has not recorded any play yet
    except OSError:
        raise SourceError("heroic_unreadable", "Heroic's play time file could not be read") from None
    except ValueError:
        raise SourceError("heroic_unreadable", "Heroic's play time file is not in the expected format") from None
    if not isinstance(data, dict):
        raise SourceError("heroic_unreadable", "Heroic's play time file is not in the expected format")
    found: dict[str, PlayRecord] = {}
    for app_name, entry in data.items():
        total = entry.get("totalPlayed") if isinstance(entry, dict) else None
        if not isinstance(total, (int, float)) or isinstance(total, bool) or total < 0:
            continue
        when = None
        last = entry.get("lastPlayed")
        if isinstance(last, str):
            try:
                when = datetime.fromisoformat(last.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            except ValueError:
                pass
        found[str(app_name)] = PlayRecord(int(total), when)
    return found


def _heroic_dir(config: Mapping[str, str]) -> Path:
    explicit = config.get("heroic_dir")
    for candidate in (explicit,) if explicit else _DIRS:
        path = Path(candidate).expanduser()
        if path.is_dir():
            return path
    raise SourceError("heroic_not_found", "Heroic folder not found; set heroic_dir to its config directory")


def playtime(config: Mapping[str, str]) -> dict[str, PlayRecord]:
    return heroic_playtime(_heroic_dir(config))


def fetch(config: Mapping[str, str]) -> FetchResult:
    return FetchResult([OwnedGame("heroic", g["app_name"], g["title"]) for g in _entries(config)], True, "sideload library")


def installed(config: Mapping[str, str]) -> list[str]:
    return [g["app_name"] for g in _entries(config) if g.get("is_installed") is True]


def heroic_prefix(directory: Path, app_name: str) -> Path | None:
    """The Wine prefix Heroic's per-game settings (``GamesConfig/<app>.json``) name; ``None`` when the game has none of its own."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", app_name):
        return None  # an id that is not one path component must not reach the filesystem
    path = directory / "GamesConfig" / f"{app_name}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.stat().st_size <= _MAX_BYTES else {}
        entry = data.get(app_name) if isinstance(data, dict) else None
        prefix = entry.get("winePrefix") if isinstance(entry, dict) else None
        return Path(prefix).expanduser() if isinstance(prefix, str) and prefix else None
    except (OSError, ValueError, RuntimeError):  # RuntimeError: a ~user that cannot be expanded
        return None


def game_location(config: Mapping[str, str], store_id: str) -> GameLocation:
    directory = _heroic_dir(config)
    for game in _entries(config):
        if game["app_name"] == store_id and isinstance(game.get("folder_name"), str) and Path(game["folder_name"]).is_absolute():
            folder = Path(game["folder_name"]) if game.get("is_installed") is True else None  # Heroic keeps the path of an uninstalled entry
            return GameLocation(folder, heroic_prefix(directory, store_id))
    raise SourceError("not_launchable", "Heroic has no folder for this game")


def _unixy(arg: str) -> str:
    """A Windows path as Wine shows it (``Z:\\mnt\\games\\x.exe``) as the Linux path it points at."""
    return _DRIVE.sub("", arg.replace("\\", "/"))


def running(config: Mapping[str, str]) -> list[str]:
    """The sideloaded games with a program of theirs running: a process whose command line names the game's
    executable, or any ``.exe`` inside its folder (Heroic starts a Windows game through Wine or Proton with
    the program's path as an argument). A heuristic: Heroic itself keeps no record of what is running."""
    games = [
        (g["app_name"], str(g["folder_name"]).rstrip("/") + "/", g.get("install", {}).get("executable"))
        for g in _entries(config)
        if g.get("is_installed") is True and isinstance(g.get("folder_name"), str) and g["folder_name"].strip("/")
    ]
    found: list[str] = []
    for argv in command_lines():
        args = [_unixy(a) for a in argv[1:]] + [argv[0]]
        for app_name, folder, executable in games:
            if app_name not in found and any(a == executable or (a.startswith(folder) and a.lower().endswith(".exe")) for a in args):
                found.append(app_name)
    return found


PLUGIN = Provider(
    name="heroic",
    help="Games sideloaded into Heroic (read from its config folder on this machine)",
    config_fields=(ConfigField("heroic_dir", "Heroic config folder; blank to auto-detect", optional=True, path=True),),
    fetch=fetch,
    installed=installed,
    playtime=playtime,
    running=running,
    launch_url=lambda store_id: f"heroic://launch?appName={quote(store_id, safe='')}&runner=sideload",
    game_location=game_location,
)
