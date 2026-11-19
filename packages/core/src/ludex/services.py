"""Plugin-facing API for long-running background processes (a server, a beacon). It adds no daemon.

A service is a ``service`` job (see :mod:`ludex.jobs`) with ``game_id`` 0 and target ``<provider>:<name>``:
detached in its own session, output in a private log under the state directory, state derived on every read.
One service of a given provider and name runs at a time.
"""
from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .errors import LudexError
from .jobs import Job, get_job, list_jobs, refresh, start_job, stop_job

_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_PROVIDER = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")  # no "_": the log name joins provider and name with one, so it stays unambiguous


@dataclass(frozen=True, slots=True)
class Service:
    provider: str
    name: str
    running: bool
    pid: int | None  # the job's ``sh`` wrapper, leader of the process group; None when not running
    log: Path | None  # the newest run's log, kept after it ends; None if never started
    started_at: str | None  # the newest run's start; None if never started


def _target(provider: str, name: str) -> str:
    if not _PROVIDER.match(provider) or not _NAME.match(name):
        raise LudexError("invalid_service", "provider names are lowercase letters, digits and '-'; service names also allow '_'")
    return f"{provider}:{name}"


def _log_dir(conn: sqlite3.Connection) -> Path:
    database = conn.execute("PRAGMA database_list").fetchone()[2]
    if not database:
        raise LudexError("invalid_service", "services need a library database on disk")
    return Path(database).parent / "logs"


def _newest(conn: sqlite3.Connection, target: str) -> Job | None:
    jobs = list_jobs(conn, "service", limit=1, target=target)
    return jobs[0] if jobs else None


def _service(provider: str, name: str, job: Job | None) -> Service:
    if job is None:
        return Service(provider, name, False, None, None, None)
    running = job.state == "running"
    return Service(provider, name, running, job.pid if running else None, job.log, job.started_at)


def service_status(conn: sqlite3.Connection, provider: str, name: str) -> Service:
    return _service(provider, name, _newest(conn, _target(provider, name)))


def start_service(
    conn: sqlite3.Connection, provider: str, name: str, argv: Sequence[str], *, cwd: Path | None = None, settle: float = 1.0,
) -> Service:
    """Start ``argv`` (absolute ``argv[0]``, no shell) as a service and watch it for up to ``settle`` seconds.

    Raises ``service_exited`` if it ends within that time. The one-at-a-time check is not atomic: run this under the
    writer lock (plugin commands already do), or two callers can both start one.
    """
    target = _target(provider, name)
    if not argv or not Path(argv[0]).is_absolute():
        raise LudexError("invalid_service", "a service command needs an absolute argv[0]")
    log_dir = _log_dir(conn)
    current = _newest(conn, target)
    if current is not None and current.state == "running":
        raise LudexError("service_running", f"{provider} {name} is already running (pid {current.pid})")
    job = start_job(conn, "service", 0, target, f"{provider} {name}", list(argv), log_dir, cwd)
    deadline = time.monotonic() + settle
    while True:
        refresh(conn)
        job = get_job(conn, job.id)
        if job.state != "running" or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    if job.state != "running":
        raise LudexError("service_exited", f"{provider} {name} exited at startup (status {job.exit_code}); log: {job.log}")
    return _service(provider, name, job)


def stop_service(conn: sqlite3.Connection, provider: str, name: str) -> bool:
    """End the service's whole process group; ``False`` when it was not running."""
    job = _newest(conn, _target(provider, name))
    if job is None or job.state != "running":
        return False
    try:
        stop_job(conn, job.id)
    except LudexError as exc:
        if exc.code == "job_not_running":  # it ended on its own just now
            return False
        raise
    return True
