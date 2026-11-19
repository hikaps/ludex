"""Which owned games are installed right now, asked live from the providers that can tell."""
from __future__ import annotations

from collections.abc import Mapping

from .accounts import get_account, list_accounts
from .paths import StatePaths
from .plugins import Provider


def installed_keys(paths: StatePaths, providers: Mapping[str, Provider]) -> tuple[set[tuple[str, str]], dict[str, str]]:
    """Return ``({(store, store_id)}, {account ref: reason})`` over every account whose provider can tell.

    A failing account is reported by its secret-free reason and skipped; the rest still count.
    """
    keys: set[tuple[str, str]] = set()
    problems: dict[str, str] = {}
    for name, source in list_accounts(paths):
        provider = providers.get(source)
        if provider is None or provider.installed is None:
            continue
        ref = f"{source}:{name}"
        try:
            ids = provider.installed(get_account(paths, ref).config)
            keys.update((source, str(store_id)) for store_id in ids)
        except Exception as exc:
            problems[ref] = getattr(exc, "message", f"failed ({type(exc).__name__})")
    return keys, problems
