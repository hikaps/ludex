# Commands and views

## Commands

`commands` is a sequence of `Command(name, help, run)`. Each becomes `ludex <provider> <name> [args...]`. Names are lowercase letters, digits and `-`. A provider named like a built-in command cannot have commands (the built-in wins).

```python
import argparse

from ludex.library import list_games
from ludex.plugins import Command, CommandResult


def count(ctx, args):
    parser = argparse.ArgumentParser(prog="ludex demo count")
    parser.add_argument("--store")
    ns = parser.parse_args(args)
    games = list_games(ctx.conn, store=ns.store)
    return CommandResult({"count": len(games)}, f"{len(games)} games")


PLUGIN = Provider("demo", "Demo", (), commands=(Command("count", "Count games", count),))
```

- `run(ctx, args)` gets a `CommandContext` (`conn`, `providers`, and `settings`: your plugin-wide settings) and the raw argument strings after the command name. Parse them yourself; `argparse` works, including `-h` and usage errors.
- Return `CommandResult(data, text)`: `data` is printed as JSON under `--json`, `text` otherwise.
- Act on the library through `ludex.library` (`list_games`, `get_game`, `resolve_game`, `run_import`, ...), never raw SQL. The core holds the writer lock for the whole run, so commands are serialized with imports.
- Raise `LudexError(code, message)` with a fixed, secret-free message for expected failures; any other exception is reported as `command_failed` without its text.
- A command that needs a long-running process can use `ludex.services.start_service(ctx.conn, provider, name, argv, cwd=..., settle=...)`, then `stop_service` and `service_status`. It runs as a detached `service` job with its output in a private log, visible on the GUI Jobs page. One service of a given name runs at a time.

## Views

`views` is a tuple of `View(id, title, fetch)`. A frontend lists each as a navigation entry: a sidebar page in `ludex gui`, and `ludex plugin view PLUGIN [VIEW]` on the command line. Ids are lowercase letters, digits and `-`, unique within the provider; `title` is a single line.

`fetch(settings)` receives the plugin-wide settings (never account settings) and returns:

- `ViewTable(columns, rows)`: each `ViewRow(id, cells, actions)` has a string `id` unique in the table and one string cell per column;
- or `ViewDetail(fields)`: a tuple of `(label, value)` pairs.

```python
from ludex.plugins import View, ViewAction, ViewRow, ViewTable


def players(settings):
    return ViewTable(
        ("Name", "State"),
        (ViewRow("alice", ("Alice", "online"), (ViewAction("Kick", "kick", ("alice",)),)),),
    )


views = (View("players", "Players", players),)
```

- A `ViewAction(label, command, args)` names one of this provider's `commands`. The frontend shows the label, asks the user to confirm, and only then runs the command with `args` (no shell). Fetching never runs an action. Actions must not prompt or print.
- Everything is plain text: no markup, no links the frontend opens.
- `fetch` may block; frontends call it off their UI thread. The same rules as `search` apply: bounded responses, verified TLS, fixed secret-free `LudexError` messages (any other exception is reported as `view_failed` without its text).

Needs `ludex-core>=0.61.0`; `API_VERSION` stays 3.
