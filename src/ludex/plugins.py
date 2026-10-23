"""Contract for providers (entry-point group ``ludex.providers``).

A plugin is a ``Provider`` instance exported from an entry point. A provider declares the
capabilities it has by filling the matching field; at least one is required and the core only
calls what is declared (``Provider.capabilities`` lists them):

- ``owned``: ``fetch``, below.
- ``launch``: ``launch_url``, below.
- ``install``: ``install_url``, below.
- ``installed``: ``installed``, below.
- ``search``: ``search``, below.
- ``acquire``: ``acquire``, below.

An owned-only provider needs nothing else. ``API_VERSION`` changes only when an existing field
changes meaning; adding a capability field is compatible and does not change it. A provider whose
``api_version`` differs from the core's is skipped with a reported reason.

Owned: ``fetch`` receives the account's configuration (``ConfigField`` names mapped to strings)
and returns a ``FetchResult``. Only providers with this capability can have accounts.

Completeness contract: ``FetchResult.complete`` is True only when the plugin is sure ``games`` is
every game the account owns on that store; only then may the core mark owned games missing from
the result as removed. A source that can only see part of the library (for example local files)
returns ``complete=False``, and the core adds and updates games but removes nothing. A plugin that
cannot tell whether a result is partial (a private profile, a truncated page, a rate limit) MUST
raise ``SourceError`` instead of returning it.

Installed (optional): ``installed(config)`` returns the store ids of the account's games that are
installed on this machine right now (an iterable of strings). It is read live, never stored, and
must not touch the network. Raise ``SourceError`` when the answer cannot be determined.

Search (optional): ``search(query)`` returns ``SearchHit`` records for a store's catalog (any
game, owned or not). This is the only capability besides ``fetch`` that may use the network; the
same rules apply: bounded responses, verified TLS, ``https`` links only, and errors that are
``SourceError`` with fixed, secret-free messages. The core adds the "owned" marker and merges
results across providers; a failing provider is reported and skipped.

Launching (optional): ``launch_url(store_id)`` returns the URL that makes the store's own client
start the game (for example ``steam://rungameid/<id>``). The core opens it with ``xdg-open``; the
plugin never spawns processes. The URL must percent-encode ``store_id`` and carry no credentials.

Installing (optional): ``install_url(store_id)`` returns the URL that makes the store's own client
offer to install a game the account owns (for example ``steam://install/<id>``). Same rules as
``launch_url``. This is for the owner's official store client only; the core does not download or
unpack anything itself.

Acquiring (optional): ``acquire(request, report)`` gets a ``AcquireRequest`` (store id, title, and a
``destination`` directory the core created) and does the whole job itself: download, unpack, or
drive an official client. It calls ``report(message)`` with short progress lines and returns an
``AcquireResult``: the game's ``directory``, which MUST lie inside ``destination`` (the core checks
this and rejects anything else), and string ``hints`` (for example ``{"executable": "game.sh"}``).
The core ships no implementation and takes no position on where a plugin gets its files; the
plugin's author is responsible for what it fetches and for the rights to it. Same rules as
``search``: bounded responses, verified TLS, fixed secret-free ``SourceError`` messages, nothing
written outside ``destination``.

Errors raised by ``fetch`` must carry a fixed, secret-free message: never include API keys,
tokens, or URLs with query strings.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import LudexError

API_VERSION = 3
GROUP = "ludex.providers"


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
class SearchHit:
    store: str
    store_id: str
    title: str
    url: str
    price: str | None = None


@dataclass(frozen=True, slots=True)
class AcquireRequest:
    store_id: str
    title: str
    destination: Path


@dataclass(frozen=True, slots=True)
class AcquireResult:
    directory: Path
    hints: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FetchResult:
    games: Iterable[OwnedGame]
    complete: bool
    mode: str


@dataclass(frozen=True, slots=True)
class Provider:
    name: str
    help: str
    config_fields: tuple[ConfigField, ...]
    fetch: Callable[[Mapping[str, str]], FetchResult] | None = None
    api_version: int = API_VERSION
    launch_url: Callable[[str], str] | None = None
    install_url: Callable[[str], str] | None = None
    acquire: Callable[[AcquireRequest, Callable[[str], None]], AcquireResult] | None = None
    installed: Callable[[Mapping[str, str]], Iterable[str]] | None = None
    search: Callable[[str], Sequence[SearchHit]] | None = None

    @property
    def capabilities(self) -> tuple[str, ...]:
        found = (("owned", self.fetch), ("installed", self.installed), ("search", self.search), ("launch", self.launch_url), ("install", self.install_url), ("acquire", self.acquire))
        return tuple(name for name, value in found if value is not None)
