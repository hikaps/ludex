from __future__ import annotations

import os
import time

import pytest

from ludex.errors import LudexError
from ludex.services import service_status, start_service, stop_service
from ludex.storage import connect

SLEEP = ["/bin/sh", "-c", "sleep 60"]


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "db.sqlite3")
    yield connection
    for provider, name in (("demo", "loop"), ("demo", "say"), ("demo", "cwd"), ("a", "b_c"), ("demo", "old")):
        stop_service(connection, provider, name)  # never leave a detached process behind
    connection.close()


def test_start_is_exclusive_stop_ends_the_whole_group_and_it_can_start_again(conn):
    service = start_service(conn, "demo", "loop", ["/bin/sh", "-c", "sleep 60 & wait"], settle=0.3)
    assert service.running and service.pid
    with pytest.raises(LudexError) as error:
        start_service(conn, "demo", "loop", SLEEP)
    assert error.value.code == "service_running"
    assert stop_service(conn, "demo", "loop") is True
    with pytest.raises(ProcessLookupError):
        os.killpg(service.pid, 0)  # the group is gone, the background sleep included
    assert service_status(conn, "demo", "loop").running is False
    assert stop_service(conn, "demo", "loop") is False
    assert start_service(conn, "demo", "loop", SLEEP, settle=0.2).running


def test_a_service_that_exits_at_startup_is_reported_as_soon_as_it_ends(conn):
    started = time.monotonic()
    with pytest.raises(LudexError) as error:
        start_service(conn, "demo", "dies", ["/bin/sh", "-c", "exit 4"], settle=20)
    assert error.value.code == "service_exited" and "status 4" in error.value.message
    assert time.monotonic() - started < 15


@pytest.mark.parametrize(
    ("provider", "name", "argv"),
    [
        ("demo", "Bad Name", ["/bin/sleep", "1"]),
        ("demo", "ok", ["sleep", "1"]),
        ("demo", "ok", []),
        ("Demo", "ok", ["/bin/sleep", "1"]),
        ("a_b", "ok", ["/bin/sleep", "1"]),
        ("demo", "x" * 33, ["/bin/sleep", "1"]),
        ("demo", "ok\n", ["/bin/sleep", "1"]),
    ],
)
def test_invalid_names_and_commands_are_refused(conn, provider, name, argv):
    with pytest.raises(LudexError) as error:
        start_service(conn, provider, name, argv, settle=0.1)
    assert error.value.code == "invalid_service"


def test_a_name_of_32_characters_is_accepted(conn):
    name = "x" * 32
    try:
        assert start_service(conn, "demo", name, SLEEP, settle=0.1).running
    finally:
        stop_service(conn, "demo", name)


def test_output_goes_to_a_log_beside_the_database(conn, tmp_path):
    start_service(conn, "demo", "say", ["/bin/sh", "-c", "echo hello-service; sleep 60"], settle=0.5)
    log = service_status(conn, "demo", "say").log
    assert log.parent == tmp_path / "logs"
    deadline = time.monotonic() + 3
    while "hello-service" not in log.read_text() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert "hello-service" in log.read_text()


def test_cwd_is_where_the_service_runs(conn, tmp_path):
    folder = tmp_path / "work"
    folder.mkdir()
    start_service(conn, "demo", "cwd", ["/bin/sh", "-c", "pwd; sleep 60"], cwd=folder, settle=0.5)
    log = service_status(conn, "demo", "cwd").log
    deadline = time.monotonic() + 3
    while not log.read_text() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert log.read_text().strip() == str(folder.resolve())


def test_services_of_different_names_never_share_a_log(conn):
    first = start_service(conn, "a", "b_c", SLEEP, settle=0.1)
    second = start_service(conn, "demo", "loop", SLEEP, settle=0.1)
    assert first.log != second.log


def test_an_old_running_service_is_still_found_after_many_newer_service_runs(conn):
    old = start_service(conn, "demo", "old", SLEEP, settle=0.1)
    with conn:
        conn.executemany(
            "INSERT INTO jobs(kind, game_id, target, title, pid, pid_start, log, exit_file, started_at, state) "
            "VALUES ('service', 0, 'demo:other', 'x', 1, '', '/dev/null', '/nonexistent', '2000-01-01T00:00:00Z', 'done')",
            [()] * 1001,
        )
    assert service_status(conn, "demo", "old").pid == old.pid
    assert stop_service(conn, "demo", "old") is True
