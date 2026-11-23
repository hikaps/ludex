# ludex: every game you own, in one local library

ludex is a headless, scriptable catalog of the games you own on Steam, Epic/Heroic and in local folders, for Linux. It stores everything in a local SQLite database, has a plugin API for stores and metadata, sends no telemetry and has no hosted component. The core never provides or endorses content; store access lives in plugins.

Use it from the command line or the desktop launcher (`ludex gui`, installed separately), which a game controller can drive and which has a fullscreen console mode for a TV or handheld.

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

Update a PyPI install with `uv tool upgrade ludex-games` or `pipx upgrade ludex-games`. `ludex update` does the same for the channel this install came from (`--channel stable|beta`; stable is PyPI, beta is the rolling pre-release) and keeps `ludex-gui` if it is installed. To add the GUI to a beta install: `uv tool install https://github.com/hikaps/ludex/releases/download/beta/ludex.tar.gz --with https://github.com/hikaps/ludex/releases/download/beta/ludex-gui.tar.gz`.

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
