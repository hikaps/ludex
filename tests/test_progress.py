from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ludex import acquire as acquire_mod
from ludex.jobs import PROGRESS_ENV, Job, ProgressWriter, eta_seconds, format_eta, progress, progress_line, progress_path, start_job
from ludex.storage import connect


def running_job(tmp_path: Path, started_ago: float = 100.0) -> Job:
    started = datetime.fromtimestamp(time.time() - started_ago, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return Job(1, "download", 0, "rel:1", "Doom", 1, tmp_path / "download-rel_1.log", started, None, "running", None)


def test_a_report_with_numbers_gives_a_percentage_and_a_time_estimate(tmp_path):
    job = running_job(tmp_path, started_ago=100)
    ProgressWriter(progress_path(job.log))("fetching", 25, 100)
    report = progress(job)
    assert (report.message, report.fraction) == ("fetching", 0.25)
    assert 290 <= eta_seconds(job, report) <= 310  # a quarter in 100 s: about 300 s left
    line = progress_line(job)
    assert line.startswith("fetching  25%  ") and line.endswith(" left")
    assert [format_eta(s) for s in (45, 125, 3725)] == ["45s", "2m 05s", "1h 02m"]


def test_bad_numbers_are_dropped_but_the_message_is_kept_and_progress_ends_with_the_job(tmp_path):
    job = running_job(tmp_path)
    write = ProgressWriter(progress_path(job.log))
    for bad in ((-1, 10), (5, 0), (float("nan"), 10), (True, 10), (5, None), ("5", "10")):
        write("unpacking", *bad)
        report = progress(job)
        assert report.message == "unpacking" and report.fraction is None, bad
    write("over", 150, 100)
    assert progress(job).fraction == 1.0  # never more than 100%
    progress_path(job.log).write_text("not json")
    assert progress(job) is None
    progress_path(job.log).write_text(json.dumps({"message": ["x"], "at": 1}))
    assert progress(job) is None
    (tmp_path / "download-rel_1.log").write_text("line one\nplain log line\n")
    assert progress_line(job) == "plain log line"  # no usable report: the log's newest line
    write("late", 1, 2)
    ended = Job(job.id, job.kind, job.game_id, job.target, job.title, job.pid, job.log, job.started_at, job.started_at, "done", 0)
    assert progress(ended) is None


def test_a_plugin_reporting_in_a_tight_loop_writes_a_few_times_and_always_the_last(tmp_path):
    path = tmp_path / "p.progress"
    write = ProgressWriter(path)
    writes = 0
    for done in range(0, 1001):
        before = path.stat().st_mtime_ns if path.exists() else None
        write("x", done, 1000)
        writes += (path.stat().st_mtime_ns != before) if before is not None else 1
    assert writes < 50 and json.loads(path.read_text())["done"] == 1000


def test_the_job_reporter_echoes_percentages_and_feeds_the_progress_file(tmp_path, monkeypatch):
    path = tmp_path / "j.progress"
    monkeypatch.setenv(PROGRESS_ENV, str(path))
    lines = []
    report = acquire_mod.job_reporter(lines.append)
    report("plain")
    report("half", 50, 100)
    assert lines == ["plain", "half 50%"]
    assert json.loads(path.read_text())["done"] == 50
    monkeypatch.delenv(PROGRESS_ENV)
    acquire_mod.job_reporter(lines.append)("no file", 1, 2)  # outside a download job: only the echo
    assert lines[-1] == "no file 50%"


def test_a_download_job_gets_its_progress_file_and_a_resume_starts_clean(tmp_path):
    conn = connect(tmp_path / "db.sqlite3")
    logs = tmp_path / "logs"
    script = 'echo "$LUDEX_PROGRESS_FILE" > "$1"; sleep 30'
    marker = tmp_path / "env.txt"
    job = start_job(conn, "download", 0, "rel:1", "Doom", ["/bin/sh", "-c", script, "x", str(marker)], logs)
    for _ in range(50):
        if marker.exists() and marker.read_text().strip():
            break
        time.sleep(0.1)
    assert marker.read_text().strip() == str(progress_path(job.log))
    ProgressWriter(progress_path(job.log))("old run", 1, 2)
    from ludex.jobs import stop_job

    stop_job(conn, job.id)
    again = start_job(conn, "download", 0, "rel:1", "Doom", ["/bin/sh", "-c", "sleep 30"], logs)
    assert progress(again) is None  # the last run's report is gone
    stop_job(conn, again.id)
