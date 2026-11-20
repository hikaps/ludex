"""Run a provider's acquire capability and check what it returns."""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path

from .errors import LudexError
from .jobs import PROGRESS_ENV, Job, ProgressWriter, start_job
from .plugins import AcquireRequest, AcquireResult, Provider, Report


def acquire_game(
    providers: Mapping[str, Provider],
    store: str,
    store_id: str,
    title: str,
    destination: Path,
    report: Report = lambda message, done=None, total=None: None,
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
    argv = [sys.executable, "-m", "ludex._acquire_worker", store, store_id, "--to", str(destination.expanduser())]
    if title:
        argv += ["--title", title]
    return start_job(conn, "download", 0, f"{store}:{store_id}", title or store_id, argv, log_dir)


def format_acquired(result: AcquireResult) -> str:
    """The human line for a finished acquisition: the directory, then the sorted hints."""
    hints = "".join(f"\n  {key}={value}" for key, value in sorted(result.hints.items()))
    return f"acquired into {result.directory}{hints}"


def job_reporter(echo: Callable[[str], None]) -> Report:
    """The ``report`` for ``ludex acquire``: each report goes to ``echo`` (the job's log) and, inside a download job, to its progress file."""
    path = os.environ.get(PROGRESS_ENV)
    writer = ProgressWriter(Path(path)) if path else None
    last = [0.0]

    def report(message: str, done: float | None = None, total: float | None = None) -> None:
        if writer is not None:
            writer(message, done, total)
        if done is not None and total and done < total:
            if time.time() - last[0] < 0.25:
                return  # a plugin may report on every chunk; the log gets a few lines a second at most
            last[0] = time.time()
        percent = f" {int(min(done, total) / total * 100)}%" if isinstance(done, (int, float)) and isinstance(total, (int, float)) and total > 0 else ""
        echo(f"{message}{percent}")

    return report
