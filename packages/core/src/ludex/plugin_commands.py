"""Run one provider command under the writer lock (shared by the CLI and plugin view actions)."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import LudexError
from .paths import StatePaths
from .plugins import Command, CommandContext, CommandResult, Provider
from .provider_settings import get_values
from .storage import connect, writer_lock


def run_command(
    paths: StatePaths,
    providers: Mapping[str, Provider],
    provider: Provider,
    command: Command,
    args: Sequence[str],
) -> CommandResult:
    """Call ``command.run`` with an open library connection; ``LudexError`` and ``SystemExit`` pass through."""
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            result = command.run(CommandContext(conn, providers, get_values(paths, provider.name)), args)
        except (LudexError, SystemExit):
            raise
        except Exception as exc:
            raise LudexError("command_failed", f"{provider.name} {command.name} failed ({type(exc).__name__})") from None
        finally:
            conn.close()
    if not isinstance(result, CommandResult):
        raise LudexError("command_failed", f"{provider.name} {command.name} returned an invalid result")
    return result
