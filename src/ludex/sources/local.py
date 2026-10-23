"""Local games directory source: every non-hidden subfolder of ``path`` is one owned game.

The folder name is both the store id and the title. Complete: a folder that disappears is marked
removed. An unreadable or empty ``path`` raises instead, so an unmounted drive never wipes the
library. ponytail: folders only (no loose files such as AppImages or ROMs) and no title cleanup
(scene tags, versions); add when a real library needs them.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..plugins import ConfigField, FetchResult, OwnedGame, SourceError, SourcePlugin


def fetch(config: Mapping[str, str]) -> FetchResult:
    raw = config.get("path")
    if not raw:
        raise SourceError("invalid_config", "path is required")
    root = Path(raw).expanduser()
    try:
        names = sorted(p.name for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        raise SourceError("directory_unreadable", "games directory is missing or unreadable") from None
    if not names:
        raise SourceError("directory_empty", "games directory has no game folders (is the drive mounted?)")
    return FetchResult([OwnedGame("local", name, name) for name in names], True, "directory")


PLUGIN = SourcePlugin(
    name="local",
    help="A folder of games: each subfolder is one game (add one account per folder)",
    config_fields=(ConfigField("path", "games directory, for example ~/Games"),),
    fetch=fetch,
)
