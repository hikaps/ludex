# ludex

[![Tests](https://github.com/hikaps/ludex/actions/workflows/tests.yml/badge.svg?branch=develop)](https://github.com/hikaps/ludex/actions/workflows/tests.yml)
[![Rolling packages](https://github.com/hikaps/ludex/actions/workflows/releases.yml/badge.svg?branch=main)](https://github.com/hikaps/ludex/actions/workflows/releases.yml)

**beets for games.** A headless, scriptable, local-only library of the games you own across stores. Linux first, Python 3.11+, SQLite.

## The problem

Your games are spread over Steam, Epic, Heroic sideloads and folders on a drive. Which games do you own, which store has them, and which are installed on this machine? ludex imports ownership from each store into one local database you can search, script and export, then launches or installs a game through the store that owns it.

Status: early development.

## Features

- **Sources** (bundled plugins): `steam` (Web API with your own key, or the local Steam folder), `shortcuts` (non-Steam shortcuts in Steam), `epic` (Legendary's on-disk library cache), `heroic` (Heroic sideloaded games), `local` (every subfolder of a directory or glob is a game).
- **Library**: `import`, `ls` (query, `--store`, `--account`, `--installed`, `--removed`), `show`, `find` (search store catalogs), `export` (JSON or CSV), `review` and `merge` for title matches that need a decision.
- **Launch**: `launch` starts a game through its store's client; Windows games run via `umu-run` with Proton builds found by `runners`. Per-game runner, prefix, executable, arguments and environment via `game set`.
- **Install**: `install` asks the owning store's client to install a game (Epic goes through Legendary). Started installs run as background jobs: `install --status`, `install --stop`.
- **Metadata**: `metadata` shows description, genres and developer, asked of the plugin once and then kept; `match` picks a game-database entry (bundled: `rawg`, needs your own API key).
- **TUI**: `ludex tui` browses, searches and launches games in the terminal.
- **Scripting**: `ludex --json <command>` prints `{"ok": ..., "data": ...}` (errors go to stderr).
- **Plugins**: `plugin add/ls/rm/enable/disable/update`; `update` updates ludex from its release channel.

## Install

```sh
uv tool install ludex-games
# Or: pipx install ludex-games
```

The package is `ludex-games`; the command is `ludex`. Rolling builds are also published from `main` (**stable**) and `develop` (**beta**); see [releases](https://github.com/hikaps/ludex/releases):

```sh
uv tool install https://github.com/hikaps/ludex/releases/download/beta/ludex.tar.gz
```

## Quick start

Use a scratch directory first if you only want to try it: `export LUDEX_HOME=$(mktemp -d)`.

```sh
ludex providers                                        # bundled and installed plugins
ludex account add local games --set path='/mnt/games/*'
ludex import --all
ludex ls --installed
ludex show "Some Game"
ludex launch "Some Game" --dry-run                     # show the command, don't start it
ludex --json ls --limit 500 | jq -r '.data.games[].title'
ludex export --format csv > library.csv
```

`ludex setup` walks through adding an account and importing it.

## Plugins

A plugin is a `Provider` instance exported from a Python entry point in the group `ludex.providers`. It declares the capabilities it supports (owned games, launch, install, installed, search, metadata, acquire, commands) and the core only calls what is declared. Plugins report whether an ownership result is complete; the core removes missing games only then. Install one with `ludex plugin add <package, URL or path>`; it runs with your permissions. The contract, including the `API_VERSION` rules, is documented in the docstrings of [src/ludex/plugins.py](src/ludex/plugins.py).

## Privacy and scope

- No telemetry and no hosted component; everything lives in a local SQLite database (`LUDEX_HOME`, default `$XDG_DATA_HOME/ludex`).
- The core never provides or endorses content; it records what you own.
- The core makes no store requests itself. Network access happens inside plugins (for example the Steam Web API, RAWG, `find`), only when you run a command that needs it.

## How it differs

Lutris, Heroic, Playnite and GOG Galaxy are full game launchers with graphical interfaces, and they do many things ludex does not. ludex has a narrower focus: a command-line library you can script (`--json`, `export`), a documented plugin API, and local-only data, with no GUI launcher to run. It can sit alongside them; it reads Heroic's sideload list and Legendary's cache, and starts games through the store clients.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

GPL-3.0-or-later.
