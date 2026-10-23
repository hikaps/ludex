from __future__ import annotations

import io
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from ludex.cli import main
from ludex.plugins import ConfigField, FetchResult, OwnedGame, SourceError, SourcePlugin
from ludex.storage import writer_lock

SECRET = "hunter2-very-secret"


class World:
    """Mutable fake store catalogs keyed by the account's `user` config value."""

    def __init__(self) -> None:
        self.catalogs: dict[str, list[tuple[str, str]]] = {}
        self.failing: set[str] = set()
        self.seen_config: list[dict[str, str]] = []

    def fetch(self, config: Any) -> list[OwnedGame]:
        self.seen_config.append(dict(config))
        user = config["user"]
        if user in self.failing:
            raise SourceError("fetch_incomplete", "profile is private")
        return [OwnedGame("fake", store_id, title) for store_id, title in self.catalogs.get(user, [])]


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    home = tmp_path / "home"
    home.mkdir()
    home.chmod(0o700)
    monkeypatch.setenv("LUDEX_HOME", str(home))
    w = World()
    plugin = SourcePlugin(
        name="fake",
        help="Fake store",
        config_fields=(ConfigField("user", "account user"), ConfigField("key", "API key", secret=True)),
        fetch=lambda config: FetchResult(w.fetch(config), True, "fake"),
    )
    monkeypatch.setattr("ludex.cli.load_sources", lambda: ({"fake": plugin}, {"broken": "failed to import"}))
    return w


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def add(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, name: str, user: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, _, err = run(capsys, "account", "add", "fake", name, "--set", f"user={user}")
    assert code == 0, err


def test_sources_lists_plugins_and_problems(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--json", "sources")
    assert code == 0
    data = json.loads(out)
    assert data == {
        "ok": True,
        "data": {
            "sources": [
                {
                    "name": "fake",
                    "help": "Fake store",
                    "fields": [
                        {"name": "user", "help": "account user", "secret": False, "optional": False},
                        {"name": "key", "help": "API key", "secret": True, "optional": False},
                    ],
                }
            ],
            "problems": {"broken": "failed to import"},
        },
    }
    code, out, _ = run(capsys, "sources")
    assert code == 0 and "fake" in out and "broken" in out


def test_account_add_reads_secret_from_stdin_and_never_echoes_it(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, out, err = run(capsys, "account", "add", "fake", "main", "--set", "user=alice")
    assert code == 0
    assert SECRET not in out + err
    accounts_file = tmp_path / "home" / "accounts.json"
    assert stat.S_IMODE(accounts_file.stat().st_mode) == 0o600
    assert json.loads(accounts_file.read_text())["fake:main"] == {"source": "fake", "config": {"user": "alice", "key": SECRET}}
    for argv in (("account", "ls"), ("--json", "account", "ls"), ("--json", "sources")):
        code, out, err = run(capsys, *argv)
        assert code == 0
        assert SECRET not in out + err
    code, out, _ = run(capsys, "--json", "account", "ls")
    assert json.loads(out) == {"ok": True, "data": {"accounts": [{"name": "main", "source": "fake"}]}}


def test_account_add_json_output_has_no_secret(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, out, err = run(capsys, "--json", "account", "add", "fake", "main", "--set", "user=alice")
    assert code == 0
    assert json.loads(out) == {"ok": True, "data": {"account": "main", "source": "fake"}}
    assert SECRET not in out + err


def test_account_add_prompts_for_every_missing_field_from_stdin(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(f"bob\n{SECRET}\n"))
    code, _, err = run(capsys, "account", "add", "fake", "main")
    assert code == 0, err
    stored = json.loads((tmp_path / "home" / "accounts.json").read_text())
    assert stored["fake:main"]["config"] == {"user": "bob", "key": SECRET}


def test_account_add_uses_getpass_for_secret_on_tty(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Tty(io.StringIO):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", Tty())
    monkeypatch.setattr("getpass.getpass", lambda prompt="": SECRET)
    code, out, err = run(capsys, "account", "add", "fake", "main", "--set", "user=alice")
    assert code == 0
    assert SECRET not in out + err
    assert json.loads((tmp_path / "home" / "accounts.json").read_text())["fake:main"]["config"]["key"] == SECRET


def test_secret_field_via_set_is_refused(world: World, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, out, err = run(capsys, "--json", "account", "add", "fake", "main", "--set", "user=a", "--set", f"key={SECRET}")
    assert code == 1
    assert out == ""
    assert json.loads(err)["error"]["code"] == "secret_via_argv"
    assert SECRET not in err
    assert not (tmp_path / "home" / "accounts.json").exists()


def test_unknown_field_and_unknown_source_and_empty_value(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, _, err = run(capsys, "--json", "account", "add", "fake", "main", "--set", "nope=1")
    assert (code, json.loads(err)["error"]["code"]) == (1, "unknown_field")

    code, _, err = run(capsys, "--json", "account", "add", "steam", "main")
    assert (code, json.loads(err)["error"]["code"]) == (1, "unknown_source")

    code, _, err = run(capsys, "--json", "account", "add", "broken", "main")
    error = json.loads(err)["error"]
    assert code == 1 and error["code"] == "unknown_source"
    assert "broken" in error["message"] and "failed to import" in error["message"]

    code, _, err = run(capsys, "--json", "account", "add", "fake", "main", "--set", "user=")
    assert (code, json.loads(err)["error"]["code"]) == (1, "empty_value")

    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    code, _, err = run(capsys, "--json", "account", "add", "fake", "main", "--set", "user=a")
    assert (code, json.loads(err)["error"]["code"]) == (1, "empty_value")
    assert run(capsys, "account", "ls")[1].strip() == "no accounts"


def test_account_duplicate_invalid_and_remove(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    add(capsys, monkeypatch, "main", "alice")
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, _, err = run(capsys, "--json", "account", "add", "fake", "main", "--set", "user=x")
    assert (code, json.loads(err)["error"]["code"]) == (1, "account_exists")

    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, _, err = run(capsys, "--json", "account", "add", "fake", "Bad Name", "--set", "user=x")
    assert (code, json.loads(err)["error"]["code"]) == (1, "invalid_account_name")

    code, out, _ = run(capsys, "--json", "account", "rm", "main")
    assert (code, json.loads(out)) == (0, {"ok": True, "data": {"account": "main"}})
    code, err_out, err = run(capsys, "account", "rm", "main")
    assert code == 1 and err_out == "" and err.startswith("error: ")


def test_import_ls_show(world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    world.catalogs["alice"] = [("1", "Half-Life"), ("2", "Portal")]
    add(capsys, monkeypatch, "main", "alice")
    code, out, _ = run(capsys, "--json", "import", "main")
    assert code == 0
    assert json.loads(out) == {"ok": True, "data": {"account": "main", "source": "fake", "added": 2, "restored": 0, "removed": 0, "total": 2, "complete": True, "mode": "fake"}}
    assert world.seen_config[-1] == {"user": "alice", "key": SECRET}

    code, out, _ = run(capsys, "--json", "ls")
    data = json.loads(out)["data"]
    assert (data["limit"], data["offset"]) == (50, 0)
    assert [g["title"] for g in data["games"]] == ["Half-Life", "Portal"]
    assert all(g["stores"] == ["fake"] and g["accounts"] == ["main"] and g["removed"] is False for g in data["games"])

    code, out, _ = run(capsys, "ls", "portal")
    assert code == 0 and "Portal" in out and "Half-Life" not in out and "[fake]" in out

    code, out, _ = run(capsys, "--json", "ls", "--limit", "1", "--offset", "1")
    assert len(json.loads(out)["data"]["games"]) == 1

    game_id = data["games"][0]["id"]
    code, out, _ = run(capsys, "--json", "show", str(game_id))
    shown = json.loads(out)["data"]
    assert shown["title"] == "Half-Life"
    assert [(o["store"], o["store_id"], o["account"], o["removed"]) for o in shown["ownership"]] == [("fake", "1", "main", False)]
    code, out, _ = run(capsys, "show", str(game_id))
    assert code == 0 and "Half-Life" in out and "fake:1" in out

    code, _, err = run(capsys, "--json", "show", "9999")
    assert (code, json.loads(err)["error"]["code"]) == (1, "game_not_found")


def test_removed_game_hidden_then_visible_and_restored(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.catalogs["alice"] = [("1", "Half-Life"), ("2", "Portal")]
    add(capsys, monkeypatch, "main", "alice")
    assert run(capsys, "import", "main")[0] == 0

    world.catalogs["alice"] = [("1", "Half-Life")]
    code, out, _ = run(capsys, "--json", "import", "main")
    assert code == 0 and json.loads(out)["data"]["removed"] == 1

    titles = [g["title"] for g in json.loads(run(capsys, "--json", "ls")[1])["data"]["games"]]
    assert titles == ["Half-Life"]
    games = json.loads(run(capsys, "--json", "ls", "--removed")[1])["data"]["games"]
    assert {g["title"]: g["removed"] for g in games} == {"Half-Life": False, "Portal": True}

    world.catalogs["alice"] = [("1", "Half-Life"), ("2", "Portal")]
    code, out, _ = run(capsys, "--json", "import", "main")
    assert json.loads(out)["data"]["restored"] == 1
    assert len(json.loads(run(capsys, "--json", "ls")[1])["data"]["games"]) == 2


def test_source_error_leaves_library_unchanged(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.catalogs["alice"] = [("1", "Half-Life"), ("2", "Portal")]
    add(capsys, monkeypatch, "main", "alice")
    run(capsys, "import", "main")
    before = run(capsys, "--json", "ls", "--removed")[1]

    world.failing.add("alice")
    code, out, err = run(capsys, "--json", "import", "main")
    assert code == 1 and out == ""
    assert json.loads(err) == {"ok": False, "error": {"code": "fetch_incomplete", "message": "profile is private"}}
    assert run(capsys, "--json", "ls", "--removed")[1] == before

    code, out, err = run(capsys, "import", "main")
    assert code == 1 and out == "" and err == "error: profile is private\n"


def test_import_unknown_account_and_unknown_source(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    code, _, err = run(capsys, "--json", "import", "ghost")
    assert (code, json.loads(err)["error"]["code"]) == (1, "account_not_found")

    (tmp_path / "home" / "accounts.json").write_text(json.dumps({"old": {"source": "gone", "config": {}}}))
    (tmp_path / "home" / "accounts.json").chmod(0o600)
    code, _, err = run(capsys, "--json", "import", "old")
    assert (code, json.loads(err)["error"]["code"]) == (1, "unknown_source")


def test_import_all_mixed_results(world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    world.catalogs["alice"] = [("1", "Half-Life")]
    world.catalogs["bob"] = [("9", "Doom")]
    add(capsys, monkeypatch, "aaa", "alice")
    add(capsys, monkeypatch, "bbb", "bob")
    add(capsys, monkeypatch, "ccc", "carol")
    world.failing.add("bob")

    code, out, err = run(capsys, "--json", "import", "--all")
    assert code == 1
    results = json.loads(out)["data"]["results"]
    assert results == [
        {"account": "aaa", "source": "fake", "ok": True, "added": 1, "restored": 0, "removed": 0, "total": 1, "complete": True, "mode": "fake"},
        {"account": "bbb", "source": "fake", "ok": False, "error": {"code": "fetch_incomplete", "message": "profile is private"}},
        {"account": "ccc", "source": "fake", "ok": True, "added": 0, "restored": 0, "removed": 0, "total": 0, "complete": True, "mode": "fake"},
    ]
    games = json.loads(run(capsys, "--json", "ls")[1])["data"]["games"]
    assert [g["title"] for g in games] == ["Half-Life"]


def test_import_all_without_accounts_is_empty_success(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--json", "import", "--all")
    assert (code, json.loads(out)) == (0, {"ok": True, "data": {"results": []}})


def test_import_lock_contention(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    world.catalogs["alice"] = [("1", "Half-Life")]
    add(capsys, monkeypatch, "main", "alice")
    with writer_lock(tmp_path / "home" / "import.lock"):
        code, out, err = run(capsys, "--json", "import", "main")
        assert code == 1 and out == ""
        assert json.loads(err)["error"]["code"] == "import_in_progress"
        code, _, err = run(capsys, "--json", "import", "--all")
        assert (code, json.loads(err)["error"]["code"]) == (1, "import_in_progress")
    assert world.seen_config == []
    assert run(capsys, "import", "main")[0] == 0


def test_usage_errors_exit_2(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (
        ["import"],
        ["import", "a", "--all"],
        ["show", "abc"],
        ["account"],
        ["account", "add", "fake"],
        ["bogus"],
    ):
        with pytest.raises(SystemExit) as caught:
            main(argv)
        assert caught.value.code == 2, argv
        capsys.readouterr()


def test_json_flag_must_precede_subcommand(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as caught:
        main(["ls", "--json"])
    assert caught.value.code == 2


def test_state_unavailable_when_home_is_open(
    world: World, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "home").chmod(0o755)
    code, out, err = run(capsys, "--json", "ls")
    assert code == 1 and out == ""
    assert json.loads(err)["error"]["code"] == "state_unavailable"
    code, _, err = run(capsys, "ls")
    assert code == 1 and err.startswith("error: ")


def test_ls_on_empty_library(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--json", "ls")
    assert (code, json.loads(out)) == (0, {"ok": True, "data": {"games": [], "limit": 50, "offset": 0}})


def test_optional_field_may_be_left_blank_and_partial_import_says_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    home.chmod(0o700)
    monkeypatch.setenv("LUDEX_HOME", str(home))
    seen: list[dict[str, str]] = []

    def fetch(config: Any) -> FetchResult:
        seen.append(dict(config))
        return FetchResult([OwnedGame("fake", "1", "Alpha")], False, "local")

    plugin = SourcePlugin("fake", "Fake", (ConfigField("key", "API key", secret=True, optional=True),), fetch)
    monkeypatch.setattr("ludex.cli.load_sources", lambda: ({"fake": plugin}, {}))
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    code, _, err = run(capsys, "account", "add", "fake", "main")
    assert code == 0, err
    code, out, err = run(capsys, "import", "main")
    assert code == 0, err
    assert seen == [{}]
    assert "[local] partial: nothing removed" in out
    code, out, _ = run(capsys, "--json", "import", "main")
    data = json.loads(out)["data"]
    assert (data["complete"], data["mode"], data["removed"]) == (False, "local", 0)


def test_setup_adds_account_with_default_name_and_imports(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.catalogs["me"] = [("1", "Alpha")]
    monkeypatch.setattr("sys.stdin", io.StringIO(f"\nme\n{SECRET}\n"))  # source default; name given
    code, out, err = run(capsys, "setup", "--name", "main")
    assert code == 0, err
    assert "added account main (fake)" in out and "main: 1 added" in out
    assert SECRET not in out + err


def test_setup_failed_import_keeps_account_and_says_how_to_retry(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.failing.add("me")
    monkeypatch.setattr("sys.stdin", io.StringIO(f"me\n{SECRET}\n"))
    code, _, err = run(capsys, "setup", "fake", "--name", "main")
    assert code == 1
    assert "profile is private" in err and "ludex import fake:main" in err
    code, out, _ = run(capsys, "account", "ls")
    assert "main" in out


def test_setup_rejects_taken_name_before_prompting_for_fields(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    add(capsys, monkeypatch, "main", "me")
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    code, _, err = run(capsys, "setup", "fake", "--name", "main")
    assert code == 1
    assert "already exists for source fake" in err


def test_same_name_in_two_sources_is_allowed_and_needs_qualifying(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    other = SourcePlugin("other", "Other", (), lambda config: FetchResult([OwnedGame("other", "1", "Zed")], True, "o"))
    fake = SourcePlugin("fake", "Fake", (), lambda config: FetchResult([OwnedGame("fake", "1", "Alpha")], True, "f"))
    monkeypatch.setattr("ludex.cli.load_sources", lambda: ({"fake": fake, "other": other}, {}))
    for source in ("fake", "other"):
        code, _, err = run(capsys, "account", "add", source, "main")
        assert code == 0, err
    code, _, err = run(capsys, "import", "main")
    assert code == 1 and "fake:main" in err and "other:main" in err
    code, out, err = run(capsys, "import", "other:main")
    assert code == 0 and "1 added" in out, err
    code, out, _ = run(capsys, "import", "--all")
    assert code == 0 and out.count("main:") == 2
    code, _, _ = run(capsys, "account", "rm", "fake:main")
    assert code == 0
    code, out, _ = run(capsys, "account", "ls")
    assert out.split() == ["main", "other"]
