from __future__ import annotations

import importlib.metadata

import pytest

import ludex
from ludex.cli import main


def test_version_matches_installed_metadata(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    out = capsys.readouterr().out
    assert out == f"ludex {importlib.metadata.version('ludex')}\n"
    assert out == f"ludex {ludex.__version__}\n"


def test_no_command_prints_help_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 2
    assert "usage: ludex" in capsys.readouterr().err
