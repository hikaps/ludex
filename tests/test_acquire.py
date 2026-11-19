from __future__ import annotations

from pathlib import Path

import pytest

from ludex.acquire import acquire_game
from ludex.errors import LudexError
from ludex.plugins import AcquireRequest, AcquireResult, Provider, SourceError


def _provider(fn):
    return {"demo": Provider("demo", "d", (), acquire=fn)}


def test_acquire_returns_the_verified_directory_and_hints_and_reports_progress(tmp_path):
    seen = []

    def fn(request, report):
        report("working")
        game = request.destination / request.title
        game.mkdir()
        return AcquireResult(game, {"executable": "run.sh"})

    result = acquire_game(_provider(fn), "demo", "42", "Hades", tmp_path / "out", seen.append)
    assert (result.directory, dict(result.hints), seen) == ((tmp_path / "out" / "Hades").resolve(), {"executable": "run.sh"}, ["working"])


@pytest.mark.parametrize("make", [
    lambda request: AcquireResult(request.destination.parent),  # outside the destination
    lambda request: AcquireResult(request.destination / "missing"),  # does not exist
    lambda request: AcquireResult(request.destination, {"k": 1}),  # bad hints
    lambda request: None,  # wrong type
])
def test_acquire_rejects_results_outside_or_malformed(tmp_path, make):
    with pytest.raises(LudexError) as info:
        acquire_game(_provider(lambda request, report: make(request)), "demo", "1", "x", tmp_path)
    assert info.value.code == "acquire_failed"


def test_acquire_error_mapping_and_missing_capability(tmp_path):
    def boom(request, report):
        raise RuntimeError("secret token abc")

    with pytest.raises(LudexError) as info:
        acquire_game(_provider(boom), "demo", "1", "x", tmp_path)
    assert info.value.message == "provider demo failed (RuntimeError)"

    def known(request, report):
        raise SourceError("no_access", "not entitled")

    with pytest.raises(LudexError) as info:
        acquire_game(_provider(known), "demo", "1", "x", tmp_path)
    assert (info.value.code, info.value.message) == ("no_access", "not entitled")
    for providers in ({}, {"demo": Provider("demo", "d", (), launch_url=str)}):
        with pytest.raises(LudexError) as info:
            acquire_game(providers, "demo", "1", "x", tmp_path)
        assert info.value.code == "not_acquirable"


def test_the_detached_worker_acquires_into_the_destination_and_reports_failures(tmp_path, monkeypatch, capsys):
    from ludex import _acquire_worker

    def fn(request, report):
        report("half", 1, 2)
        game = request.destination / "game"
        game.mkdir()
        return AcquireResult(game, {"executable": "run.sh"})

    monkeypatch.setattr(_acquire_worker, "load_providers", lambda: (_provider(fn), {}))
    assert _acquire_worker.main(["demo", "7", "--to", str(tmp_path / "dl")]) == 0
    captured = capsys.readouterr()
    assert captured.out == f"acquired into {(tmp_path / 'dl' / 'game').resolve()}\n  executable=run.sh\n"
    assert "half 50%" in captured.err
    assert _acquire_worker.main(["nope", "7", "--to", str(tmp_path / "dl")]) == 1
    assert capsys.readouterr().err == "error: provider nope cannot acquire games\n"
