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
- **Launch**: `launch` starts a game through its store's client; Windows games run via `umu-run` with Proton builds found by `runners`. Per-game runner, prefix, executable, arguments and environment via `game set` (or `e` in the TUI, which offers the executables it finds in the game folder; `game exes GAME` lists them). A game ludex starts itself (a local folder) runs as a background job with its output in a log: `launch --status`, `launch --stop`. Games started through Steam or Heroic belong to that client and are not tracked.
- **Install**: `install` asks the owning store's client to install a game (Epic goes through Legendary). Started installs run as background jobs: `install --status`, `install --stop`.
- **Metadata**: `metadata` shows description, genres and developer, asked of the plugin once and then kept; `match` picks a game-database entry (bundled: `rawg`, needs your own API key). `metadata --all` fetches it for every game, then `genres` lists the genres and `ls --genre NAME` filters by one (`f` and `d` in the TUI, a genre box in the GUI).
- **Downloads and jobs**: `i` on a Search hit of a plugin that downloads games (it has `acquire`) asks for a folder and downloads there in the background (`ludex download STORE ID`, `--status`, `--stop`); the Jobs tab lists installs, downloads and games ludex started, with progress (a bar and time left when the plugin reports numbers), and `x` stops one; the folder is remembered as `download_dir` (`ludex config download_dir`, default `~/Games`). `ludex acquire STORE ID` uses it when `--to` is left out. Stores with their own client (Steam, Heroic) still open that client, which asks for its own library.
- **Play time**: `show` and `ls --sort played|recent` report how long you played, from what Steam and Heroic (Epic and sideloads) recorded on this machine, plus the games ludex started itself. The TUI shows it in Detail and `o` changes the order.
- **TUI**: `ludex tui` browses, searches and launches games in the terminal. It imports every account when it starts and again on `r` (in the background; `ludex config auto_refresh no` turns the startup import off).
- **GUI**: `pip install ludex-gui` (or `uv tool install ludex-games --with ludex-gui`), then `ludex gui` opens a game launcher (cover-art grid, game pages with Play or Install, launch options and title matching, search, jobs, settings with accounts and plugins, and a sidebar page for every plugin view). Covers come from the Steam and RAWG plugins and are fetched only for games on screen while `ludex config auto_details` is on. It is separate from `ludex-games` because it brings Qt. A game controller drives it when installed with `ludex-gui[gamepad]` (`uv tool install ludex-games --with "ludex-gui[gamepad]"`): D-pad or left stick move, A selects, B goes back, X plays or installs, LB and RB switch pages, Y jumps to search, Start opens a menu with Quit (keyboard: `Ctrl+P`, `Ctrl+PgUp`, `Ctrl+PgDown`). The controller only acts while the launcher window has focus, `ludex gui --console` (or `ludex-gui --console`) opens it fullscreen and 25% larger with the button hints in the status bar, for a TV or a handheld (`QT_SCALE_FACTOR` overrides the size); `ludex gui --install-desktop` adds "Ludex" and "Ludex Console" (with an icon) to the application menu, for example to add them to Steam as non-Steam games; `--uninstall-desktop` removes them. Typing text uses Steam's on-screen keyboard.
- **Scripting**: `ludex --json <command>` prints `{"ok": ..., "data": ...}` (errors go to stderr).
- **Plugins**: `plugin add/ls/view/rm/enable/disable/update` (`plugin view` lists the tables and panels plugins contribute, which the TUI shows as extra tabs); `update` updates ludex from its release channel.

## Install

```sh
uv tool install ludex-games
# Or: pipx install ludex-games
```

The package is `ludex-games`; the command is `ludex`. It bundles `ludex-core` (library and plugin API), `ludex-cli` and `ludex-tui`, which can also be installed on their own (`ludex-cli` alone has no terminal UI; `ludex tui` says so). Each release is tagged `vX.Y.Z` on the [releases page](https://github.com/hikaps/ludex/releases). A rolling pre-release (**beta**) is built from `develop`:

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

A plugin is a `Provider` instance exported from a Python entry point in the group `ludex.providers`. It declares the capabilities it supports (owned games, launch, install, installed, search, metadata, acquire, commands, views) and the core only calls what is declared. Plugins report whether an ownership result is complete; the core removes missing games only then. Install one with `ludex plugin add <package, URL or path>`; it runs with your permissions. The contract, including the `API_VERSION` rules, is documented in the docstrings of [packages/core/src/ludex/plugins.py](https://github.com/hikaps/ludex/blob/main/packages/core/src/ludex/plugins.py).

## Privacy and scope

- No telemetry and no hosted component; everything lives in a local SQLite database (`LUDEX_HOME`, default `$XDG_DATA_HOME/ludex`).
- The core never provides or endorses content; it records what you own.
- The core makes no store requests itself. Network access happens inside plugins (for example the Steam Web API, RAWG, `find`), only when you run a command that needs it.

## How it differs

Lutris, Heroic, Playnite and GOG Galaxy are full game launchers with graphical interfaces, and they do many things ludex does not. ludex has a narrower focus: a command-line library you can script (`--json`, `export`), a documented plugin API, and local-only data, with no GUI launcher to run. It can sit alongside them; it reads Heroic's sideload list and Legendary's cache, and starts games through the store clients.

## Contributing

See [CONTRIBUTING.md](https://github.com/hikaps/ludex/blob/main/CONTRIBUTING.md).

## License

GPL-3.0-or-later.
