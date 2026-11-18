from __future__ import annotations

import time

import pytest

from ludex.errors import LudexError
from ludex.services import service_status, start_service, stop_service
from ludex.storage import connect


@pytest.fixture
def conn(tmp_path):
    connection = connect(tmp_path / "db.sqlite3")
    yield connection
    connection.close()


def test_start_is_exclusive_and_stop_ends_it(conn):
    service = start_service(conn, "demo", "loop", ["/bin/sh", "-c", "sleep 60"], settle=0.3)
    assert service.running and service.pid
    with pytest.raises(LudexError) as error:
        start_service(conn, "demo", "loop", ["/bin/sh", "-c", "sleep 60"], settle=0.1)
    assert error.value.code == "service_running"
    assert stop_service(conn, "demo", "loop") is True
    assert service_status(conn, "demo", "loop").running is False
    assert stop_service(conn, "demo", "loop") is False


def test_a_service_that_exits_at_startup_is_reported(conn):
    with pytest.raises(LudexError) as error:
        start_service(conn, "demo", "dies", ["/bin/sh", "-c", "exit 4"], settle=0.5)
    assert error.value.code == "service_exited" and "status 4" in error.value.message


def test_invalid_names_and_commands_are_refused(conn):
    for name, argv in (("Bad Name", ["/bin/sleep", "1"]), ("ok", ["sleep", "1"]), ("ok", [])):
        with pytest.raises(LudexError) as error:
            start_service(conn, "demo", name, argv, settle=0.1)
        assert error.value.code == "invalid_service"


def test_output_goes_to_a_log_beside_the_database(conn, tmp_path):
    start_service(conn, "demo", "say", ["/bin/sh", "-c", "echo hello-service; sleep 60"], settle=0.5)
    try:
        log = service_status(conn, "demo", "say").log
        assert log.parent == tmp_path / "logs"
        deadline = time.monotonic() + 3
        while "hello-service" not in log.read_text() and time.monotonic() < deadline:
            time.sleep(0.1)
        assert "hello-service" in log.read_text()
    finally:
        stop_service(conn, "demo", "say")
