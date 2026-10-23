"""Start an owned game through its store's own client (the plugin supplies the URL)."""
from __future__ import annotations

import subprocess
from collections.abc import Mapping

from .errors import LudexError
from .library import get_game
from .plugins import Provider


def launch_game(conn, sources: Mapping[str, Provider], game_id: int, store: str | None = None) -> str:
    """Open the launch URL of a game; returns ``store:store_id``. ponytail: no installed check, the client reports a game that is not installed; add when launch must pick installed copies."""
    game = get_game(conn, game_id)
    owned = [o for o in game["ownership"] if not o["removed"]]
    launchable = [o for o in owned if getattr(sources.get(o["store"]), "launch_url", None)]
    if store is not None:
        launchable = [o for o in launchable if o["store"] == store]
    stores = sorted({o["store"] for o in launchable})
    if not launchable:
        raise LudexError("not_launchable", f"game {game_id} has no owned copy that can be launched")
    if len(stores) > 1:
        raise LudexError("launch_ambiguous", f"game {game_id} can be launched from {', '.join(stores)}; pass --store")
    record = launchable[0]
    url = sources[record["store"]].launch_url(record["store_id"])
    try:
        subprocess.run(["xdg-open", url], check=True, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        raise LudexError("launcher_missing", "xdg-open is not installed") from None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise LudexError("launch_failed", f"the system could not open the {record['store']} client for this game") from None
    return f"{record['store']}:{record['store_id']}"
