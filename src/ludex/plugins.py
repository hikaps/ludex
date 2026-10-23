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
- ``commands``: ``commands``, below.

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

Launching without a client (optional): ``launch_command(config, store_id)`` takes the owning
account's configuration and returns an argument list that starts the game directly (no shell;
``argv[0]`` an absolute path, which also becomes the working directory's folder). The core starts
it detached from the terminal and does not track it afterwards. Raise ``SourceError`` when no
single command can be determined. A provider may declare ``launch_url`` or ``launch_command``;
both count as the ``launch`` capability, and ``launch_url`` wins when both are present.

Game folder (optional): ``game_folder(config, store_id)`` returns the folder a game lives in. With
it, the user can attach launch settings (``ludex game set``: executable, arguments, environment,
and a Proton runner): the core then runs the configured executable itself, through ``umu-run``
when a runner is set, and uses ``launch_command`` only when no executable or runner is set.
Settings arguments and environment also apply to ``launch_command``. Declaring ``game_folder``
counts as the ``launch`` capability.

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

Commands (optional): ``commands`` is a sequence of ``Command(name, help, run)``. Each becomes
``ludex <provider> <name> [args...]`` (names are lowercase letters, digits and ``-``; a provider
named like a built-in command cannot have commands, because the built-in wins). ``run(context,
args)`` receives a ``CommandContext`` (an open library connection and the loaded providers) and
the raw argument strings after the command name; it parses them itself (``argparse`` is fine;
``-h`` and usage errors work as usual) and returns a ``CommandResult(data, text)``: ``data`` is
printed as JSON under ``--json`` and ``text`` otherwise. Act on the library through the functions
in ``ludex.library`` (``list_games``, ``get_game``, ``resolve_game``, ``run_import``, ...), not raw
SQL. The core holds the writer lock for the whole run, so commands are serialized with imports.
Raise ``LudexError`` with a fixed, secret-free message for expected failures; any other exception
is reported as ``command_failed`` without its text. Commands cannot add TUI tabs.

Errors raised by ``fetch`` must carry a fixed, secret-free message: never include API keys,
tokens, or URLs with query strings.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
import sqlite3
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
class CommandContext:
    conn: sqlite3.Connection
    providers: Mapping[str, Provider]


@dataclass(frozen=True, slots=True)
class CommandResult:
    data: object
    text: str = ""


@dataclass(frozen=True, slots=True)
class Command:
    name: str
    help: str
    run: Callable[[CommandContext, Sequence[str]], CommandResult]


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
    launch_command: Callable[[Mapping[str, str], str], Sequence[str]] | None = None
    game_folder: Callable[[Mapping[str, str], str], Path] | None = None
    install_url: Callable[[str], str] | None = None
    acquire: Callable[[AcquireRequest, Callable[[str], None]], AcquireResult] | None = None
    installed: Callable[[Mapping[str, str]], Iterable[str]] | None = None
    search: Callable[[str], Sequence[SearchHit]] | None = None
    commands: Sequence[Command] = ()

    @property
    def capabilities(self) -> tuple[str, ...]:
        found = (("owned", self.fetch), ("installed", self.installed), ("search", self.search), ("launch", self.launch_url or self.launch_command or self.game_folder), ("install", self.install_url), ("acquire", self.acquire), ("commands", self.commands or None))
        return tuple(name for name, value in found if value is not None)
