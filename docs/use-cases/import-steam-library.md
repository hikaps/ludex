# Import your Steam library

To import your Steam library into ludex, add a `steam` account and import it. There are two modes, chosen by the account settings.

- **With a Steam Web API key:** the whole library is fetched; games no longer owned are marked removed. Your profile's game details must be public, otherwise the import fails rather than risk an incomplete result.
- **Without a key:** ludex reads the local Steam folder (installed games plus licensed games from the client cache). This is partial, so nothing is ever removed.

Settings (all optional): `api_key` (secret), `steam_id` (SteamID64, detected from the local Steam folder when blank), `steam_dir` (auto-detected when blank).

## Guided

```sh
ludex setup steam
```

## Step by step

```sh
ludex account add steam steam --set steam_id=YOUR_STEAMID64
ludex import steam:steam
```

Secret fields cannot be passed on the command line; `account add` prompts for the API key (or reads it from stdin) and Enter skips it. To change settings later:

```sh
ludex account set steam --set steam_dir=/path/to/Steam
ludex account set steam --secret api_key
ludex import steam:steam
```

Re-importing is safe: existing games are kept, new ones are added, removed ones that return are restored.

## Steam non-Steam shortcuts

```sh
ludex config steam_shortcuts yes
```

Setting it to `no` removes those games from the library.

Next: [list your games](list-games-across-stores.md).
