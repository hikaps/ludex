"""Epic ownership source: reads the library cache Legendary keeps on disk (no network, no login).

Legendary (also bundled in Heroic) writes one ``metadata/<app_name>.json`` per entitled app. The
games are those whose ``metadata.mainGameItemList`` is empty; entries with a main game are DLC. The
cache is refreshed only when Legendary or Heroic refreshes its library, so it can lag the account:
the result is ``complete=False`` and nothing is ever removed. The layout is from a real Heroic
Flatpak install, not documented by Legendary. ``user.json`` (login tokens) is never opened.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..plugins import ConfigField, FetchResult, OwnedGame, SourceError, SourcePlugin

_DIRS = (
    "~/.config/legendary",
    "~/.config/heroic/legendaryConfig/legendary",
    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic/legendaryConfig/legendary",
)
_MAX_FILE_BYTES = 8 * 1024 * 1024


def _legendary_dir(config: Mapping[str, str]) -> Path:
    explicit = config.get("legendary_dir")
    for candidate in (explicit,) if explicit else _DIRS:
        path = Path(candidate).expanduser()
        if (path / "metadata").is_dir():
            return path
    raise SourceError("epic_not_found", "Legendary folder not found; set legendary_dir to its config directory")


def _games(directory: Path) -> list[OwnedGame]:
    games: dict[str, OwnedGame] = {}
    for path in sorted((directory / "metadata").glob("*.json")):
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not isinstance(data.get("metadata"), dict):
            continue
        app_name, title = data.get("app_name"), data.get("app_title")
        if not isinstance(app_name, str) or not app_name or data["metadata"].get("mainGameItemList"):
            continue
        title = title.strip() if isinstance(title, str) else ""
        games[app_name] = OwnedGame("epic", app_name, title or app_name, {"namespace": data["metadata"].get("namespace")})
    return list(games.values())


def fetch(config: Mapping[str, str]) -> FetchResult:
    return FetchResult(_games(_legendary_dir(config)), False, "local")


PLUGIN = SourcePlugin(
    name="epic",
    help="Epic library from the Legendary or Heroic cache on this machine (no login; refresh it in Heroic first)",
    config_fields=(ConfigField("legendary_dir", "Legendary config folder; blank to auto-detect", optional=True),),
    fetch=fetch,
)
