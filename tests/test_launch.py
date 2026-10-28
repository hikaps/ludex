from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ludex import launch as launch_mod
from ludex.errors import LudexError
from ludex.library import import_account
from ludex.plugins import OwnedGame, Provider, SourceError
from ludex.sources import epic, steam
from ludex.storage import connect


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "db.sqlite3")


@pytest.fixture
def opened(monkeypatch):
    calls = []
    monkeypatch.setattr(launch_mod.subprocess, "run", lambda argv, **kw: calls.append(argv))
    return calls


def test_urls_encode_the_store_id():
    assert steam.PLUGIN.launch_url("220") == "steam://rungameid/220"
    assert epic.PLUGIN.launch_url("a b&c") == "heroic://launch?appName=a%20b%26c&runner=legendary"


def test_launch_opens_the_plugin_url_with_xdg_open(conn, opened):
    import_account(conn, "main", [OwnedGame("steam", "220", "HL2")], store="steam")
    assert launch_mod.launch_game(conn, {"steam": steam.PLUGIN}, 1) == "steam:220"
    assert opened == [["xdg-open", "steam://rungameid/220"]]


def test_several_launchable_stores_need_a_choice_and_local_is_not_launchable(conn, opened):
    import_account(conn, "main", [OwnedGame("steam", "1", "Hades")], store="steam")
    import_account(conn, "main", [OwnedGame("epic", "h", "Hades")], store="epic")
    import_account(conn, "main", [OwnedGame("local", "x", "Hades")], store="local")
    sources = {"steam": steam.PLUGIN, "epic": epic.PLUGIN, "local": Provider("local", "l", (), lambda c: None)}
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, sources, 1)
    assert info.value.code == "launch_ambiguous"
    assert launch_mod.launch_game(conn, sources, 1, "epic") == "epic:h"
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, sources, 1, "local")
    assert info.value.code == "not_launchable"


def test_failed_open_is_reported_without_the_url(conn, monkeypatch):
    import_account(conn, "main", [OwnedGame("steam", "220", "HL2")], store="steam")

    def boom(argv, **kw):
        raise subprocess.CalledProcessError(3, argv)

    monkeypatch.setattr(launch_mod.subprocess, "run", boom)
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, {"steam": steam.PLUGIN}, 1)
    assert info.value.code == "launch_failed" and "steam://" not in info.value.message


def test_install_opens_the_install_url_and_only_for_providers_that_have_one(conn, opened):
    import_account(conn, "main", [OwnedGame("steam", "220", "HL2")], store="steam")
    import_account(conn, "main", [OwnedGame("plain", "h", "HL2")], store="plain")
    sources = {"steam": steam.PLUGIN, "plain": Provider("plain", "no install route", ())}
    assert launch_mod.install_game(conn, sources, 1) == ("steam:220", None)  # the other provider has no install route, so no ambiguity
    assert opened == [["xdg-open", "steam://install/220"]]
    with pytest.raises(LudexError) as info:
        launch_mod.install_game(conn, sources, 1, "plain")
    assert info.value.code == "not_installable"


def test_install_command_runs_in_the_background_as_a_tracked_job(conn, tmp_path):
    import_account(conn, "main", [OwnedGame("epic", "Quail", "Quail")], store="epic")
    tool = Provider("epic", "e", (), install_command=lambda config, store_id: ["/bin/echo", store_id, config["dir"]])
    target, job = launch_mod.install_game(conn, {"epic": tool}, 1, None, lambda store, account: {"dir": "/x"}, tmp_path / "logs")
    assert target == "epic:Quail" and job.target == "epic:Quail" and job.title == "Quail" and job.kind == "install"
    assert job.log.parent == tmp_path / "logs" and oct(job.log.parent.stat().st_mode & 0o777) == "0o700"
    plan = launch_mod.prepare_install(conn, {"epic": tool}, 1, None, lambda store, account: {"dir": "/x"})
    assert plan.argv[0] == "/bin/echo" and plan.url is None
    bad = Provider("epic", "e", (), install_command=lambda config, store_id: ["relative"])
    with pytest.raises(LudexError, match="invalid install command"):
        launch_mod.prepare_install(conn, {"epic": bad}, 1, None, lambda store, account: {})
    failing = Provider("epic", "e", (), install_command=lambda config, store_id: (_ for _ in ()).throw(SourceError("epic_no_legendary", "legendary is not installed")))
    with pytest.raises(LudexError, match="legendary is not installed"):
        launch_mod.prepare_install(conn, {"epic": failing}, 1, None, lambda store, account: {})


