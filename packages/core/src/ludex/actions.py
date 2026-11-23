"""What plugins offer to do with a game besides play it (``Provider.actions``): listed per game, run as a background job."""
from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from .errors import LudexError
from .jobs import Job, start_job
from .library import get_game
from .plugins import GameAction, Provider, _view_label

_ID = re.compile(r"[a-z][a-z0-9-]*")
_MAX_PER_COPY = 10


@dataclass(frozen=True, slots=True)
class ActionInfo:
    plugin: str
    id: str
    label: str  # carries the store, "Label (store)", when the same action is offered for copies in several stores
    store: str
    store_id: str


def _valid(action: object) -> bool:
    if not (isinstance(action, GameAction) and isinstance(action.id, str) and _ID.fullmatch(action.id) and _view_label(action.label)):
        return False
    argv = action.argv
    return isinstance(argv, (list, tuple)) and bool(argv) and all(isinstance(a, str) and "\0" not in a for a in argv) and Path(argv[0]).is_absolute()


def _offered(sources: Mapping[str, Provider], store: str, store_id: str) -> list[tuple[str, GameAction]]:
    found: list[tuple[str, GameAction]] = []
    for name, provider in sorted(sources.items()):
        if provider.actions is None:
            continue
        try:
            actions = list(provider.actions(store, store_id))
        except (Exception, SystemExit):  # a broken plugin offers nothing; it must not break the game page
            continue
        seen: set[str] = set()
        for action in actions[:_MAX_PER_COPY]:
            if _valid(action) and action.id not in seen:
                seen.add(action.id)
                found.append((name, action))
    return found


def _copies(conn: sqlite3.Connection, game_id: int) -> list[dict]:
    game = get_game(conn, game_id)
    return sorted((o for o in game["ownership"] if not o["removed"]), key=lambda o: (o["store"], str(o["store_id"])))


def list_actions(conn: sqlite3.Connection, sources: Mapping[str, Provider], game_id: int) -> list[ActionInfo]:
    """The actions the loaded plugins offer for the game's owned copies, ordered by plugin, action id and store."""
    items: dict[tuple[str, str, str, str], ActionInfo] = {}
    for copy in _copies(conn, game_id):
        for plugin, action in _offered(sources, copy["store"], str(copy["store_id"])):
            key = (plugin, action.id, copy["store"], str(copy["store_id"]))
            items.setdefault(key, ActionInfo(plugin, action.id, action.label, copy["store"], str(copy["store_id"])))
    stores: dict[tuple[str, str], set[str]] = {}
    for item in items.values():
        stores.setdefault((item.plugin, item.id), set()).add(item.store)
    return sorted(
        (replace(i, label=f"{i.label} ({i.store})") if len(stores[(i.plugin, i.id)]) > 1 else i for i in items.values()),
        key=lambda i: (i.plugin, i.id, i.store, i.store_id),
    )


def run_action(
    conn: sqlite3.Connection, sources: Mapping[str, Provider], game_id: int, plugin: str, action_id: str, store: str | None, log_dir: Path,
    dry_run: bool = False,
) -> tuple[ActionInfo, list[str], Job | None]:
    """Start ``plugin``'s action for the game as an ``action`` job; returns ``(action, argv, job)`` (``job`` is ``None`` for a ``dry_run``).

    ``store`` picks the copy when the action is offered for several stores.
    """
    provider = sources.get(plugin)
    if provider is None or provider.actions is None:
        raise LudexError("unknown_action", f"plugin {plugin} offers no actions")
    matches = []
    for copy in _copies(conn, game_id):
        if store is not None and copy["store"] != store:
            continue
        for name, action in _offered({plugin: provider}, copy["store"], str(copy["store_id"])):
            if action.id == action_id:
                matches.append((copy, action))
    if not matches:
        raise LudexError("unknown_action", f"game {game_id} has no action {plugin}:{action_id}" + (f" for store {store}" if store else ""))
    if len({m[0]["store"] for m in matches}) > 1:
        raise LudexError("action_ambiguous", f"action {plugin}:{action_id} is offered for several stores of game {game_id}; pass --store")
    copy, action = matches[0]
    info = ActionInfo(plugin, action.id, action.label, copy["store"], str(copy["store_id"]))
    argv = [str(a) for a in action.argv]
    if dry_run:
        return info, argv, None
    if not os.access(argv[0], os.X_OK):
        raise LudexError("action_failed", f"action {plugin}:{action_id} cannot run (is {Path(argv[0]).name} installed and executable?)")
    target = f"{plugin}:{action_id}:{copy['store']}:{copy['store_id']}"
    return info, argv, start_job(conn, "action", game_id, target, get_game(conn, game_id)["title"], argv, log_dir)
