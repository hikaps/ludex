# Import Epic Games Store and Heroic games on Linux

To import the Epic Games you own into ludex on Linux, point it at the library cache that Legendary or Heroic keeps on disk. No network access and no login are needed. Heroic "Add Game" (sideloaded) entries have their own source.

## Epic

```sh
ludex setup epic
# or
ludex account add epic epic
ludex import epic:epic
```

Optional settings: `legendary_dir` (Legendary config folder, auto-detected from the usual Legendary and Heroic locations when blank) and `install_dir` (where installs go; default `~/Games/Heroic`).

```sh
ludex account add epic epic --set legendary_dir=/path/to/legendary
```

The cache only refreshes when Legendary or Heroic refreshes its library, so it can lag your account. The import is partial: it adds and updates games and removes nothing. DLC entries are skipped.

## Heroic sideloaded games

```sh
ludex setup heroic
```

Optional setting: `heroic_dir` (Heroic config folder, auto-detected when blank). Every sideload entry becomes a game. A missing or unreadable file is an error, never an empty library.

```sh
ludex config heroic_sideload yes   # global switch; "no" removes those games from the library
```

Next: [install an Epic game](install-epic-game-legendary.md).
