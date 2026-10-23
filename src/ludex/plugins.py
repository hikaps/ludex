"""Contract for ownership-source plugins (entry-point group ``ludex.ownership``).

A plugin is a ``SourcePlugin`` instance exported from an entry point. ``fetch`` receives the
account's configuration (``ConfigField`` names mapped to strings) and returns a ``FetchResult``.

Completeness contract: ``FetchResult.complete`` is True only when the plugin is sure ``games`` is
every game the account owns on that store; only then may the core mark owned games missing from
the result as removed. A source that can only see part of the library (for example local files)
returns ``complete=False``, and the core adds and updates games but removes nothing. A plugin that
cannot tell whether a result is partial (a private profile, a truncated page, a rate limit) MUST
raise ``SourceError`` instead of returning it.

Errors raised by ``fetch`` must carry a fixed, secret-free message: never include API keys,
tokens, or URLs with query strings.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import LudexError

API_VERSION = 2
GROUP = "ludex.ownership"


class SourceError(LudexError):
    """A source plugin could not complete a fetch."""


@dataclass(frozen=True, slots=True)
class OwnedGame:
    store: str
    store_id: str
    title: str
    extra: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConfigField:
    name: str
    help: str
    secret: bool = False
    optional: bool = False
    path: bool = False  # value is a filesystem path; interactive prompts offer tab completion


@dataclass(frozen=True, slots=True)
class FetchResult:
    games: Iterable[OwnedGame]
    complete: bool
    mode: str


@dataclass(frozen=True, slots=True)
class SourcePlugin:
    name: str
    help: str
    config_fields: tuple[ConfigField, ...]
    fetch: Callable[[Mapping[str, str]], FetchResult]
    api_version: int = API_VERSION
