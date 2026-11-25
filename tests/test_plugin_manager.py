from __future__ import annotations

import sys
from pathlib import Path

import pytest

from ludex import plugin_manager as pm
from ludex.errors import LudexError
from ludex.loader import load_providers


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setenv("LUDEX_HOME", str(tmp_path / "state"))
    monkeypatch.setattr(sys, "path", list(sys.path))
    monkeypatch.setattr(pm.shutil, "which", lambda name: None)
    calls: list[list[str]] = []

    def fake_run(command: list[str]) -> None:
        calls.append(command)
        target = Path(command[command.index("--target") + 1])
        spec = command[-1]
        if spec == "plain-lib":
            (target / "plain_lib-1.0.dist-info").mkdir()
            (target / "plain_lib-1.0.dist-info" / "METADATA").write_text("Name: plain-lib\nVersion: 1.0\n")
            return
        version = spec.partition("==")[2] or "1.0"
        provider = "fakeprov"
        if "withcore" in spec:  # a plugin that requires ludex-core brings a second copy of the built-in providers
            core = target / "ludex_core-0.60.0.dist-info"
            core.mkdir()
            (core / "METADATA").write_text("Name: ludex-core\nVersion: 0.60.0\n")
            (core / "entry_points.txt").write_text("[ludex.providers]\nsteam = ludex.sources.steam:PLUGIN\nlocal = ludex.sources.local:PLUGIN\n")
        if "clash" in spec:
            provider = "steam"
        info = target / f"ludex_fakeplug-{version}.dist-info"
        info.mkdir()
        (info / "METADATA").write_text(f"Name: ludex-fakeplug\nVersion: {version}\n")
        (info / "entry_points.txt").write_text(f"[ludex.providers]\n{provider} = ludex_fakeplug_mod:PLUGIN\n")
        (target / "ludex_fakeplug_mod.py").write_text(
            "from ludex.plugins import FetchResult, Provider\n"
            f"PLUGIN = Provider({provider!r}, 'fake', (), lambda c: FetchResult([], True, None))\n"
        )

    monkeypatch.setattr(pm, "_run", fake_run)
    monkeypatch.setattr(pm, "_tool", lambda **kw: ["pip"])
    yield calls
    sys.modules.pop("ludex_fakeplug_mod", None)


def test_add_update_remove_roundtrip_and_loader_picks_the_plugin_up(managed):
    assert pm.add_plugin("ludex-fakeplug==1.0") == {"name": "ludex-fakeplug", "version": "1.0", "providers": ["fakeprov"]}
    assert [(p["name"], p["version"], p["spec"]) for p in pm.list_plugins()] == [("ludex-fakeplug", "1.0", "ludex-fakeplug==1.0")]
    loaded, problems = load_providers()
    assert "fakeprov" in loaded and not problems
    assert pm.update_plugins() == [{"name": "ludex-fakeplug", "from": "1.0", "ok": True, "to": "1.0"}]
    assert "--upgrade" in managed[-1] and managed[-1][-1] == "ludex-fakeplug==1.0"
    assert pm.remove_plugin("fakeprov")["name"] == "ludex-fakeplug"  # by provider name too
    assert pm.list_plugins() == [] and not [p for p in pm.plugins_dir().iterdir()]


def test_a_plugin_requiring_ludex_core_does_not_register_the_built_in_providers_twice(managed):
    assert pm.add_plugin("ludex-fakeplug-withcore==1.0")["providers"] == ["fakeprov"]
    loaded, problems = load_providers()
    assert not problems and {"fakeprov", "steam", "local"} <= set(loaded)


def test_a_disabled_plugin_is_not_loaded_and_stays_disabled_after_an_update(managed):
    pm.add_plugin("ludex-fakeplug==1.0")
    assert pm.set_plugin_enabled("fakeprov", False)["enabled"] is False
    assert pm.list_plugins()[0]["enabled"] is False
    sys.path[:] = [p for p in sys.path if "plugins" not in p]
    sys.modules.pop("ludex_fakeplug_mod", None)
    assert "fakeprov" not in load_providers()[0]
    pm.update_plugins()
    assert pm.list_plugins()[0]["enabled"] is False
    pm.set_plugin_enabled("ludex-fakeplug", True)
    assert "fakeprov" in load_providers()[0]


def test_a_package_without_a_ludex_entry_point_is_rejected_and_leaves_nothing(managed):
    with pytest.raises(LudexError) as info:
        pm.add_plugin("plain-lib")
    assert info.value.code == "not_a_plugin" and list(pm.plugins_dir().iterdir()) == []


def test_a_provider_name_that_is_already_taken_is_rejected(managed):
    with pytest.raises(LudexError) as info:
        pm.add_plugin("ludex-fakeplug-clash")
    assert info.value.code == "provider_exists" and pm.list_plugins() == []


@pytest.mark.parametrize("spec", ["", "--index-url=http://evil", "git+https://user:token@host/x.git"])
def test_unsafe_specs_never_reach_the_installer(managed, spec):
    with pytest.raises(LudexError) as info:
        pm.add_plugin(spec)
    assert info.value.code == "invalid_spec" and managed == []


def test_a_failed_update_keeps_the_installed_version(managed, monkeypatch):
    pm.add_plugin("ludex-fakeplug==1.0")

    def boom(command):
        raise LudexError("install_failed", "network down")

    monkeypatch.setattr(pm, "_run", boom)
    result = pm.update_plugins("ludex-fakeplug")
    assert result[0]["ok"] is False and result[0]["error"]["code"] == "install_failed"
    assert pm.list_plugins()[0]["version"] == "1.0"


