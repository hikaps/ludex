"""Local games directory source: every non-hidden subfolder of ``path`` is one owned game.

``path`` may be a glob such as ``/mnt/games/*``: every matching folder is searched, and the store
id becomes ``<matched folder>/<game folder>`` so equal names under different folders stay distinct.
A plain path keeps the folder name as store id. The title is always the folder name. Every game folder is also reported installed. Complete: a folder that disappears is marked
removed. An unreadable or empty ``path`` raises instead, so an unmounted drive never wipes the
library. ponytail: launching runs one executable per game (no launcher menus); folders only (no loose files such as AppImages or ROMs) and no title cleanup
(scene tags, versions); add when a real library needs them.

``exclude`` (optional) lists folder names to skip, separated by commas or newlines. Each entry is a
case-insensitive pattern (``*`` and ``?``) matched against the folder name, and against
``<matched folder>/<game folder>`` when ``path`` is a glob, so ``_unsorted`` or ``backup*`` or
``steamapps/Proton*`` all work. A game excluded after it was imported is marked removed by the next import.
"""
from __future__ import annotations

import fnmatch
import glob
import os
from collections.abc import Mapping
from pathlib import Path

from ..plugins import ConfigField, FetchResult, OwnedGame, SourceError, Provider


def _roots(config: Mapping[str, str]) -> tuple[list[Path], bool]:
    raw = config.get("path")
    if not raw:
        raise SourceError("invalid_config", "path is required")
    pattern = str(Path(raw).expanduser())
    if glob.has_magic(pattern):
        return sorted(Path(m) for m in glob.glob(pattern) if Path(m).is_dir()), True
    return [Path(pattern)], False


def _excluded(config: Mapping[str, str]) -> list[str]:
    raw = config.get("exclude") or ""
    return [p.strip().casefold() for p in raw.replace("\n", ",").split(",") if p.strip()]


def _scan(config: Mapping[str, str]) -> list[OwnedGame]:
    roots, qualify = _roots(config)
    skip = _excluded(config)
    games: list[OwnedGame] = []
    try:
        for root in roots:
            for folder in sorted(root.iterdir()):
                if folder.is_dir() and not folder.name.startswith("."):
                    store_id = f"{root.name}/{folder.name}" if qualify else folder.name
                    if any(fnmatch.fnmatchcase(name, pattern) for pattern in skip for name in (folder.name.casefold(), store_id.casefold())):
                        continue
                    games.append(OwnedGame("local", store_id, folder.name))
    except OSError:
        raise SourceError("directory_unreadable", "games directory is missing or unreadable") from None
    if not roots:
        raise SourceError("directory_unreadable", "games directory is missing or unreadable")
    if not games:
        raise SourceError("directory_empty", "games directory has no game folders (is the drive mounted?)")
    return games


def fetch(config: Mapping[str, str]) -> FetchResult:
    return FetchResult(_scan(config), True, "directory")


def installed(config: Mapping[str, str]) -> set[str]:
    """Every game folder on disk counts as installed (an unmounted drive raises, as in ``fetch``)."""
    return {g.store_id for g in _scan(config)}


def game_folder(config: Mapping[str, str], store_id: str) -> Path:
    roots, qualify = _roots(config)
    root_name, _, folder_name = store_id.rpartition("/") if qualify else ("", "", store_id)
    folders = [r / folder_name for r in roots if (not qualify or r.name == root_name) and (r / folder_name).is_dir()]
    if len(folders) != 1:
        raise SourceError("not_launchable", "the game folder was not found (or is ambiguous)")
    return folders[0]


def launch_command(config: Mapping[str, str], store_id: str) -> list[str]:
    """The game's single native launcher: ``start.sh``, else the only executable ``.sh`` or ``.AppImage`` at the top of its folder."""
    folder = game_folder(config, store_id)
    try:
        found = sorted(
            f for f in folder.iterdir()
            if f.is_file() and os.access(f, os.X_OK) and f.suffix.lower() in (".sh", ".appimage")
        )
    except OSError:
        raise SourceError("not_launchable", "the game folder is unreadable") from None
    start = [f for f in found if f.name == "start.sh"]
    if start or len(found) == 1:
        return [str((start or found)[0].resolve())]
    raise SourceError(
        "not_launchable",
        "no single native launcher (need start.sh or one executable .sh/.AppImage); "
        "for a Windows game set a runner with 'ludex game set GAME --runner NAME' (see 'ludex runners')",
    )


PLUGIN = Provider(
    name="local",
    help="A folder of games: each subfolder is one game (add one account per folder)",
    config_fields=(
        ConfigField("path", "games directory, or a pattern like /mnt/games/* to search every folder in it", path=True),
        ConfigField("exclude", "folder names to skip, comma-separated (patterns like _* or backup* work)", optional=True),
    ),
    fetch=fetch,
    installed=installed,
    launch_command=launch_command,
    game_folder=game_folder,
)
