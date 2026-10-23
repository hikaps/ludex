"""Start or install an owned game through its store's own client (the plugin supplies the URL)."""
from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

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


def _pick(conn, sources: Mapping[str, Provider], game_id: int, store: str | None, usable, verb: str) -> dict:
    game = get_game(conn, game_id)
    candidates = [o for o in game["ownership"] if not o["removed"] and usable(sources.get(o["store"]))]
    if store is not None:
        candidates = [o for o in candidates if o["store"] == store]
    stores = sorted({o["store"] for o in candidates})
    if not candidates:
        raise LudexError(f"not_{verb}able", f"game {game_id} has no owned copy that can be {verb}ed")
    if len(stores) > 1:
        raise LudexError(f"{verb}_ambiguous", f"game {game_id} can be {verb}ed from {', '.join(stores)}; pass --store")
    return candidates[0]


def launch_game(
    conn,
    sources: Mapping[str, Provider],
    game_id: int,
    store: str | None = None,
    config_for: Callable[[str, str], Mapping[str, str]] | None = None,
) -> str:
    """Start a game; returns ``store:store_id``. ``config_for(store, account)`` supplies the account configuration for providers that launch by command. ponytail: no installed check, the client reports a game that is not installed; add when launch must pick installed copies."""
    record = _pick(conn, sources, game_id, store, lambda p: p is not None and (p.launch_url or p.launch_command), "launch")
    provider = sources[record["store"]]
    if provider.launch_url:
        open_url(provider.launch_url(record["store_id"]), f"the {record['store']} client for this game")
    else:
        if config_for is None:
            raise LudexError("launch_failed", "this provider launches by command and no account configuration is available")
        try:
            argv = [str(a) for a in provider.launch_command(config_for(record["store"], record["account"]), record["store_id"])]
        except LudexError:
            raise
        except Exception as exc:
            raise LudexError("launch_failed", f"provider {record['store']} could not build a launch command ({type(exc).__name__})") from None
        if not argv or not Path(argv[0]).is_absolute():
            raise LudexError("launch_failed", f"provider {record['store']} returned an invalid launch command")
        try:
            subprocess.Popen(
                argv, cwd=Path(argv[0]).parent, start_new_session=True,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            raise LudexError("launch_failed", "the game could not be started (is it executable?)") from None
    return f"{record['store']}:{record['store_id']}"


def install_game(conn, sources: Mapping[str, Provider], game_id: int, store: str | None = None) -> str:
    """Ask the owning store's client to install a game you own; returns ``store:store_id``."""
    record = _pick(conn, sources, game_id, store, lambda p: p is not None and p.install_url, "install")
    open_url(sources[record["store"]].install_url(record["store_id"]), f"the {record['store']} client for this game")
    return f"{record['store']}:{record['store_id']}"
