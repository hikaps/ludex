"""Heroic sideloaded games: the "Add Game" entries in ``sideload_apps/library.json``.

Every entry whose runner is ``sideload`` is one owned game (store id = Heroic's ``app_name``);
Heroic keeps launching it with its own runner, prefix and environment settings. Complete: the
file is the whole list, and a missing or unreadable file raises, never an empty result. Installed
is Heroic's ``is_installed``. The layout is from a real Heroic Flatpak install, not documented by
Heroic. ponytail: name and install state only (no executable, prefix or artwork).
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from ..plugins import ConfigField, FetchResult, OwnedGame, Provider, SourceError

_DIRS = (
    "~/.config/heroic",
    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic",
)
_MAX_BYTES = 8 * 1024 * 1024


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


def fetch(config: Mapping[str, str]) -> FetchResult:
    return FetchResult([OwnedGame("heroic", g["app_name"], g["title"]) for g in _entries(config)], True, "sideload library")


def installed(config: Mapping[str, str]) -> list[str]:
    return [g["app_name"] for g in _entries(config) if g.get("is_installed") is True]


PLUGIN = Provider(
    name="heroic",
    help="Games sideloaded into Heroic (read from its config folder on this machine)",
    config_fields=(ConfigField("heroic_dir", "Heroic config folder; blank to auto-detect", optional=True, path=True),),
    fetch=fetch,
    installed=installed,
    launch_url=lambda store_id: f"heroic://launch?appName={quote(store_id, safe='')}&runner=sideload",
)
