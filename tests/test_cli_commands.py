from __future__ import annotations

import io
import json
import stat
from pathlib import Path

from ludex.paths import state_paths
from typing import Any

import pytest

from ludex.cli import main
from ludex.plugins import ConfigField, FetchResult, OwnedGame, SourceError, Provider
from ludex.storage import connect, writer_lock

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
    plugin = Provider(
        name="fake",
        help="Fake store",
        config_fields=(ConfigField("user", "account user"), ConfigField("key", "API key", secret=True)),
        fetch=lambda config: FetchResult(w.fetch(config), True, "fake"),
        settings=(ConfigField("region", "store region", optional=True), ConfigField("token", "API token", secret=True, optional=True)),
    )
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"fake": plugin}, {"broken": "failed to import"}))
    return w


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def add(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, name: str, user: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, _, err = run(capsys, "account", "add", "fake", name, "--set", f"user={user}")
    assert code == 0, err


def test_providers_lists_plugins_and_problems(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _ = run(capsys, "--json", "providers")
    assert code == 0
    data = json.loads(out)
    assert data == {
        "ok": True,
        "data": {
            "providers": [
                {
                    "name": "fake",
                    "help": "Fake store",
                    "capabilities": ["owned"],
                    "commands": [],
                    "fields": [
                        {"name": "user", "help": "account user", "secret": False, "optional": False, "kind": "text", "choices": []},
                        {"name": "key", "help": "API key", "secret": True, "optional": False, "kind": "text", "choices": []},
                    ],
                    "settings": [
                        {"name": "region", "help": "store region", "secret": False, "optional": True, "kind": "text", "choices": []},
                        {"name": "token", "help": "API token", "secret": True, "optional": True, "kind": "text", "choices": []},
                    ],
                }
            ],
            "problems": {"broken": "failed to import"},
        },
    }
    code, out, _ = run(capsys, "providers")
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
    for argv in (("account", "ls"), ("--json", "account", "ls"), ("--json", "providers")):
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
    assert (code, json.loads(out)) == (0, {"ok": True, "data": {"account": "main", "records_removed": 0}})
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

    plugin = Provider("fake", "Fake", (ConfigField("key", "API key", secret=True, optional=True),), fetch)
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"fake": plugin}, {}))
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
    other = Provider("other", "Other", (), lambda config: FetchResult([OwnedGame("other", "1", "Zed")], True, "o"))
    fake = Provider("fake", "Fake", (), lambda config: FetchResult([OwnedGame("fake", "1", "Alpha")], True, "f"))
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"fake": fake, "other": other}, {}))
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


def test_export_json_and_csv(world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    world.catalogs["me"] = [("1", 'Alpha, "the" game'), ("2", "Beta")]
    add(capsys, monkeypatch, "main", "me")
    assert run(capsys, "import", "main")[0] == 0
    code, out, _ = run(capsys, "export")
    assert code == 0 and [g["title"] for g in json.loads(out)] == ['Alpha, "the" game', "Beta"]
    code, out, _ = run(capsys, "export", "--format", "csv")
    import csv as _csv
    rows = list(_csv.reader(out.splitlines()))
    assert rows[0][:3] == ["game_id", "title", "store"] and rows[1][1] == 'Alpha, "the" game' and len(rows) == 3
    code, out, _ = run(capsys, "--json", "export")
    assert json.loads(out)["data"]["games"][0]["ownership"][0]["account"] == "main"


def test_path_completion_lists_matches_and_marks_directories(tmp_path: Path) -> None:
    from ludex.cli import _complete_path

    (tmp_path / "games").mkdir()
    (tmp_path / "gzip.txt").write_text("x")
    prefix = str(tmp_path / "g")
    assert [_complete_path(prefix, i) for i in range(3)] == [str(tmp_path / "games") + "/", str(tmp_path / "gzip.txt"), None]


def test_account_rm_deletes_its_records_and_clears_orphans(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.catalogs["me"] = [("1", "Alpha")]
    add(capsys, monkeypatch, "main", "me")
    add(capsys, monkeypatch, "other", "me")
    assert run(capsys, "import", "--all")[0] == 0
    code, out, _ = run(capsys, "account", "rm", "other")
    assert code == 0 and "deleted 1 records" in out
    code, out, _ = run(capsys, "ls")
    assert "Alpha" in out  # still owned through main
    code, out, _ = run(capsys, "show", "1")
    assert out.count("owned") == 1 and "other" not in out
    # orphan: the account vanished from the file but its record remains
    add(capsys, monkeypatch, "ghost", "me")
    assert run(capsys, "import", "ghost")[0] == 0
    path = state_paths().accounts
    path.write_text(json.dumps({k: v for k, v in json.loads(path.read_text()).items() if k != "fake:ghost"}))
    code, out, _ = run(capsys, "account", "rm", "ghost")
    assert code == 0 and "deleted 1 records" in out
    code, _, err = run(capsys, "account", "rm", "ghost")
    assert code == 1 and "not found" in err


def test_show_accepts_a_title(world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    world.catalogs["me"] = [("1", "Alpha"), ("2", "Beta")]
    add(capsys, monkeypatch, "main", "me")
    assert run(capsys, "import", "main")[0] == 0
    code, out, _ = run(capsys, "show", "beta")
    assert code == 0 and out.startswith("2  Beta")
    code, _, err = run(capsys, "show", "gamma")
    assert code == 1 and "no game matches" in err


def test_provider_without_owned_capability_cannot_have_accounts(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    searchless = Provider("lookup", "Lookup only", (), launch_url=lambda store_id: "x://" + store_id)
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"lookup": searchless}, {}))
    code, _, err = run(capsys, "account", "add", "lookup", "a")
    assert code == 1 and "cannot list owned games" in err
    code, out, _ = run(capsys, "providers")
    assert "lookup  [launch]" in out


def test_acquire_command_prints_directory_and_hints(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ludex.plugins import AcquireResult

    def fn(request, report):
        report("step 1")
        (request.destination / "g").mkdir()
        return AcquireResult(request.destination / "g", {"executable": "run.sh"})

    plugin = Provider("demo", "Demo", (), acquire=fn)
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"demo": plugin}, {}))
    code, out, err = run(capsys, "acquire", "demo", "7", "--to", str(tmp_path / "dl"))
    assert code == 0 and "step 1" in err and "executable=run.sh" in out and str((tmp_path / "dl").resolve() / "g") in out
    code, _, err = run(capsys, "acquire", "steam", "7", "--to", str(tmp_path / "dl"))
    assert code == 1 and "cannot acquire" in err


