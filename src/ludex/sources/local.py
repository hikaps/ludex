"""Local games directory source: every non-hidden subfolder of ``path`` is one owned game.

``path`` may be a glob such as ``/mnt/games/*``: every matching folder is searched, and the store
id becomes ``<matched folder>/<game folder>`` so equal names under different folders stay distinct.
A plain path keeps the folder name as store id. The title is always the folder name. Complete: a folder that disappears is marked
removed. An unreadable or empty ``path`` raises instead, so an unmounted drive never wipes the
library. ponytail: folders only (no loose files such as AppImages or ROMs) and no title cleanup
(scene tags, versions); add when a real library needs them.
"""
from __future__ import annotations

import glob
from collections.abc import Mapping
from pathlib import Path

from ..plugins import ConfigField, FetchResult, OwnedGame, SourceError, SourcePlugin


def fetch(config: Mapping[str, str]) -> FetchResult:
    raw = config.get("path")
    if not raw:
        raise SourceError("invalid_config", "path is required")
    pattern = str(Path(raw).expanduser())
    if glob.has_magic(pattern):
        roots = sorted(Path(m) for m in glob.glob(pattern) if Path(m).is_dir())
        qualify = True
    else:
        roots, qualify = [Path(pattern)], False
    games: list[OwnedGame] = []
    try:
        for root in roots:
            for folder in sorted(root.iterdir()):
                if folder.is_dir() and not folder.name.startswith("."):
                    store_id = f"{root.name}/{folder.name}" if qualify else folder.name
                    games.append(OwnedGame("local", store_id, folder.name))
    except OSError:
        raise SourceError("directory_unreadable", "games directory is missing or unreadable") from None
    if not roots:
        raise SourceError("directory_unreadable", "games directory is missing or unreadable")
    if not games:
        raise SourceError("directory_empty", "games directory has no game folders (is the drive mounted?)")
    return FetchResult(games, True, "directory")


PLUGIN = SourcePlugin(
    name="local",
    help="A folder of games: each subfolder is one game (add one account per folder)",
    config_fields=(ConfigField("path", "games directory, or a pattern like /mnt/games/* to search every folder in it", path=True),),
    fetch=fetch,
)
