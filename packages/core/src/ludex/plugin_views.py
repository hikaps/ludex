"""Discover, fetch and act on the views providers contribute (see ``ludex.plugins``).

Frontends (the CLI, the GUI) call these functions; none renders anything here.
"""
from __future__ import annotations

from collections.abc import Mapping

from .errors import LudexError
from .paths import StatePaths
from .plugin_commands import run_command
from .plugins import CommandResult, Provider, View, ViewAction, ViewDetail, ViewRow, ViewTable, _view_label
from .provider_settings import get_values

def list_views(providers: Mapping[str, Provider]) -> tuple[tuple[str, View], ...]:
    """Every ``(provider key, view)``: providers sorted by key, each provider's views in declaration order."""
    return tuple((key, view) for key in sorted(providers) for view in providers[key].views)


def get_view(providers: Mapping[str, Provider], provider_key: str, view_id: str) -> View:
    provider = providers.get(provider_key)
    if provider is None:
        raise LudexError("unknown_provider", "unknown provider")
    for view in provider.views:
        if view.id == view_id:
            return view
    raise LudexError("unknown_view", "unknown plugin view")


def _text(value: object, *, multiline: bool = False) -> bool:
    return isinstance(value, str) and not any(
        (ord(c) < 32 and not (multiline and c == "\n")) or 127 <= ord(c) < 160 for c in value
    )


def _valid_action(action: object, commands: frozenset[str]) -> bool:
    return (
        isinstance(action, ViewAction)
        and _view_label(action.label)
        and isinstance(action.command, str)
        and action.command in commands
        and isinstance(action.args, tuple)
        and all(isinstance(a, str) and "\0" not in a for a in action.args)
    )


def _valid_table(table: ViewTable, commands: frozenset[str]) -> bool:
    if not (isinstance(table.columns, tuple) and table.columns and all(_view_label(c) for c in table.columns)):
        return False
    if not isinstance(table.rows, tuple):
        return False
    seen: set[str] = set()
    for row in table.rows:
        if not (isinstance(row, ViewRow) and _view_label(row.id) and row.id not in seen):
            return False
        seen.add(row.id)
        if not (isinstance(row.cells, tuple) and len(row.cells) == len(table.columns) and all(_text(c) for c in row.cells)):
            return False
        if not (isinstance(row.actions, tuple) and all(_valid_action(a, commands) for a in row.actions)):
            return False
    return True


def _valid_detail(detail: ViewDetail) -> bool:
    return isinstance(detail.fields, tuple) and all(
        isinstance(f, tuple) and len(f) == 2 and _view_label(f[0]) and _text(f[1], multiline=True) for f in detail.fields
    )


def fetch_view(paths: StatePaths, provider: Provider, view: View) -> ViewTable | ViewDetail:
    """Call ``view.fetch`` with the plugin-wide settings and validate what it returns."""
    try:
        result = view.fetch(get_values(paths, provider.name))
    except LudexError:
        raise
    except (Exception, SystemExit):
        raise LudexError("view_failed", "plugin view failed") from None
    commands = frozenset(c.name for c in provider.commands)
    if isinstance(result, ViewTable) and _valid_table(result, commands):
        return result
    if isinstance(result, ViewDetail) and _valid_detail(result):
        return result
    raise LudexError("invalid_view_result", "plugin view returned invalid data")


def run_view_action(paths: StatePaths, providers: Mapping[str, Provider], provider_key: str, action: ViewAction) -> CommandResult:
    """Run an action a validated snapshot offered; the frontend confirms with the user before calling."""
    provider = providers.get(provider_key)
    if provider is None:
        raise LudexError("unknown_provider", "unknown provider")
    command = next((c for c in provider.commands if c.name == action.command), None)
    if command is None:
        raise LudexError("unknown_command", "unknown plugin command")
    try:
        result = run_command(paths, providers, provider, command, list(action.args))
    except LudexError:
        raise
    except SystemExit:
        raise LudexError("command_failed", "plugin view command exited") from None
    except Exception:
        raise LudexError("command_failed", "plugin view command failed") from None
    if not isinstance(result.text, str):
        raise LudexError("command_failed", "plugin view command returned invalid text")
    return result
