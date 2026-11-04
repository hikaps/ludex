# Add local, non-store games and exclude folders

To add games that are not from any store (DRM-free downloads, a games drive) to your ludex library, use the `local` source: every non-hidden subfolder of the directory you give is one game, titled with the folder name.

```sh
ludex setup local
# or
ludex account add local games --set path=/mnt/games
ludex import local:games
```

`path` must be absolute (a leading `~` is fine). It may be a pattern such as `/mnt/games/*` to search every folder in it; ludex then keeps the store id as `<matched folder>/<game folder>` so equal names stay distinct (a pattern may match at most 200 folders).

## Exclude folders

`exclude` lists folder names to skip, separated by commas or newlines. Entries are case-insensitive patterns (`*` and `?`):

```sh
ludex account set games --set 'exclude=_unsorted,backup*,steamapps/Proton*'
ludex import local:games
```

A game excluded after it was imported is marked removed by the next import. An unreadable or empty `path` makes the import fail instead of wiping the library, so an unmounted drive is safe.

## Launching

Local games launch through one executable per game, which you can set:

```sh
ludex game set "My Game" --exe bin/game.x86_64
ludex launch "My Game" --dry-run
```

Give a clean title to local folders: [match games to metadata](match-games-to-metadata.md).
