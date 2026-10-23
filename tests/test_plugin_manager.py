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
    monkeypatch.setattr(pm, "version", lambda name: "0.31.0.dev12")
    monkeypatch.setattr(pm.shutil, "which", lambda name: f"/bin/{name}")


def test_update_core_uses_the_installers_own_command_and_the_installed_channel(core, monkeypatch):
    monkeypatch.setattr(pm.sys, "prefix", "/home/u/.local/share/uv/tools/ludex")
    result = pm.update_core(None, dry_run=True)
    assert result["channel"] == "beta"
    assert result["command"] == ["/bin/uv", "tool", "install", "--reinstall", "https://github.com/hikaps/ludex/releases/download/beta/ludex.tar.gz"]
    monkeypatch.setattr(pm.sys, "prefix", "/home/u/.local/pipx/venvs/ludex")
    assert pm.update_core("stable", dry_run=True)["command"][:3] == ["/bin/pipx", "install", "--force"]


def test_update_core_refuses_when_the_channel_or_install_kind_is_unknown(core, monkeypatch):
    monkeypatch.setattr(pm, "version", lambda name: "0.31.0")
    with pytest.raises(LudexError) as info:
        pm.update_core(None, dry_run=True)
    assert info.value.code == "unknown_channel"
    monkeypatch.setattr(pm, "_is_editable", lambda: True)
    with pytest.raises(LudexError) as info:
        pm.update_core("beta", dry_run=True)
    assert info.value.code == "development_install"
