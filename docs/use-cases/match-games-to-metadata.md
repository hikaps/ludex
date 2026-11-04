# Match games to metadata by title or by hand

To give a local game a proper title, description and genres, ludex can look it up by name in a game-database plugin. The bundled `rawg` plugin uses the RAWG database and needs your own API key. Matching sends the game title to that service, so it only happens when you ask.

```sh
ludex config rawg.api_key --secret     # prompts for the key (never printed)
```

## Look up details

```sh
ludex metadata "My Game"               # description, genres, developer (cached after the first ask)
ludex metadata "My Game" --refresh     # ask the plugin again
ludex metadata "My Game" --match       # for a game no store describes, look it up by name
ludex config auto_match yes            # do that automatically
```

## Choose the match by hand

```sh
ludex match "My Game"                  # list candidates for the folder name (tags and version stripped)
ludex match "My Game" "Hollow Knight"  # search for something else
ludex match "My Game" --use rawg:3328  # keep that candidate's title and details
ludex match "My Game" --clear          # forget it; go back to the folder name
```

Candidates are listed as `PLUGIN:ID`; pass one to `--use`. With `auto_match`, only a hit whose title equals the cleaned folder name is accepted.

Merge duplicates of one game with `ludex review` and `ludex merge`; see [list games](list-games-across-stores.md).