def _demo_provider(monkeypatch):
    import argparse

    from ludex.library import list_games
    from ludex.plugins import Command, CommandResult

    def count(context, args):
        parser = argparse.ArgumentParser(prog="ludex demo count")
        parser.add_argument("--min", type=int, default=0)
        ns = parser.parse_args(list(args))
        return CommandResult({"count": len(list_games(context.conn)), "min": ns.min}, f"{len(list_games(context.conn))} games")

    def boom(context, args):
        raise RuntimeError("secret token abc")

    plugin = Provider("demo", "Demo", (), commands=(Command("count", "count games", count), Command("boom", "fails", boom)))
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"demo": plugin}, {}))


def test_plugin_commands_run_with_library_access_and_report_errors(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    _demo_provider(monkeypatch)
    code, out, _ = run(capsys, "demo", "count")
    assert (code, out.strip()) == (0, "0 games")
    code, out, _ = run(capsys, "--json", "demo", "count", "--min", "3")
    assert code == 0 and json.loads(out)["data"] == {"count": 0, "min": 3}
    code, _, err = run(capsys, "demo", "boom")
    assert code == 1 and err.strip() == "error: demo boom failed (RuntimeError)" and "secret" not in err
    code, _, err = run(capsys, "demo", "nope")
    assert code == 1 and "demo commands: boom, count" in err
    assert run(capsys, "demo", "count", "--bad")[0] == 2
    code, out, _ = run(capsys, "providers")
    assert "ludex demo count  count games" in out


def test_builtin_commands_win_over_a_provider_with_the_same_name(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ludex.plugins import Command, CommandResult

    plugin = Provider("ls", "Evil", (), commands=(Command("x", "x", lambda c, a: CommandResult(None, "hijacked")),))
    monkeypatch.setattr("ludex.cli.load_providers", lambda: ({"ls": plugin}, {}))
    assert "hijacked" not in run(capsys, "ls", "x")[1]


def test_game_set_and_show_and_runners_commands(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ludex.library import import_account
    from ludex.plugins import OwnedGame
    from ludex.paths import state_paths
    from ludex.runners import Runner

    conn = connect(state_paths().database)
    import_account(conn, "disk", [OwnedGame("local", "g", "Hades")], store="local")
    conn.close()
    proton = tmp_path / "GE"
    proton.mkdir()
    (proton / "proton").write_text("")
    monkeypatch.setattr("ludex.cli.find_runners", lambda: [Runner("GE", proton, "steam")])
    code, out, _ = run(capsys, "--json", "runners")
    assert code == 0 and json.loads(out)["data"]["runners"][0]["name"] == "GE"
    code, out, _ = run(capsys, "--json", "game", "set", "hades", "--runner", str(proton), "--env", "A=1", "--args=-w '1 2'", "--exe", "g.exe")
    data = json.loads(out)["data"]
    assert code == 0 and (data["runner"], data["env"], data["args"], data["executable"]) == (str(proton), {"A": "1"}, ["-w", "1 2"], "g.exe")
    code, out, _ = run(capsys, "game", "show", "Hades")
    assert code == 0 and "executable: g.exe" in out and "A" in out
    code, _, err = run(capsys, "game", "set", "hades", "--env", "bad")
    assert code == 1 and "NAME=VALUE" in err
    with pytest.raises(SystemExit):
        run(capsys, "game")


def test_config_command_shows_sets_and_resets(world: World, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    default = json.loads(run(capsys, "--json", "config")[1])["data"]["prefix_dir"]
    code, out, _ = run(capsys, "--json", "config", "prefix_dir", str(tmp_path / "pfx"))
    assert code == 0 and json.loads(out)["data"]["prefix_dir"] == str(tmp_path / "pfx")
    assert run(capsys, "config", "prefix_dir", "rel")[0] == 1
    assert run(capsys, "config", "--reset")[0] == 1  # no setting named
    assert run(capsys, "config", "nope")[0] == 1
    assert json.loads(run(capsys, "--json", "config", "prefix_dir", "--reset")[1])["data"]["prefix_dir"] == default


def test_config_switch_values_are_validated_and_shown(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    data = json.loads(run(capsys, "--json", "config")[1])["data"]
    assert data["steam_shortcuts"] is False and data["heroic_sideload"] is False
    assert run(capsys, "config", "steam_shortcuts", "maybe")[0] == 1
    assert run(capsys, "config", "steam_shortcuts", "--reset")[0] == 1
    code, out, _ = run(capsys, "config", "steam_shortcuts", "no")  # already off: harmless
    assert code == 0 and out.strip() == "steam_shortcuts: no"


def test_account_set_changes_fields_keeps_games_and_never_prints_secrets(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.catalogs = {"u1": [("1", "Hades")], "u2": [("2", "Doom")]}
    add(capsys, monkeypatch, "a", "u1")
    assert run(capsys, "import", "a")[0] == 0
    code, out, err = run(capsys, "--json", "account", "set", "a", "--set", "user=u2")
    assert code == 0 and json.loads(out)["data"] == {"account": "a", "changed": ["user"]}
    assert "Hades" in run(capsys, "ls")[1]  # the games stay until the next import
    monkeypatch.setattr("sys.stdin", io.StringIO("new-" + SECRET + "\n"))
    code, out, err = run(capsys, "account", "set", "a", "--secret", "key")
    assert code == 0 and "new-" + SECRET not in out + err
    assert run(capsys, "import", "a")[0] == 0 and world.seen_config[-1]["user"] == "u2" and world.seen_config[-1]["key"] == "new-" + SECRET
    assert "Doom" in run(capsys, "ls")[1]


def test_account_set_rejects_bad_input_without_changing_the_account(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    add(capsys, monkeypatch, "a", "u1")
    for argv in (
        ["account", "set", "a"],
        ["account", "set", "a", "--set", f"key={SECRET}"],  # secret on argv
        ["account", "set", "a", "--set", "nope=1"],
        ["account", "set", "a", "--set", "user="],
        ["account", "set", "a", "--unset", "user"],  # required
        ["account", "set", "missing", "--set", "user=x"],
    ):
        code, out, err = run(capsys, *argv)
        assert code == 1 and SECRET not in out + err, argv
    run(capsys, "import", "a")
    assert world.seen_config[-1]["user"] == "u1"


def test_plugin_settings_roundtrip_reach_the_plugin_and_never_print_secrets(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    world.catalogs = {"u1": []}
    add(capsys, monkeypatch, "a", "u1")
    assert run(capsys, "config", "fake.region", "eu")[1].strip() == "fake.region: eu"
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    code, out, err = run(capsys, "config", "fake.token", "--secret")
    assert code == 0 and out.strip() == "fake.token: (set)" and SECRET not in out + err
    code, out, _ = run(capsys, "--json", "config")
    assert json.loads(out)["data"]["plugins"] == {"fake": {"region": "eu", "token": "(set)"}} and SECRET not in out
    run(capsys, "import", "a")
    assert world.seen_config[-1]["region"] == "eu" and world.seen_config[-1]["token"] == SECRET
    assert run(capsys, "config", "fake.region", "--reset")[1].strip() == "fake.region: (not set)"
    path = Path(state_paths().root) / "plugin-settings.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_plugin_settings_rejects_secret_on_argv_and_unknown_names(world: World, capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (["config", "fake.token", SECRET], ["config", "fake.nope", "x"], ["config", "ghost.region", "x"], ["config", "fake.region", "--secret"], ["config", "prefix_dir", "--secret"]):
        code, out, err = run(capsys, *argv)
        assert code == 1 and SECRET not in out + err, argv
