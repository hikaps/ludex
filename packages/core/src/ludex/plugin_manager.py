"""Install, list, update and remove plugins, and update ludex itself.

Plugins are ordinary Python packages that register in the ``ludex.providers`` entry-point group.
Managed ones live in ``<state>/plugins/<name>/``, one self-contained folder each (the package and
its own dependencies), added to the *end* of ``sys.path`` so they survive ludex upgrades and can
never shadow ludex's own libraries. Removing a plugin deletes its folder; accounts and games it
imported stay until ``ludex account rm``. A plugin runs with your permissions: install only code
you trust. ludex opens no connection itself: ``uv`` or ``pip`` does the downloading (TLS verified),
and only when you run ``plugin add``, ``plugin update`` or ``update``.

ponytail: managed plugins are installed with uv, else pip; pipx-style isolation per plugin, version
pinning and checksums are left to the spec you pass (for example ``name==1.2`` or a wheel path). A plugin may declare
``ludex-core`` as a dependency; the copy installed into its folder (and that copy's built-in providers) is ignored in
favor of the running one, so a requirement that cannot be satisfied on the index still blocks the install.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path
from typing import Any

from .errors import LudexError
from .loader import installed_provider_entries, is_reserved_project
from .paths import plugins_dir
from .plugins import GROUP

_SIDECAR = ".ludex-plugin.json"
_DISABLED = ".disabled"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_REPO_LINK = re.compile(r"https://(?:www\.)?(?:github|gitlab)\.com/[\w.-]+/[\w.-]+?(?:\.git)?/?\Z")
_CREDENTIALS = re.compile(r"://[^/@\s]*:[^/@\s]*@")
_BETA = "https://github.com/hikaps/ludex/releases/download/beta/"
_DIST = "ludex-games"
_GUI = "ludex-gui"
CHANNELS = ("stable", "beta")


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _run(command: list[str]) -> None:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=900, stdin=subprocess.DEVNULL)
    except FileNotFoundError:
        raise LudexError("installer_missing", f"cannot run {command[0]}") from None
    except subprocess.TimeoutExpired:
        raise LudexError("install_failed", "the installer took longer than 15 minutes") from None
    if done.returncode != 0:
        tail = " | ".join(line.strip() for line in done.stderr.strip().splitlines()[-3:])
        raise LudexError("install_failed", f"{Path(command[0]).name} failed: {tail[:400] or 'no output'}")


def _tool(*, uv_only: bool = False) -> list[str]:
    uv = shutil.which("uv")
    if uv:
        return [uv, "pip"]
    if uv_only:
        raise LudexError("installer_missing", "uv was not found on PATH")
    try:
        import pip  # noqa: F401
    except ImportError:
        raise LudexError("installer_missing", "plugins need uv or pip to install; neither is available") from None
    return [sys.executable, "-m", "pip"]


def _install_command(target: Path, spec: str, upgrade: bool) -> list[str]:
    tool = _tool()
    command = [*tool, "install", "--target", str(target)]
    if tool[-1] == "pip" and Path(tool[0]).name == "uv":
        command += ["--python", sys.executable]
    else:
        command += ["--no-input", "--disable-pip-version-check"]
    if upgrade:
        command.append("--upgrade")
    return [*command, spec]


def _check_spec(spec: str) -> str:
    spec = spec.strip()
    if not spec or spec.startswith("-") or "\n" in spec or "\0" in spec:
        raise LudexError("invalid_spec", "give a package name, URL or path (not an option)")
    if _CREDENTIALS.search(spec):
        raise LudexError("invalid_spec", "the spec must not contain credentials; use ssh or a credential helper")
    if _REPO_LINK.fullmatch(spec):  # a pasted repository link: pip needs the git+ prefix
        spec = "git+" + spec
    return spec


def _providers(directory: Path) -> list[tuple[str, str, list[str]]]:
    """(dist name, version, provider names) for each plugin distribution inside ``directory``."""
    found = []
    for dist in distributions(path=[str(directory)]):
        name = _canonical(dist.metadata["Name"] or "")
        names = [ep.name for ep in dist.entry_points if ep.group == GROUP]
        if names and not is_reserved_project(name):  # a copy of ludex's own providers brought in by a ludex-core dependency
            found.append((name, dist.version or "?", sorted(names)))
    return found


def _read_spec(folder: Path) -> str | None:
    try:
        spec = json.loads((folder / _SIDECAR).read_text(encoding="utf-8")).get("spec")
    except (OSError, ValueError, AttributeError):
        return None
    return spec if isinstance(spec, str) else None


def _entry(folder: Path) -> dict[str, Any] | None:
    found = _providers(folder)
    if not found:
        return None
    name, ver, names = found[0]
    return {
        "name": folder.name, "version": ver, "providers": names, "spec": _read_spec(folder),
        "enabled": not (folder / _DISABLED).exists(),
    }


def list_plugins() -> list[dict[str, Any]]:
    root = plugins_dir()
    if not root.is_dir():
        return []
    entries = (_entry(p) for p in sorted(root.iterdir()) if p.is_dir() and not p.is_symlink() and not p.name.startswith("."))
    return [e for e in entries if e]


def _find(name: str) -> dict[str, Any]:
    """A managed plugin by package name or by one of its provider names."""
    key = _canonical(name)
    for plugin in list_plugins():
        if key == plugin["name"] or name in plugin["providers"]:
            return plugin
    raise LudexError("plugin_not_found", f"no managed plugin named {name}; see 'ludex plugin ls'")


def add_plugin(spec: str, *, upgrade: bool = False) -> dict[str, Any]:
    """Install ``spec`` as a managed plugin (replacing the same plugin when it is already there)."""
    spec = _check_spec(spec)
    root = plugins_dir()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = root / f".tmp-{secrets.token_hex(6)}"
    staging.mkdir(mode=0o700)
    try:
        _run(_install_command(staging, spec, upgrade))
        found = _providers(staging)
        if len(found) != 1:
            raise LudexError(
                "not_a_plugin",
                "that package registers no ludex plugin (no ludex.providers entry point)" if not found
                else "that spec installs more than one plugin; add them one at a time",
            )
        name, ver, provider_names = found[0]
        if not _NAME.fullmatch(name) or name in (_DIST, "ludex"):
            raise LudexError("not_a_plugin", "that package name cannot be used as a plugin")
        taken = {ep.name for ep in installed_provider_entries() if ep.dist is not None and _canonical(ep.dist.name) != name}
        clash = sorted(set(provider_names) & taken)
        if clash:
            raise LudexError("provider_exists", f"provider name already provided by another package: {', '.join(clash)}")
        (staging / _SIDECAR).write_text(json.dumps({"spec": spec}), encoding="utf-8")
        destination = root / name
        previous = None
        if destination.exists():
            if (destination / _DISABLED).exists():  # an update keeps the plugin disabled
                (staging / _DISABLED).touch()
            previous = root / f".old-{secrets.token_hex(6)}"
            destination.rename(previous)
        staging.rename(destination)
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"name": name, "version": ver, "providers": provider_names}


def set_plugin_enabled(name: str, enabled: bool) -> dict[str, Any]:
    """Enable or disable a managed plugin; a disabled one is not loaded (takes effect on the next run)."""
    plugin = _find(name)
    marker = plugins_dir() / plugin["name"] / _DISABLED
    if enabled:
        marker.unlink(missing_ok=True)
    else:
        marker.touch()
    return {"name": plugin["name"], "providers": plugin["providers"], "enabled": enabled}


def remove_plugin(name: str) -> dict[str, Any]:
    plugin = _find(name)
    shutil.rmtree(plugins_dir() / plugin["name"])
    return {"name": plugin["name"], "providers": plugin["providers"]}


def update_plugins(name: str | None = None) -> list[dict[str, Any]]:
    """Reinstall each managed plugin (or ``name``) from the spec it was added with."""
    plugins = list_plugins()
    if name is not None:
        plugins = [_find(name)]
    results = []
    for plugin in plugins:
        record: dict[str, Any] = {"name": plugin["name"], "from": plugin["version"]}
        try:
            if plugin["spec"] is None:
                raise LudexError("no_spec", "its install spec is unknown; remove and add it again")
            record |= {"ok": True, "to": add_plugin(plugin["spec"], upgrade=True)["version"]}
        except LudexError as exc:
            record |= {"ok": False, "error": {"code": exc.code, "message": exc.message}}
        results.append(record)
    return results


def _is_editable() -> bool:
    try:
        from importlib.metadata import distribution

        return bool(json.loads(distribution(_DIST).read_text("direct_url.json") or "{}").get("dir_info", {}).get("editable"))
    except (PackageNotFoundError, ValueError, AttributeError):
        return False


def _gui_installed() -> bool:
    try:
        version(_GUI)
    except PackageNotFoundError:
        return False
    return True


def update_core(channel: str | None, dry_run: bool) -> dict[str, Any]:
    """Reinstall ludex-games from PyPI (``stable``) or the rolling beta release, keeping ludex-gui if it is installed."""
    try:
        current = version(_DIST)
    except PackageNotFoundError:
        raise LudexError("not_installed", "self-update requires ludex-games; upgrade ludex-cli with your installer") from None
    if _is_editable():
        raise LudexError("development_install", "this is a development install; update it with git instead")
    if channel is None:
        channel = "beta" if ".dev" in current else "stable"
    core, gui = (_BETA + "ludex.tar.gz", _BETA + "ludex-gui.tar.gz") if channel == "beta" else (_DIST, _GUI)
    with_gui = _gui_installed()
    prefix = Path(sys.prefix).as_posix()
    if "/uv/tools/" in prefix and shutil.which("uv"):
        uv = shutil.which("uv") or "uv"
        commands = [[uv, "tool", "install", "--force", "--reinstall", *(["--with", gui] if with_gui else []), core]]
    elif "/pipx/venvs/" in prefix and shutil.which("pipx"):
        pipx = shutil.which("pipx") or "pipx"
        commands = [[pipx, "install", "--force", core], *([[pipx, "inject", "--force", _DIST, gui]] if with_gui else [])]
    else:
        commands = [[*_tool_for_core(), "install", "--upgrade", "--force-reinstall", "--no-input", core, *([gui] if with_gui else [])]]
    result: dict[str, Any] = {"channel": channel, "from": current, "commands": commands}
    if dry_run:
        return result | {"dry_run": True}
    for command in commands:
        _run(command)
    try:
        done = subprocess.run(
            [sys.executable, "-c", f"import importlib.metadata as m; print(m.version({_DIST!r}))"],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
        )
        result["to"] = done.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        result["to"] = None
    return result


def _tool_for_core() -> list[str]:
    try:
        import pip  # noqa: F401
    except ImportError:
        raise LudexError(
            "installer_missing",
            "cannot tell how ludex was installed; reinstall it the way you first did (uv tool, pipx or pip)",
        ) from None
    return [sys.executable, "-m", "pip"]
