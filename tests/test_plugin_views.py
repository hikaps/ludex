from __future__ import annotations

import json
from pathlib import Path

import pytest

from ludex.errors import LudexError
from ludex.loader import load_providers
from ludex.paths import state_paths
from ludex.plugin_views import fetch_view, get_view, list_views, run_view_action
from ludex.plugins import (
    Command,
    CommandResult,
    ConfigField,
    Provider,
    View,
    ViewAction,
    ViewDetail,
    ViewRow,
    ViewTable,
)
from ludex.provider_settings import set_value
from ludex_cli.cli import main

SECRET = "sk-sentinel-secret"


class _Entry:
    def __init__(self, name: str, value: object) -> None:
        self.name = name
        self.value = value
        self.loaded = False

    def load(self) -> object:
        self.loaded = True
        return self.value


def _table(rows: tuple[ViewRow, ...] = (), columns: tuple[str, ...] = ("Name",)) -> View:
    return View("people", "People", lambda settings: ViewTable(columns, rows))


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("LUDEX_HOME", str(home))
    return state_paths()


def _demo(*views: View, commands: tuple[Command, ...] = ()) -> Provider:
    return Provider("demo", "Demo", (), views=views, commands=commands, settings=(ConfigField("region", "r", optional=True),))


def test_a_view_only_provider_loads_without_fetching_and_bad_views_skip_only_that_plugin() -> None:
    calls: list[int] = []
    good = Provider("good", "g", (), views=(View("people", "People", lambda s: calls.append(1) or ViewDetail()),))
    dup = Provider("dup", "d", (), views=(_table(), _table()))
    untitled = Provider("untitled", "u", (), views=(View("x", "two\nlines", lambda s: ViewDetail()),))
    not_callable = Provider("nocall", "n", (), views=(View("x", "X", None),))  # type: ignore[arg-type]
    shouting = Provider("shout", "s", (), views=(View("Bad_Id", "X", lambda s: ViewDetail()),))
    entries = [_Entry(p.name, p) for p in (good, dup, untitled, not_callable, shouting)]
    loaded, problems = load_providers(entries)  # type: ignore[arg-type]
    assert list(loaded) == ["good"] and loaded["good"].capabilities == ("views",)
    assert set(problems) == {"dup", "untitled", "nocall", "shout"}
    assert all("invalid view" in reason for reason in problems.values())
    assert calls == []
    assert list_views(loaded) == (("good", good.views[0]),)


def test_get_view_reports_unknown_provider_and_view() -> None:
    providers = {"demo": _demo(_table())}
    assert get_view(providers, "demo", "people").title == "People"
    with pytest.raises(LudexError) as unknown:
        get_view(providers, "nope", "people")
    assert unknown.value.code == "unknown_provider"
    with pytest.raises(LudexError) as missing:
        get_view(providers, "demo", "nope")
    assert missing.value.code == "unknown_view"


def test_fetch_rejects_malformed_snapshots_and_foreign_commands(paths) -> None:
    ok = Command("go", "g", lambda ctx, args: CommandResult(None))
    cases = {
        "foreign command": ViewTable(("A",), (ViewRow("r", ("x",), (ViewAction("Go", "other"),)),)),
        "cell count": ViewTable(("A", "B"), (ViewRow("r", ("x",)),)),
        "duplicate row": ViewTable(("A",), (ViewRow("r", ("x",)), ViewRow("r", ("y",)))),
        "no columns": ViewTable(()),
        "control in cell": ViewTable(("A",), (ViewRow("r", ("\x1b[31mred",)),)),
        "non-string cell": ViewTable(("A",), (ViewRow("r", (1,)),)),  # type: ignore[arg-type]
        "list args": ViewTable(("A",), (ViewRow("r", ("x",), (ViewAction("Go", "go", ["a"]),)),)),  # type: ignore[arg-type]
        "multiline label": ViewDetail((("a\nb", "v"),)),
        "not a record": {"columns": []},
    }
    for label, result in cases.items():
        provider = _demo(View("v", "V", lambda s, r=result: r), commands=(ok,))
        with pytest.raises(LudexError) as caught:
            fetch_view(paths, provider, provider.views[0])
        assert caught.value.code == "invalid_view_result", label
    multiline = _demo(View("v", "V", lambda s: ViewDetail((("Log", "a\nb"),))))
    assert fetch_view(paths, multiline, multiline.views[0]).fields == (("Log", "a\nb"),)


