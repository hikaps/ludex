from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from ludex.actions import list_actions, run_action
from ludex.errors import LudexError
from ludex.jobs import list_jobs
from ludex.library import import_account
from ludex.loader import load_providers
from ludex.plugins import GameAction, OwnedGame, Provider
from ludex.storage import connect

LOGGER = Path(sys.executable)  # any real executable


def plugin(name="couch", actions=None, **kw):
    return Provider(name, "t", (), actions=actions, **kw)


@pytest.fixture
def conn(tmp_path):
    conn = connect(tmp_path / "db.sqlite3")
    import_account(conn, "s", [OwnedGame("steam", "220", "HL2")], store="steam")
    import_account(conn, "h", [OwnedGame("heroic", "abc", "HL2")], store="heroic")
    import_account(conn, "l", [OwnedGame("local", "x", "Other")], store="local")
    return conn


def split(store, store_id):
    if store in ("steam", "heroic"):
        return [GameAction("split-screen", "Play split-screen", [str(LOGGER), "-c", f"print({store!r}, {store_id!r})"])]
    return []


def test_actions_are_offered_per_copy_and_name_the_store_only_when_it_is_ambiguous(conn):
    steam_only = {"couch": plugin(actions=lambda store, store_id: split(store, store_id) if store == "steam" else [])}
    [item] = list_actions(conn, steam_only, 1)
    assert (item.plugin, item.id, item.label, item.store, item.store_id) == ("couch", "split-screen", "Play split-screen", "steam", "220")
    both = {"couch": plugin(actions=split)}
    assert [i.label for i in list_actions(conn, both, 1)] == ["Play split-screen (heroic)", "Play split-screen (steam)"]
    assert list_actions(conn, both, 2) == []  # a game with no offering copy


@pytest.mark.parametrize(
    "bad",
    [
        GameAction("Bad Id", "x", ["/bin/true"]), GameAction("ok", "two\nlines", ["/bin/true"]), GameAction("ok", "x", []),
        GameAction("ok", "x", ["relative"]), GameAction("ok", "x", ["/bin/true", 5]), "not an action",
    ],
)
def test_invalid_actions_and_broken_plugins_are_skipped_not_raised(conn, bad):
    def boom(store, store_id):
        raise RuntimeError("secret")

    sources = {"bad": plugin("bad", actions=lambda s, i: [bad]), "boom": plugin("boom", actions=boom), "fine": plugin("fine", actions=lambda s, i: [GameAction("ok", "Fine", ["/bin/true"])] if s == "steam" else [])}
    assert [(i.plugin, i.label) for i in list_actions(conn, sources, 1)] == [("fine", "Fine")]


def test_run_action_starts_an_action_job_with_the_plugins_argv(conn, tmp_path):
    sources = {"couch": plugin(actions=split)}
    with pytest.raises(LudexError) as caught:
        run_action(conn, sources, 1, "couch", "split-screen", None, tmp_path / "logs")
    assert caught.value.code == "action_ambiguous"
    info, argv, job = run_action(conn, sources, 1, "couch", "split-screen", "steam", tmp_path / "logs", dry_run=True)
    assert job is None and argv[0] == str(LOGGER) and info.store == "steam"
    info, argv, job = run_action(conn, sources, 1, "couch", "split-screen", "heroic", tmp_path / "logs")
    for _ in range(100):
        if list_jobs(conn, "action", 1, running=True) == []:
            break
        time.sleep(0.05)
    [done] = list_jobs(conn, "action", 1)
    assert done.kind == "action" and done.state == "done" and done.target == "couch:split-screen:heroic:abc"
    assert "heroic abc" in done.log.read_text()
    for plugin_name, action_id in (("couch", "nope"), ("missing", "split-screen")):
        with pytest.raises(LudexError) as caught:
            run_action(conn, sources, 1, plugin_name, action_id, "steam", tmp_path / "logs")
        assert caught.value.code == "unknown_action"


def test_run_action_refuses_a_program_that_cannot_run(conn, tmp_path):
    sources = {"couch": plugin(actions=lambda s, i: [GameAction("go", "Go", ["/nonexistent/couchplay-gamemode"])])}
    with pytest.raises(LudexError) as caught:
        run_action(conn, sources, 1, "couch", "go", "steam", tmp_path / "logs")
    assert caught.value.code == "action_failed" and "couchplay-gamemode" in caught.value.message and "/nonexistent" not in caught.value.message


def test_an_actions_function_declaring_settings_gets_the_plugins_settings(monkeypatch, tmp_path):
    from importlib.metadata import EntryPoint

    seen = []
    provider = plugin("couch", actions=lambda store, store_id, settings: seen.append(dict(settings)) or [], settings=())
    module = type(sys)("couchmod")
    module.PLUGIN = provider
    monkeypatch.setitem(sys.modules, "couchmod", module)
    monkeypatch.setenv("LUDEX_HOME", str(tmp_path))
    loaded, problems = load_providers([EntryPoint("couch", "couchmod:PLUGIN", "ludex.providers")])
    assert problems == {} and loaded["couch"].actions("steam", "1") == [] and seen == [{}]
