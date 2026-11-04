# ludex: a scriptable library of the games you own, across stores

ludex is a headless, scriptable catalog of the games you own on Steam, Epic/Heroic and in local folders, for Linux. It stores everything in a local SQLite database, has a plugin API for stores and metadata, sends no telemetry and has no hosted component. The core never provides or endorses content; store access lives in plugins.

Requires Python 3.11 or newer.

## Install

Install the rolling stable release from the GitHub release tarball with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/):

```sh
uv tool install https://github.com/hikaps/ludex/releases/download/stable/ludex.tar.gz
# or
pipx install https://github.com/hikaps/ludex/releases/download/stable/ludex.tar.gz
```

Check it works, and update later with:

```sh
ludex --version
ludex update
```

## First steps

```sh
ludex providers      # list available sources and what each can do
ludex setup          # guided: add an account for a source and import it
ludex ls             # list your games
```

## Use cases

- [List the games you own across stores on Linux](use-cases/list-games-across-stores.md)
- [Export your game library to JSON or CSV](use-cases/export-library-json.md)
- [Import your Steam library](use-cases/import-steam-library.md)
- [Import Epic and Heroic games](use-cases/import-epic-heroic-games.md)
- [Add local, non-store games and exclude folders](use-cases/add-local-games.md)
- [Match games to metadata by title or by hand](use-cases/match-games-to-metadata.md)
- [Find installed games and install an Epic game through Legendary](use-cases/install-epic-game-legendary.md)
- [Write a ludex plugin](use-cases/write-a-plugin.md)

Source code and issues: <https://github.com/hikaps/ludex>.