def test_removing_an_unknown_plugin_fails(managed):
    with pytest.raises(LudexError) as info:
        pm.remove_plugin("nope")
    assert info.value.code == "plugin_not_found"


@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr(pm, "_is_editable", lambda: False)
    installed = {"ludex-games": "0.31.0.dev12"}

    def version(name):
        if name not in installed:
            raise pm.PackageNotFoundError(name)
        return installed[name]

    monkeypatch.setattr(pm, "version", version)
    monkeypatch.setattr(pm.shutil, "which", lambda name: f"/bin/{name}")
    return installed


BETA = "https://github.com/hikaps/ludex/releases/download/beta/"


def test_update_core_uses_the_installers_own_command_and_the_installed_channel(core, monkeypatch):
    monkeypatch.setattr(pm.sys, "prefix", "/home/u/.local/share/uv/tools/ludex")
    result = pm.update_core(None, dry_run=True)
    assert result["channel"] == "beta"
    assert result["commands"] == [["/bin/uv", "tool", "install", "--force", "--reinstall", BETA + "ludex.tar.gz"]]
    core["ludex-games"] = "0.31.0"
    stable = pm.update_core(None, dry_run=True)
    assert stable["channel"] == "stable"
    assert stable["commands"] == [["/bin/uv", "tool", "install", "--force", "--reinstall", "ludex-games"]]


def test_update_core_keeps_the_gui_the_user_installed(core, monkeypatch):
    core["ludex-gui"] = "0.31.0.dev12"
    monkeypatch.setattr(pm.sys, "prefix", "/home/u/.local/share/uv/tools/ludex")
    uv = pm.update_core("beta", dry_run=True)["commands"]
    assert uv == [["/bin/uv", "tool", "install", "--force", "--reinstall", "--with", BETA + "ludex-gui.tar.gz", BETA + "ludex.tar.gz"]]
    assert pm.update_core("stable", dry_run=True)["commands"][0][5:] == ["--with", "ludex-gui", "ludex-games"]
    monkeypatch.setattr(pm.sys, "prefix", "/home/u/.local/pipx/venvs/ludex")
    assert pm.update_core("stable", dry_run=True)["commands"] == [
        ["/bin/pipx", "install", "--force", "ludex-games"],
        ["/bin/pipx", "inject", "--force", "ludex-games", "ludex-gui"],
    ]


@pytest.mark.parametrize(
    ("prefix", "installer"),
    [
        ("/home/u/.local/share/uv/tools/ludex-games", "uv"),
        ("/home/u/.local/pipx/venvs/ludex-games", "pipx"),
        ("/home/u/venv", "pip"),
    ],
)
@pytest.mark.parametrize("channel", ["stable", "beta"])
def test_update_core_preserves_controller_support(core, monkeypatch, prefix, installer, channel):
    monkeypatch.setattr(pm.sys, "prefix", prefix)
    monkeypatch.setattr(pm, "_tool_for_core", lambda: ["python", "-m", "pip"])
    core.update({"ludex-gui": "0.31.0.dev12", "PySDL2": "0.9.17"})
    core_spec = BETA + "ludex.tar.gz" if channel == "beta" else "ludex-games"
    gui_spec = "ludex-gui[gamepad]"
    if channel == "beta":
        gui_spec += f" @ {BETA}ludex-gui.tar.gz"

    commands = pm.update_core(channel, dry_run=True)["commands"]
    if installer == "uv":
        assert commands[0][-3:] == ["--with", gui_spec, core_spec]
    elif installer == "pipx":
        assert commands[-1][-3:] == ["--force", "ludex-games", gui_spec]
    else:
        assert commands[0][-2:] == [core_spec, gui_spec]


def test_update_core_refuses_a_development_install(core, monkeypatch):
    monkeypatch.setattr(pm, "_is_editable", lambda: True)
    with pytest.raises(LudexError) as info:
        pm.update_core("beta", dry_run=True)
    assert info.value.code == "development_install"


@pytest.mark.parametrize(
    "given, passed",
    [
        ("https://github.com/owner/repo", "git+https://github.com/owner/repo"),
        ("https://gitlab.com/owner/repo.git", "git+https://gitlab.com/owner/repo.git"),
        ("https://github.com/owner/repo/", "git+https://github.com/owner/repo/"),
        ("git+https://github.com/owner/repo@v1", "git+https://github.com/owner/repo@v1"),
        ("https://github.com/owner/repo/archive/main.zip", "https://github.com/owner/repo/archive/main.zip"),
        ("https://example.com/owner/repo", "https://example.com/owner/repo"),
    ],
)
def test_a_pasted_repository_link_gets_the_git_prefix_and_nothing_else_is_rewritten(managed, given, passed):
    try:
        pm.add_plugin(given)
    except LudexError:
        pass  # the fake installer registers nothing for these specs; only the spec handed over matters
    assert managed[-1][-1] == passed


def test_plugin_ls_shows_the_link_and_branch_updates_will_use(managed, capsys):
    from ludex_cli.cli import main

    pm.add_plugin("ludex-fakeplug==1.0")
    assert main(["plugin", "ls"]) == 0
    assert "from: ludex-fakeplug==1.0" in capsys.readouterr().out
