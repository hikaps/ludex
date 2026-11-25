from __future__ import annotations

import json
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


BETA = "https://github.com/hikaps/ludex/releases/download/beta/"


@pytest.fixture
def core(tmp_path, monkeypatch):
    prefix = tmp_path / "venvs" / "ludex-games"
    prefix.mkdir(parents=True)

    class Install:
        version = "0.66.0"
        direct = None

        def read_text(self, name):
            return self.direct

    install = Install()
    monkeypatch.setattr(pm, "distribution", lambda name: install)
    monkeypatch.setattr(pm.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(pm.sys, "prefix", str(prefix))
    monkeypatch.setattr(pm.sys, "_base_executable", "/usr/bin/python3")
    return prefix, install


def _uv_receipt(prefix, *, beta=False, extra=""):
    core = f', url = "{BETA}ludex.tar.gz"' if beta else ""
    gui = f', url = "{BETA}ludex-gui.tar.gz"' if beta else ""
    (prefix / "uv-receipt.toml").write_text(
        f"""[tool]
requirements = [
    {{ name = "ludex-games"{core} }},
    {{ name = "ludex-gui", extras = ["gamepad"]{gui} }},
    {{ name = "addon", extras = ["ui"], specifier = "==1.2" }},
    {{ name = "addon" }},
]
entrypoints = [
    {{ name = "ludex", install-path = "{prefix.parent / 'bin/ludex'}", from = "ludex-games" }},
    {{ name = "addon", install-path = "{prefix.parent / 'bin/addon'}", from = "addon" }},
]
{extra}"""
    )


@pytest.mark.parametrize("beta", [False, True])
def test_update_uses_uvs_recorded_requirements_on_the_same_channel(core, beta):
    prefix, install = core
    _uv_receipt(prefix, beta=beta, extra='constraints = [{ name = "addon", specifier = "==1.2" }]')
    if beta:
        install.direct = json.dumps({"url": BETA + "ludex.tar.gz"})

    result = pm.update_core(None, dry_run=True)

    assert result["channel"] == ("beta" if beta else "stable")
    (command,) = result["commands"]
    native = command[command.index("/bin/uv"):]
    assert native[:4] == ["/bin/uv", "tool", "upgrade", "ludex-games"]
    assert native[4:] == (["--reinstall-package", "ludex-games", "--reinstall-package", "ludex-gui"] if beta else [])
    assert f"UV_TOOL_DIR={prefix.parent}" in command


@pytest.mark.parametrize("beta", [False, True])
def test_uv_switches_only_ludex_sources_and_preserves_extras_and_addons(core, beta):
    prefix, install = core
    _uv_receipt(prefix, beta=not beta)
    if not beta:
        install.direct = json.dumps({"url": BETA + "ludex.tar.gz"})

    (command,) = pm.update_core("beta" if beta else "stable", dry_run=True)["commands"]

    assert command[-1] == (f"ludex-games @ {BETA}ludex.tar.gz" if beta else "ludex-games")
    assert command[command.index("--with") + 1] == (
        f"ludex-gui[gamepad] @ {BETA}ludex-gui.tar.gz" if beta else "ludex-gui[gamepad]"
    )
    assert command[command.index("--with", command.index("--with") + 1) + 1] == "addon[ui]==1.2"
    assert command[command.index("--with-executables-from") + 1] == "addon"
    assert "addon" not in [arg for flag, arg in zip(command, command[1:]) if flag == "--with"]


def test_uv_does_not_switch_when_it_cannot_replay_install_constraints(core, monkeypatch):
    prefix, _ = core
    _uv_receipt(prefix, extra='constraints = [{ name = "addon", specifier = "==1.2" }]')
    monkeypatch.setattr(pm, "_run", lambda *a, **kw: pytest.fail("must not change the install"))

    with pytest.raises(LudexError) as info:
        pm.update_core("beta", dry_run=False)
    assert info.value.code == "channel_switch_unsupported"


def test_pipx_reuses_the_original_install_and_injection_specs(core):
    prefix, install = core
    install.direct = json.dumps({"url": BETA + "ludex.tar.gz"})
    (prefix / "pipx_metadata.json").write_text(json.dumps({
        "main_package": {"package": "ludex-games", "package_or_url": BETA + "ludex.tar.gz"},
        "injected_packages": {"addon": {"package": "addon", "package_or_url": "addon[ui]==1.2"}},
    }))
    (command,) = pm.update_core(None, dry_run=True)["commands"]
    assert command[command.index("/bin/pipx"):] == ["/bin/pipx", "reinstall", "ludex-games", "--python", "/usr/bin/python3"]
    assert "UV_NO_CACHE=1" in command and "PIP_NO_CACHE_DIR=1" in command

    with pytest.raises(LudexError) as info:
        pm.update_core("stable", dry_run=True)
    assert info.value.code == "channel_switch_unsupported"


def test_update_refuses_to_guess_an_unrecorded_install_spec(core, monkeypatch):
    monkeypatch.setattr(pm, "_run", lambda *a, **kw: pytest.fail("must not change the install"))
    with pytest.raises(LudexError) as info:
        pm.update_core(None, dry_run=False)
    assert info.value.code == "install_spec_unknown"


def test_update_core_refuses_a_development_install(core):
    _, install = core
    install.direct = '{"url": "file:///dev/ludex", "dir_info": {"editable": true}}'
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
