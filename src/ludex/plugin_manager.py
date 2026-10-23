"""Install, list, update and remove plugins, and update ludex itself.

Plugins are ordinary Python packages that register in the ``ludex.providers`` entry-point group.
Managed ones live in ``<state>/plugins/<name>/``, one self-contained folder each (the package and
its own dependencies), added to the *end* of ``sys.path`` so they survive ludex upgrades and can
never shadow ludex's own libraries. Removing a plugin deletes its folder; accounts and games it
imported stay until ``ludex account rm``. A plugin runs with your permissions: install only code
you trust. ludex opens no connection itself: ``uv`` or ``pip`` does the downloading (TLS verified),
and only when you run ``plugin add``, ``plugin update`` or ``update``.

ponytail: managed plugins are installed with uv, else pip; pipx-style isolation per plugin, version
pinning and checksums are left to the spec you pass (for example ``name==1.2`` or a wheel path). A plugin must not
declare ludex as a dependency (it would install a second copy); it imports the running one.
"""
from __future__ import annotations

import json
import re
import secrets
import shutil
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distributions, entry_points, version
from pathlib import Path
from typing import Any

from .errors import LudexError
from .paths import plugins_dir
from .plugins import GROUP

_SIDECAR = ".ludex-plugin.json"
_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}\Z")
_CREDENTIALS = re.compile(r"://[^/@\s]*:[^/@\s]*@")
_RELEASES = "https://github.com/hikaps/ludex/releases/download/{channel}/ludex.tar.gz"
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
    return spec


def _providers(directory: Path) -> list[tuple[str, str, list[str]]]:
    """(dist name, version, provider names) for each plugin distribution inside ``directory``."""
    found = []
    for dist in distributions(path=[str(directory)]):
        names = [ep.name for ep in dist.entry_points if ep.group == GROUP]
        if names:
            found.append((_canonical(dist.metadata["Name"] or ""), dist.version or "?", sorted(names)))
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
    return {"name": folder.name, "version": ver, "providers": names, "spec": _read_spec(folder)}


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
        if not _NAME.fullmatch(name) or name == "ludex":
            raise LudexError("not_a_plugin", "that package name cannot be used as a plugin")
        taken = {ep.name for ep in entry_points(group=GROUP) if ep.dist is not None and _canonical(ep.dist.name) != name}
        clash = sorted(set(provider_names) & taken)
        if clash:
            raise LudexError("provider_exists", f"provider name already provided by another package: {', '.join(clash)}")
        (staging / _SIDECAR).write_text(json.dumps({"spec": spec}), encoding="utf-8")
        destination = root / name
        previous = None
        if destination.exists():
            previous = root / f".old-{secrets.token_hex(6)}"
            destination.rename(previous)
        staging.rename(destination)
        if previous is not None:
            shutil.rmtree(previous, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"name": name, "version": ver, "providers": provider_names}


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

        return bool(json.loads(distribution("ludex").read_text("direct_url.json") or "{}").get("dir_info", {}).get("editable"))
    except (PackageNotFoundError, ValueError, AttributeError):
        return False


def update_core(channel: str | None, dry_run: bool) -> dict[str, Any]:
    """Reinstall ludex from the rolling release for ``channel`` (default: the channel installed)."""
    try:
        current = version("ludex")
    except PackageNotFoundError:
        raise LudexError("not_installed", "ludex is not installed as a package, so it cannot update itself") from None
    if _is_editable():
        raise LudexError("development_install", "this is a development install; update it with git instead")
    if channel is None:
        channel = "beta" if ".dev" in current else "stable" if ".post" in current else None
        if channel is None:
            raise LudexError("unknown_channel", "cannot tell which channel this install came from; pass --channel stable|beta")
    url = _RELEASES.format(channel=channel)
    prefix = Path(sys.prefix).as_posix()
    if "/uv/tools/" in prefix and shutil.which("uv"):
        command = [shutil.which("uv") or "uv", "tool", "install", "--reinstall", url]
    elif "/pipx/venvs/" in prefix and shutil.which("pipx"):
        command = [shutil.which("pipx") or "pipx", "install", "--force", url]
    else:
        command = [*_tool_for_core(), "install", "--upgrade", "--force-reinstall", "--no-input", url]
    result: dict[str, Any] = {"channel": channel, "from": current, "command": command}
    if dry_run:
        return result | {"dry_run": True}
    _run(command)
    try:
        done = subprocess.run(
            [sys.executable, "-c", "import importlib.metadata as m; print(m.version('ludex'))"],
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