def test_fetch_hides_plugin_exception_text_and_keeps_ludex_errors(paths) -> None:
    def leak(settings):
        raise RuntimeError(SECRET)

    def known(settings):
        raise LudexError("rate_limited", "try again later")

    for fetch, code in ((leak, "view_failed"), (known, "rate_limited"), (lambda s: (_ for _ in ()).throw(SystemExit(SECRET)), "view_failed")):
        provider = _demo(View("v", "V", fetch))
        with pytest.raises(LudexError) as caught:
            fetch_view(paths, provider, provider.views[0])
        assert caught.value.code == code and SECRET not in caught.value.message


def test_fetch_reads_the_plugin_settings_each_time(paths) -> None:
    provider = _demo(View("v", "V", lambda s: ViewDetail((("Region", s.get("region", "-")),))))
    assert fetch_view(paths, provider, provider.views[0]).fields == (("Region", "-"),)
    set_value(paths, provider, "region", "eu")
    assert fetch_view(paths, provider, provider.views[0]).fields == (("Region", "eu"),)


def test_run_view_action_runs_only_the_providers_command_with_its_args(paths) -> None:
    seen: list[tuple[str, ...]] = []

    def run(ctx, args):
        seen.append(tuple(args))
        return CommandResult({"ok": True}, "marked")

    def quits(ctx, args):
        raise SystemExit(SECRET)

    provider = _demo(commands=(Command("mark", "m", run), Command("quit", "q", quits)))
    providers = {"demo": provider}
    assert run_view_action(paths, providers, "demo", ViewAction("Mark", "mark", ("alice", "away"))).text == "marked"
    assert seen == [("alice", "away")]
    for action, provider_key, code in ((ViewAction("X", "gone"), "demo", "unknown_command"), (ViewAction("X", "mark"), "nope", "unknown_provider"), (ViewAction("Q", "quit"), "demo", "command_failed")):
        with pytest.raises(LudexError) as caught:
            run_view_action(paths, providers, provider_key, action)
        assert caught.value.code == code and SECRET not in caught.value.message


@pytest.fixture
def cli_world(paths, monkeypatch: pytest.MonkeyPatch):
    people = View("people", "People", lambda s: ViewTable(("Name", "State"), (ViewRow("alice", ("Alice", "online"), (ViewAction("Away", "mark", ("alice",)),)), ViewRow("bob", ("Bob", "away")))))
    status = View("status", "Status", lambda s: ViewDetail((("State", "Ready"), ("Notes", "a\nb"))))
    empty = View("empty", "Empty", lambda s: ViewTable(("Name",)))
    commands = (Command("view", "own view command", lambda ctx, args: CommandResult({"ran": list(args)}, "ran view")), Command("mark", "mark", lambda ctx, args: CommandResult(None)))
    provider = Provider("demo", "Demo", (), views=(people, status, empty), commands=commands)
    monkeypatch.setattr("ludex_cli.cli.load_providers", lambda: ({"demo": provider}, {}))
    return provider


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_plugin_view_lists_prints_tables_and_details(cli_world, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "plugin", "view")
    assert code == 0 and out.splitlines() == ["demo.people  People", "demo.status  Status", "demo.empty  Empty"]
    code, out, _ = _run(capsys, "--json", "plugin", "view", "demo", "people")
    data = json.loads(out)["data"]
    assert code == 0 and data["kind"] == "table" and data["columns"] == ["Name", "State"]
    assert data["rows"][0] == {"id": "alice", "cells": ["Alice", "online"], "actions": [{"label": "Away", "command": "mark"}]}
    assert "alice\"]" not in out  # action args are not emitted
    code, out, _ = _run(capsys, "plugin", "view", "demo", "people")
    assert out.splitlines() == ["Name\tState", "Alice\tonline", "Bob\taway"]
    code, out, _ = _run(capsys, "--json", "plugin", "view", "demo", "status")
    assert json.loads(out)["data"]["fields"] == [["State", "Ready"], ["Notes", "a\nb"]]
    assert _run(capsys, "plugin", "view", "demo", "empty")[1].splitlines() == ["Name", "No results."]


def test_plugin_view_errors_and_empty_lists(cli_world, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = _run(capsys, "--json", "plugin", "view", "nope")
    assert code == 1 and json.loads(err)["error"]["code"] == "unknown_provider"
    code, _, err = _run(capsys, "--json", "plugin", "view", "demo", "nope")
    assert code == 1 and json.loads(err)["error"]["code"] == "unknown_view"
    code, out, _ = _run(capsys, "--json", "providers")
    assert "views" in json.loads(out)["data"]["providers"][0]["capabilities"]


def test_a_provider_command_named_view_still_runs(cli_world, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = _run(capsys, "demo", "view", "x")
    assert (code, out.strip()) == (0, "ran view")
