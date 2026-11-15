"""Run a provider's acquire capability and check what it returns."""
from __future__ import annotations

import sqlite3
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from .errors import LudexError
from .jobs import Job, start_job
from .plugins import AcquireRequest, AcquireResult, Provider


def acquire_game(
    providers: Mapping[str, Provider],
    store: str,
    store_id: str,
    title: str,
    destination: Path,
    report: Callable[[str], None] = lambda message: None,
) -> AcquireResult:
    """Ask ``store``'s provider to put the game under ``destination``; the result is verified."""
    provider = providers.get(store)
    if provider is None or provider.acquire is None:
        raise LudexError("not_acquirable", f"provider {store} cannot acquire games")
    destination = destination.expanduser()
    try:
        destination.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise LudexError("destination_unwritable", "the destination directory cannot be created") from None
    root = destination.resolve()
    try:
        result = provider.acquire(AcquireRequest(store_id, title, root), report)
    except LudexError:
        raise
    except Exception as exc:
        raise LudexError("acquire_failed", f"provider {store} failed ({type(exc).__name__})") from None
    if (
        not isinstance(result, AcquireResult)
        or not isinstance(result.directory, Path)
        or not isinstance(result.hints, Mapping)
        or not all(isinstance(k, str) and isinstance(v, str) for k, v in result.hints.items())
    ):
        raise LudexError("acquire_failed", f"provider {store} returned an invalid result")
    directory = result.directory.resolve()
    if not directory.is_dir() or not directory.is_relative_to(root):
        raise LudexError("acquire_failed", f"provider {store} returned a directory outside the destination")
    return AcquireResult(directory, dict(result.hints))


def download_game(
    conn: sqlite3.Connection, providers: Mapping[str, Provider], store: str, store_id: str, title: str, destination: Path, log_dir: Path
) -> Job:
    """Run :func:`acquire_game` in the background as a ``download`` job (see ``ludex.jobs``): ``ludex acquire`` in its own process.

    The game is not in the library yet, so the job has no game (``game_id`` 0). One running download per ``store:store_id``.
    """
    provider = providers.get(store)
    if provider is None or provider.acquire is None:
        raise LudexError("not_acquirable", f"provider {store} cannot acquire games")
    argv = [sys.executable, "-m", "ludex", "acquire", store, store_id, "--to", str(destination.expanduser())]
    if title:
        argv += ["--title", title]
    return start_job(conn, "download", 0, f"{store}:{store_id}", title or store_id, argv, log_dir)
