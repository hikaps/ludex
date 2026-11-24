# Details, matching and covers

Descriptions, genres, developers, release dates and cover art come from plugins, are asked for once and then kept in the library.

```sh
ludex metadata "Some Game"             # asks the plugin once, then uses the kept answer
ludex metadata --refresh "Some Game"   # ask again
ludex metadata --all                   # every game without details (one request each; can take minutes)
ludex genres                           # genres in the kept details, with counts
ludex ls --genre Roguelike
```

## Matching

A game from a source that supplies no details (a folder of local games) can be matched to a game-database entry, which gives it a proper title and details. The bundled database plugin is `rawg`, which needs your own API key:

```sh
ludex config rawg.api_key --secret
ludex match "hades_v1.2"               # list candidates for the cleaned folder name
ludex match "hades_v1.2" --use rawg:12345
ludex match "hades_v1.2" --clear       # forget it
ludex config auto_match yes            # match automatically (sends the title to the service)
```

Games matched to the same database entry, or to the Steam entry of a game you own, become one game. Your own choice replaces an automatic match, survives a refresh, and can be cleared. The GUI game page links to the matched entry: RAWG's terms require crediting it with an active hyperlink, and `ludex metadata` prints the same URL.

## Covers

Cover art is fetched by the plugin that has it (Steam, RAWG) and only for games on screen, and only while `auto_details` is on (`ludex config auto_details no` stops it). The core validates and caches the file and never decodes the image.

A game no store has art for (a Heroic or local game) can get a portrait cover from SteamGridDB, which is looked up by the game's name:

```sh
ludex config steamgriddb.api_key --secret   # your own key: steamgriddb.com/profile/preferences/api
```

Setting the key is the consent: from then on the cleaned title of each such game on screen is sent to SteamGridDB, once (the answer, or a miss for a week, is kept). Only a game whose name equals the title is used, never a similar one, so a game it does not know keeps the placeholder. Remove the key and nothing is sent.
