"""Background jobs: processes ludex starts for the user (an install today) and can report on and stop.

A job is one row in ``jobs`` plus a log file under ``<state>/logs``. The command runs detached in its own
session, wrapped in ``sh`` so its exit status lands in a small file; ludex does not stay alive to wait for it.
State is derived on every read: a live process whose start time matches the recorded one is ``running``;
otherwise the exit file says ``done`` (0) or ``failed`` (anything else), and no file means ``lost`` (the
machine rebooted or the process was killed from outside). ``stopped`` is only set by :func:`stop_job`.
ponytail: Linux and macOS via ``ps``; one row per run, never pruned; a daemon replaces the polling later.
"""
from __future__ import annotations

import os
import re
import signal
import sqlite3
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from .errors import LudexError
from .storage import utc_now

_children: list[subprocess.Popen] = []  # started by this process: polled so they do not stay zombies
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass(frozen=True, slots=True)
class Job:
    id: int
    kind: str
    game_id: int
    target: str
    title: str
    pid: int
    log: Path
    started_at: str
    ended_at: str | None
    state: str
    exit_code: int | None


_COLUMNS = "id, kind, game_id, target, title, pid, log, started_at, ended_at, state, exit_code"


def _job(row: sqlite3.Row) -> Job:
    return Job(row["id"], row["kind"], row["game_id"], row["target"], row["title"], row["pid"], Path(row["log"]),
               row["started_at"], row["ended_at"], row["state"], row["exit_code"])


def _token(pid: int) -> str | None:
    """The process's start time as ``ps`` prints it, or ``None`` when it is gone (a zombie counts as gone)."""
    try:
        out = subprocess.run(["ps", "-o", "stat=,lstart=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout.split(None, 1)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out[1].strip() if len(out) == 2 and not out[0].startswith("Z") else None


def _alive(pid: int, token: str) -> bool:
    now = _token(pid)
    return now is not None and (not token or now == token)


def refresh(conn: sqlite3.Connection) -> None:
    """Settle every job whose process has ended."""
    _children[:] = [c for c in _children if c.poll() is None]
    for row in conn.execute("SELECT id, pid, pid_start, exit_file FROM jobs WHERE state = 'running'").fetchall():
        if _alive(row["pid"], row["pid_start"]):
            continue
        exit_file = Path(row["exit_file"])
        try:
            code = int(exit_file.read_text().strip())
        except (OSError, ValueError):
            code = None
        exit_file.unlink(missing_ok=True)
        state = "lost" if code is None else "done" if code == 0 else "failed"
        with conn:
            conn.execute("UPDATE jobs SET state = ?, exit_code = ?, ended_at = ? WHERE id = ?", (state, code, utc_now(), row["id"]))


def start_job(conn: sqlite3.Connection, kind: str, game_id: int, target: str, title: str, argv: list[str], log_dir: Path) -> Job:
    """Run ``argv`` (no shell) in the background; its output goes to a private log. One running job per kind and target."""
    refresh(conn)
    busy = conn.execute("SELECT id FROM jobs WHERE kind = ? AND target = ? AND state = 'running'", (kind, target)).fetchone()
    if busy:
        raise LudexError("job_running", f"{kind} of {target} is already running (job {busy['id']}); see 'ludex {kind} --status'")
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", f"{kind}-{target}")
    log, exit_file = log_dir / f"{safe}.log", log_dir / f"{safe}-{uuid.uuid4().hex[:8]}.exit"
    try:
        with open(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600), "ab", closefd=True) as out:
            process = subprocess.Popen(
                ["/bin/sh", "-c", '"$@"; echo $? > "$0"', str(exit_file), *argv],
                start_new_session=True, stdin=subprocess.DEVNULL, stdout=out, stderr=out,
            )
    except OSError:
        raise LudexError(f"{kind}_failed", "the command could not be started") from None
    _children.append(process)
    with conn:
        cursor = conn.execute(
            "INSERT INTO jobs(kind, game_id, target, title, pid, pid_start, log, exit_file, started_at, state) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')",
            (kind, game_id, target, title, process.pid, _token(process.pid) or "", str(log), str(exit_file), utc_now()),
        )
    return get_job(conn, cursor.lastrowid)


def get_job(conn: sqlite3.Connection, job_id: int) -> Job:
    row = conn.execute(f"SELECT {_COLUMNS} FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise LudexError("job_not_found", f"no job {job_id}")
    return _job(row)


def list_jobs(conn: sqlite3.Connection, kind: str | None = None, game_id: int | None = None, running: bool = False, limit: int = 20) -> list[Job]:
    """Newest first, after settling finished ones."""
    refresh(conn)
    where, params = ["1 = 1"], []
    for clause, value in (("kind = ?", kind), ("game_id = ?", game_id)):
        if value is not None:
            where.append(clause)
            params.append(value)
    if running:
        where.append("state = 'running'")
    rows = conn.execute(f"SELECT {_COLUMNS} FROM jobs WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    return [_job(r) for r in rows]


def stop_job(conn: sqlite3.Connection, job_id: int) -> Job:
    """End a running job: SIGTERM to its whole process group, SIGKILL after 10 seconds."""
    refresh(conn)
    row = conn.execute("SELECT pid, pid_start, exit_file, state FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise LudexError("job_not_found", f"no job {job_id}")
    if row["state"] != "running" or not _alive(row["pid"], row["pid_start"]):
        raise LudexError("job_not_running", f"job {job_id} is not running")
    deadline = time.monotonic() + 10
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(row["pid"], sig)
        except ProcessLookupError:
            break
        except PermissionError:
            raise LudexError("job_stop_failed", f"job {job_id} could not be stopped") from None
        while time.monotonic() < deadline and _alive(row["pid"], row["pid_start"]):
            time.sleep(0.2)
        if not _alive(row["pid"], row["pid_start"]):
            break
        deadline = time.monotonic() + 3
    _children[:] = [c for c in _children if c.poll() is None]
    Path(row["exit_file"]).unlink(missing_ok=True)
    with conn:
        conn.execute("UPDATE jobs SET state = 'stopped', ended_at = ? WHERE id = ?", (utc_now(), job_id))
    return get_job(conn, job_id)


def last_line(job: Job) -> str:
    """The newest non-empty line of the job's log (progress bars rewrite one line, so ``\\r`` splits too)."""
    try:
        with open(job.log, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - 4096))
            text = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    lines = [line.strip() for line in re.split(r"[\r\n]+", _ANSI.sub("", text)) if line.strip()]
    return lines[-1][:100] if lines else ""