def test_command_launch_runs_detached_in_the_game_folder_with_the_account_config(conn, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(launch_mod.subprocess, "Popen", lambda argv, **kw: calls.append((argv, kw)))
    exe = tmp_path / "g" / "start.sh"
    seen = []

    def command(config, store_id):
        seen.append((dict(config), store_id))
        return [str(exe)]

    import_account(conn, "disk", [OwnedGame("local", "g", "G")], store="local")
    sources = {"local": Provider("local", "l", (), lambda c: None, launch_command=command)}
    assert launch_mod.launch_game(conn, sources, 1, None, lambda store, account: {"path": f"{store}/{account}"}) == "local:g"
    argv, kw = calls[0]
    assert (argv, kw["cwd"], kw["start_new_session"], seen) == ([str(exe)], exe.parent, True, [({"path": "local/disk"}, "g")])
    with pytest.raises(LudexError) as info:  # config is required to build the command
        launch_mod.launch_game(conn, sources, 1)
    assert info.value.code == "launch_failed"


@pytest.mark.parametrize("argv", [[], ["relative.sh"]])
def test_command_launch_rejects_invalid_commands(conn, monkeypatch, argv):
    monkeypatch.setattr(launch_mod.subprocess, "Popen", lambda *a, **k: pytest.fail("must not start"))
    import_account(conn, "disk", [OwnedGame("local", "g", "G")], store="local")
    sources = {"local": Provider("local", "l", (), lambda c: None, launch_command=lambda c, s: argv)}
    with pytest.raises(LudexError) as info:
        launch_mod.launch_game(conn, sources, 1, None, lambda *a: {})
    assert info.value.code == "launch_failed"


@pytest.fixture
def windows(conn, tmp_path, monkeypatch):
    """A local-style provider whose game folder holds one .exe, plus a Proton folder and a fake umu-run."""
    folder = tmp_path / "games" / "g"
    folder.mkdir(parents=True)
    (folder / "Game.exe").write_text("")
    (folder / "unins000.exe").write_text("")
    proton = tmp_path / "GE"
    proton.mkdir()
    (proton / "proton").write_text("")
    monkeypatch.setattr(launch_mod.shutil, "which", lambda name: "/usr/bin/umu-run" if name == "umu-run" else None)
    import_account(conn, "disk", [OwnedGame("local", "g", "G")], store="local")
    sources = {"local": Provider("local", "l", (), lambda c: None, game_folder=lambda config, store_id: folder)}
    return sources, folder, proton


def test_runner_launch_goes_through_umu_run_with_prefix_and_environment(conn, windows, tmp_path):
    from ludex.game_settings import update_settings

    sources, folder, proton = windows
    update_settings(conn, "local", "g", runner=str(proton), env={"DXVK_HUD": "1"}, args=["-w", "x y"])
    plan = launch_mod.prepare_launch(conn, sources, 1, None, lambda *a: {}, tmp_path / "prefixes")
    assert plan.argv == ("/usr/bin/umu-run", str(folder / "Game.exe"), "-w", "x y") and plan.cwd == folder
    assert plan.env["PROTONPATH"] == str(proton) and plan.env["DXVK_HUD"] == "1" and plan.env["GAMEID"] == "umu-0"
    assert Path(plan.env["WINEPREFIX"]).parent == tmp_path / "prefixes"
    update_settings(conn, "local", "g", prefix=str(tmp_path / "mine"))
    assert launch_mod.prepare_launch(conn, sources, 1, None, lambda *a: {}, tmp_path / "prefixes").env["WINEPREFIX"] == str(tmp_path / "mine")


def test_runner_launch_errors_are_specific(conn, windows, tmp_path, monkeypatch):
    from ludex.game_settings import update_settings

    sources, folder, proton = windows
    update_settings(conn, "local", "g", runner=str(proton))
    (folder / "Other.exe").write_text("")  # two .exe files: ambiguous without --exe
    with pytest.raises(LudexError, match="--exe"):
        launch_mod.prepare_launch(conn, sources, 1, None, lambda *a: {}, tmp_path)
    update_settings(conn, "local", "g", executable="../escape.exe")
    with pytest.raises(LudexError, match="outside the game folder"):
        launch_mod.prepare_launch(conn, sources, 1, None, lambda *a: {}, tmp_path)
    update_settings(conn, "local", "g", executable="Game.exe")
    monkeypatch.setattr(launch_mod.shutil, "which", lambda name: None)
    with pytest.raises(LudexError) as info:
        launch_mod.prepare_launch(conn, sources, 1, None, lambda *a: {}, tmp_path)
    assert info.value.code == "launcher_missing"


def test_executable_without_runner_runs_natively_and_settings_apply_to_launch_command(conn, windows, tmp_path):
    from ludex.game_settings import update_settings

    sources, folder, proton = windows
    (folder / "run.sh").write_text("")
    update_settings(conn, "local", "g", executable="run.sh", env={"A": "1"}, args=["x"])
    plan = launch_mod.prepare_launch(conn, sources, 1, None, lambda *a: {}, tmp_path)
    assert (plan.argv, plan.env) == ((str(folder / "run.sh"), "x"), {"A": "1"})
    auto = {"local": Provider("local", "l", (), lambda c: None, launch_command=lambda c, s: [str(folder / "auto.sh")])}
    plan = launch_mod.prepare_launch(conn, auto, 1, None, lambda *a: {}, tmp_path)  # settings env/args still apply
    assert (plan.argv, plan.env) == ((str(folder / "auto.sh"), "x"), {"A": "1"})
