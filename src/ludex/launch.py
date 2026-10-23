"""Start or install an owned game through its store's own client (the plugin supplies the URL)."""
from __future__ import annotations

import subprocess
from collections.abc import Mapping

from .errors import LudexError
from .library import get_game
from .plugins import Provider


def open_url(url: str, what: str) -> None:
    """Hand ``url`` to the desktop (xdg-open); errors name ``what`` but never the URL."""
    try:
        subprocess.run(["xdg-open", url], check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise LudexError("launcher_missing", "xdg-open is not installed") from None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise LudexError("launch_failed", f"the system could not open {what}") from None


def _open_owned(conn, sources: Mapping[str, Provider], game_id: int, store: str | None, field: str, verb: str) -> str:
    game = get_game(conn, game_id)
    owned = [o for o in game["ownership"] if not o["removed"]]
    usable = [o for o in owned if getattr(sources.get(o["store"]), field, None)]
    if store is not None:
        usable = [o for o in usable if o["store"] == store]
    stores = sorted({o["store"] for o in usable})
    if not usable:
        raise LudexError(f"not_{verb}able", f"game {game_id} has no owned copy that can be {verb}ed")
    if len(stores) > 1:
        raise LudexError(f"{verb}_ambiguous", f"game {game_id} can be {verb}ed from {', '.join(stores)}; pass --store")
    record = usable[0]
    open_url(getattr(sources[record["store"]], field)(record["store_id"]), f"the {record['store']} client for this game")
    return f"{record['store']}:{record['store_id']}"


def launch_game(conn, sources: Mapping[str, Provider], game_id: int, store: str | None = None) -> str:
    """Open the launch URL of a game; returns ``store:store_id``. ponytail: no installed check, the client reports a game that is not installed; add when launch must pick installed copies."""
    return _open_owned(conn, sources, game_id, store, "launch_url", "launch")


def install_game(conn, sources: Mapping[str, Provider], game_id: int, store: str | None = None) -> str:
    """Ask the owning store's client to install a game you own; returns ``store:store_id``."""
    return _open_owned(conn, sources, game_id, store, "install_url", "install")
