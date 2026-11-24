# Plugin SDK

A ludex plugin is a Python package that exports one `Provider` instance from the `ludex.providers` entry-point group. The core never provides or endorses content: every store, metadata service and extra command comes from a plugin, and the bundled ones (`steam`, `epic`, `heroic`, `local`, `shortcuts`, `rawg`) use the same API as yours. Their source under [`packages/core/src/ludex/sources/`](https://github.com/hikaps/ludex/tree/main/packages/core/src/ludex/sources) is a set of small, real examples.

| Page | What it covers |
|---|---|
| [Quick start](quickstart.md) | A working plugin in two files, installed and imported |
| [Capabilities](capabilities.md) | Every hook a provider can declare, with its signature and rules |
| [Commands and views](commands-and-views.md) | Your own `ludex <plugin> <command>` commands, and pages in the GUI |
| [Packaging and testing](packaging.md) | Entry points, installing, versioning, offline tests, rules every plugin follows |

## The model

- A `Provider` declares what it can do by filling fields. At least one capability is required, and the core calls only what is declared. `Provider.capabilities` lists them.
- Capabilities: `owned` (`fetch`), `installed`, `search`, `metadata`, `match`, `cover`, `launch`, `install`, `playtime`, `running`, `actions`, `acquire`, `commands`, `views`.
- Only a provider with `fetch` can have accounts. Users add an account for it, then `ludex import` stores what `fetch` returns in the local SQLite library.
- The core calls hooks from its own threads and connections. Your code never touches the database directly, except through the functions in `ludex.library` from a command.
- Network access belongs only in plugins, and only in the hooks that document it.

## Compatibility

- `API_VERSION` is currently `3`. It changes only when an existing field changes meaning. Adding a capability field is compatible and does not change it, so a plugin written for an older core keeps working, and a plugin that uses a newer field needs a core that has it (the capabilities page names the version for the recent ones).
- A provider whose `api_version` differs from the core's is skipped, with the reason shown by `ludex providers`.
- Do not declare `ludex` as a dependency. If you must, declare `ludex-core`; the copy that gets installed is ignored in favor of the running one.
- A broken plugin never breaks ludex: it is skipped and reported, and the rest keep working.

## Where the contract lives

The docstrings of [`ludex.plugins`](https://github.com/hikaps/ludex/blob/main/packages/core/src/ludex/plugins.py) and [`ludex.library`](https://github.com/hikaps/ludex/blob/main/packages/core/src/ludex/library.py) are the source of truth. These pages explain them; when they disagree, the docstrings win.
