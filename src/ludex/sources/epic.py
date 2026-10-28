"""Epic ownership source: reads the library cache Legendary keeps on disk (no network, no login).

Legendary (also bundled in Heroic) writes one ``metadata/<app_name>.json`` per entitled app. The
games are those whose ``metadata.mainGameItemList`` is empty; entries with a main game are DLC. The
cache is refreshed only when Legendary or Heroic refreshes its library, so it can lag the account:
the result is ``complete=False`` and nothing is ever removed. The layout is from a real Heroic
Flatpak install, not documented by Legendary. ``user.json`` (login tokens) is never opened.
"""
from __future__ import annotations

from urllib.parse import quote

import json
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..plugins import ConfigField, FetchResult, OwnedGame, SourceError, Provider

_DIRS = (
    "~/.config/legendary",
    "~/.config/heroic/legendaryConfig/legendary",
    "~/.var/app/com.heroicgameslauncher.hgl/config/heroic/legendaryConfig/legendary",
)
_MAX_FILE_BYTES = 8 * 1024 * 1024
_APP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_FLATPAK_ID = "com.heroicgameslauncher.hgl"
_FLATPAK_LEGENDARY = "/app/bin/heroic/resources/app.asar.unpacked/build/bin/x64/linux/legendary"  # seen in the Heroic Flatpak


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


def installed(config: Mapping[str, str]) -> set[str]:
    """App names in Legendary's installed.json (empty when nothing was ever installed)."""
    path = _legendary_dir(config) / "installed.json"
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8")) if path.stat().st_size <= _MAX_FILE_BYTES else {}
    except FileNotFoundError:
        return set()
    except (OSError, ValueError):
        raise SourceError("epic_installed_unreadable", "Legendary's installed.json is unreadable") from None
    return {key for key in data if isinstance(key, str)} if isinstance(data, dict) else set()


def fetch(config: Mapping[str, str]) -> FetchResult:
    return FetchResult(_games(_legendary_dir(config)), False, "local")


def install_command(config: Mapping[str, str], store_id: str) -> list[str]:
    """Legendary's own ``install``: through the Heroic Flatpak's bundled copy, else a ``legendary`` on PATH.

    Heroic has no install link, so this drives the tool Heroic itself uses, on Heroic's config (so Heroic sees the
    result). Installs under ``install_dir`` (default ``~/Games/Heroic``, which the Heroic Flatpak may write to).
    """
    if not _APP_NAME.fullmatch(store_id):
        raise SourceError("epic_bad_id", "this Epic game id cannot be installed from here")
    base = Path(config.get("install_dir") or "~/Games/Heroic").expanduser()
    if not base.is_absolute():
        raise SourceError("invalid_config", "install_dir must be absolute (a leading ~ is fine)")
    directory = _legendary_dir(config)
    tail = ["-y", "install", store_id, "--base-path", str(base), "--skip-sdl"]
    if directory.is_relative_to(Path.home() / ".var" / "app" / _FLATPAK_ID):
        flatpak = shutil.which("flatpak")
        if flatpak is None:
            raise SourceError("epic_no_legendary", "flatpak is not installed (Heroic is the Flatpak here)")
        return [flatpak, "run", f"--env=LEGENDARY_CONFIG_PATH={directory}", f"--command={_FLATPAK_LEGENDARY}", _FLATPAK_ID, *tail]
    legendary, env = shutil.which("legendary"), shutil.which("env")
    if legendary is None or env is None:
        raise SourceError("epic_no_legendary", "legendary is not installed (install it, or use Heroic's Flatpak)")
    return [env, f"LEGENDARY_CONFIG_PATH={directory}", legendary, *tail]


PLUGIN = Provider(
    name="epic",
    help="Epic library from the Legendary or Heroic cache on this machine (no login; refresh it in Heroic first)",
    config_fields=(
        ConfigField("legendary_dir", "Legendary config folder; blank to auto-detect", optional=True),
        ConfigField("install_dir", "folder games are installed under; blank: ~/Games/Heroic", optional=True, path=True),
    ),
    fetch=fetch,
    installed=installed,
    launch_url=lambda store_id: f"heroic://launch?appName={quote(store_id, safe='')}&runner=legendary",
    install_command=install_command,
)
