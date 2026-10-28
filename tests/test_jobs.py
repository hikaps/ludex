from __future__ import annotations

import os
import signal
import time

import pytest

from ludex.errors import LudexError
from ludex.jobs import last_line, list_jobs, start_job, stop_job
from ludex.library import import_account
from ludex.plugins import OwnedGame
from ludex.storage import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "db.sqlite3")
    import_account(connection, "main", [OwnedGame("epic", "Quail", "Quail"), OwnedGame("epic", "Owl", "Owl")], store="epic")
    yield connection
    connection.close()


def settle(conn, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = next(j for j in list_jobs(conn) if j.id == job_id)
        if job.state != "running":
            return job
        time.sleep(0.1)
    raise AssertionError("the job did not end")


def test_exit_status_decides_done_or_failed_and_the_log_is_private(conn, tmp_path):
    ok = start_job(conn, "install", 1, "epic:Quail", "Quail", ["/bin/sh", "-c", "echo hello; exit 0"], tmp_path / "logs")
    bad = start_job(conn, "install", 2, "epic:Owl", "Owl", ["/bin/sh", "-c", "echo oops >&2; exit 3"], tmp_path / "logs")
    assert (settle(conn, ok.id).state, settle(conn, ok.id).exit_code) == ("done", 0)
    failed = settle(conn, bad.id)
    assert (failed.state, failed.exit_code) == ("failed", 3) and "oops" in failed.log.read_text()
    assert oct(ok.log.stat().st_mode & 0o777) == "0o600" and not list((tmp_path / "logs").glob("*.exit"))


def test_stop_ends_the_whole_process_group_and_a_second_start_is_refused_while_it_runs(conn, tmp_path):
    job = start_job(conn, "install", 1, "epic:Quail", "Quail", ["/bin/sh", "-c", "sleep 60 & wait"], tmp_path / "logs")
    with pytest.raises(LudexError) as info:
        start_job(conn, "install", 1, "epic:Quail", "Quail", ["/bin/true"], tmp_path / "logs")
    assert info.value.code == "job_running"
    assert [j.id for j in list_jobs(conn, running=True)] == [job.id]
    assert stop_job(conn, job.id).state == "stopped"
    with pytest.raises(ProcessLookupError):
        os.killpg(job.pid, 0)  # the group is gone, sleep included
    with pytest.raises(LudexError) as info:
        stop_job(conn, job.id)
    assert info.value.code == "job_not_running"
    assert start_job(conn, "install", 1, "epic:Quail", "Quail", ["/bin/true"], tmp_path / "logs").id != job.id  # free again


def test_a_job_killed_from_outside_is_lost_not_running_forever(conn, tmp_path):
    job = start_job(conn, "install", 1, "epic:Quail", "Quail", ["/bin/sh", "-c", "sleep 60"], tmp_path / "logs")
    os.killpg(job.pid, signal.SIGKILL)
    assert settle(conn, job.id).state == "lost"


def test_last_line_shows_the_newest_progress_without_colour_codes(conn, tmp_path):
    job = start_job(conn, "install", 1, "epic:Quail", "Quail", ["/bin/sh", "-c", "printf 'start\\n\\033[1mProgress: 10%%\\033[0m\\rProgress: 55%%\\r'"], tmp_path / "logs")
    settle(conn, job.id)
    assert last_line(job) == "Progress: 55%"
