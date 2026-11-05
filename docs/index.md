# ludex: a scriptable library of the games you own, across stores

ludex is a headless, scriptable catalog of the games you own on Steam, Epic/Heroic and in local folders, for Linux. It stores everything in a local SQLite database, has a plugin API for stores and metadata, sends no telemetry and has no hosted component. The core never provides or endorses content; store access lives in plugins.

Requires Python 3.11 or newer.

## Install

Install from PyPI with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/). The package is `ludex-games`; the command is `ludex`:

```sh
uv tool install ludex-games
# or
pipx install ludex-games
```

Check it works:

```sh
ludex --version
```

Update a PyPI install with `uv tool upgrade ludex-games` or `pipx upgrade ludex-games`. `ludex update` reinstalls from the rolling `stable` or `beta` build instead (`--channel stable|beta`).

## First steps

```sh
ludex providers      # list available sources and what each can do
ludex setup          # guided: add an account for a source and import it
ludex ls             # list your games
```

## Use cases

- [List the games you own across stores on Linux](use-cases/list-games-across-stores.md)
- [Import your Steam library](use-cases/import-steam-library.md)
- [Write a ludex plugin](use-cases/write-a-plugin.md)

Source code and issues: <https://github.com/hikaps/ludex>.
