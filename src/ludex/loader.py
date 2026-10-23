"""Discovery of providers through Python entry points."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points as _entry_points

from .plugins import API_VERSION, GROUP, Provider

_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


def load_providers(
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[dict[str, Provider], dict[str, str]]:
    """Return ``(loaded, problems)`` for the ``ludex.providers`` entry-point group.

    ``loaded`` maps plugin name to its validated ``Provider``; ``problems`` maps the
    names of skipped plugins to a short reason that never includes plugin-supplied text.
    Names registered more than once are rejected without importing any of them.
    """
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
            else:
                loaded[name] = value
    return loaded, problems
