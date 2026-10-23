"""Discovery of providers through Python entry points."""
from __future__ import annotations

import re
import sys
from collections import Counter
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points as _entry_points

from .paths import plugins_dir
from .plugins import API_VERSION, GROUP, Command, ConfigField, Provider

_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


def _valid_commands(commands) -> bool:
    try:
        names = [c.name for c in commands]
        return len(set(names)) == len(names) and all(
            isinstance(c, Command) and re.fullmatch(r"[a-z][a-z0-9-]*", c.name) and callable(c.run) for c in commands
        )
    except TypeError:
        return False


def _add_managed_plugins() -> None:
    """Put each ``<state>/plugins/<name>`` folder at the end of ``sys.path`` (ludex's own libraries win)."""
    root = plugins_dir()
    try:
        folders = sorted(
            p for p in root.iterdir()
            if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and not (p / ".disabled").exists()
        )
    except OSError:
        return
    for folder in folders:
        if str(folder) not in sys.path:
            sys.path.append(str(folder))


def _valid_settings(plugin: Provider) -> bool:
    try:
        if not all(isinstance(f, ConfigField) for f in plugin.settings):
            return False
    except TypeError:
        return False
    names = [f.name for f in plugin.settings]
    return (
        len(set(names)) == len(names)
        and all(re.fullmatch(r"[a-z][a-z0-9_]*", n) for n in names)
        and not set(names) & {f.name for f in plugin.config_fields}
    )


def load_providers(
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[dict[str, Provider], dict[str, str]]:
    """Return ``(loaded, problems)`` for the ``ludex.providers`` entry-point group.

    ``loaded`` maps plugin name to its validated ``Provider``; ``problems`` maps the
    names of skipped plugins to a short reason that never includes plugin-supplied text.
    Names registered more than once are rejected without importing any of them.
    """
    if entry_points is None:
        _add_managed_plugins()
    candidates = sorted(
        _entry_points(group=GROUP) if entry_points is None else entry_points,
        key=lambda item: item.name,
    )
    counts = Counter(entry.name for entry in candidates)
    loaded: dict[str, Provider] = {}
    problems: dict[str, str] = {}
    for entry in candidates:
        name = entry.name
        if name in problems or name in loaded:
            continue
        if _NAME.fullmatch(name) is None:
            problems[ascii(name[:40])] = "invalid extension name"
        elif counts[name] > 1:
            problems[name] = "registered more than once"
        else:
            try:
                value = entry.load()
            except (Exception, SystemExit) as exc:
                problems[name] = f"failed to import ({type(exc).__name__})"
                continue
            if type(value) is not Provider:
                problems[name] = "must be a Provider"
            elif type(getattr(value, "api_version", None)) is not int or value.api_version != API_VERSION:
                problems[name] = f"unsupported api_version (ludex requires {API_VERSION})"
            elif not value.capabilities:
                problems[name] = "declares no capability"
            elif not _valid_commands(value.commands):
                problems[name] = "has an invalid command (need unique lowercase names and a callable run)"
            elif not _valid_settings(value):
                problems[name] = "has invalid settings (need unique lowercase names that are not account fields)"
            else:
                loaded[name] = value
    return loaded, problems
