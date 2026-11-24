# Library and command line

Everything the GUI does is also a command. `ludex --help` lists them; `ludex COMMAND --help` explains one.

## Accounts and importing

An account is a source plus its settings. `ludex providers` lists what is available and what each can do.

```sh
ludex setup steam                                  # guided: add an account and import it
ludex account add local games --set path='/mnt/games/*'
ludex account ls
ludex account set games --set path=/other/place    # change it; import again afterwards
ludex account rm games
ludex import games                                 # one account
ludex import --all                                 # every account
```

Bundled sources:

| Source | Reads |
|---|---|
| `steam` | Your library through the Steam Web API (your own key), or the local Steam folder only |
| `shortcuts` | Non-Steam shortcuts in Steam |
| `epic` | Legendary's on-disk library cache |
| `heroic` | Heroic sideloaded games |
| `local` | Every subfolder of a directory (or glob such as `/mnt/games/*`) is a game |
| `rawg` | A game database used for matching and details; needs your own API key |

An import is one transaction. Games missing from a *complete* result are marked removed (kept, and restored if they come back); a source that can only see part of a library never removes anything. Re-importing is idempotent. Games several stores share are one entry with all its stores.

## Finding games

```sh
ludex ls                       # all games, 50 at a time
ludex ls portal                # by title
ludex ls --store steam --installed
ludex ls --genre Roguelike     # needs kept details, see Metadata
ludex ls --sort played         # or recent; shows play time
ludex ls --limit 100 --offset 100
ludex ls --removed             # include games removed from a store
ludex show "Portal"            # one game: its copies per store, when it was seen, play time
ludex find "portal"            # search the stores' catalogs (uses the network)
```

## Title matches

When two games probably are the same but ludex is not sure, it queues the pair instead of joining them:

```sh
ludex review                   # list matches that need a decision
ludex merge 12 40              # merge game 40 into game 12
ludex review --dismiss 3       # keep that pair separate
ludex dedupe --dry-run         # preview joining games matched to one database entry
```

## Scripting

`--json` comes before the command and prints `{"ok": true, "data": ...}` to stdout; errors go to stderr as `{"ok": false, "error": {"code", "message"}}`.

```sh
ludex --json ls --limit 500 | jq -r '.data.games[].title'
ludex export --format csv > library.csv          # or json; --removed includes removed games
```

Exit status is 0 on success, 1 for an expected error, 2 for a usage error.

## Settings

`ludex config` shows them; `ludex config KEY VALUE` changes one and `--reset` restores the built-in value.

| Key | Meaning | Default |
|---|---|---|
| `download_dir` | where `download` and `acquire` put games | `~/Games` |
| `prefix_dir` | folder for default Wine prefixes | under the state directory |
| `auto_details` | fetch details and covers for games on screen (the GUI) | yes |
| `auto_match` | look up games no store describes in a database plugin, sending the title to it | no |
| `auto_refresh` | the GUI imports every account when it starts | yes |
| `steam_shortcuts`, `heroic_sideload` | `no` removes those games from the library | no |
| `PLUGIN.SETTING` | a plugin's own settings; secrets are prompted for (`--secret` reads stdin) and never printed | |

## Where data lives

One SQLite library and a few files in the state directory: `$XDG_DATA_HOME/ludex`, or whatever `LUDEX_HOME` points at. Use a scratch directory to try things: `export LUDEX_HOME=$(mktemp -d)`. There is no telemetry and no hosted component, and the core makes no network requests; only plugins do, only when you run a command that needs them.
