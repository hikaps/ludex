"""Discovery of ownership plugins through Python entry points."""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from importlib.metadata import EntryPoint, entry_points as _entry_points

from .plugins import API_VERSION, GROUP, SourcePlugin

_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")


def load_sources(
    entry_points: Iterable[EntryPoint] | None = None,
) -> tuple[dict[str, SourcePlugin], dict[str, str]]:
    """Return ``(loaded, problems)`` for the ``ludex.ownership`` entry-point group.

    ``loaded`` maps plugin name to its validated ``SourcePlugin``; ``problems`` maps the
    names of skipped plugins to a short reason that never includes plugin-supplied text.
    Names registered more than once are rejected without importing any of them.
    """
    candidates = sorted(
        _entry_points(group=GROUP) if entry_points is None else entry_points,
        key=lambda item: item.name,
    )
    counts = Counter(entry.name for entry in candidates)
    loaded: dict[str, SourcePlugin] = {}
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
            if type(value) is not SourcePlugin:
                problems[name] = "must be a SourcePlugin"
            elif type(getattr(value, "api_version", None)) is not int or value.api_version != API_VERSION:
                problems[name] = f"unsupported api_version (ludex requires {API_VERSION})"
            else:
                loaded[name] = value
    return loaded, problems
