# Capabilities

Fill the matching `Provider` field to declare a capability. Everything except `name`, `help` and `config_fields` is optional, and a provider needs at least one capability. Functions that take `config` receive the owning account's field values (plus the plugin-wide settings, see below) as a mapping of strings.

```python
Provider(
    "demo", "A demo store", (ConfigField("token", "API token", secret=True),),
    fetch,                                   # owned
    installed=installed, launch_url=launch_url, install_url=install_url,
    search=search, metadata=metadata, cover=cover, cover_by_title=cover_by_title,
    playtime=playtime, running=running, actions=actions,
    acquire=acquire,
    settings=(ConfigField("api_key", "Catalog API key", secret=True),),
)
```

## Configuration fields

A `ConfigField(name, help, ...)` has a `kind`: `"text"` (default), `"yes_no"` (a switch; the plugin receives `"yes"` or `"no"`, and a value never set is absent) or `"choice"` (one of `choices`, a dropdown). `secret=True` and `path=True` apply to text. Names are `[a-z][a-z0-9_]*`. `optional=True` lets the user leave it blank. The core validates a value before storing it.

- `config_fields` are asked per account (`ludex account add`).
- `settings` are set once for the whole plugin (`ludex config <plugin>.<name> VALUE`, or the GUI Settings page). Secret ones are prompted for and never printed. They are merged under the account fields in the mapping every hook receives, and a command reads them from `ctx.settings`. `search`, `metadata`, `match` and `cover` receive them only when they declare a parameter named `settings`; `install_url` and `launch_url` get no config.

## Owned: `fetch(config) -> FetchResult`

Returns `FetchResult(games, complete, mode)` with `OwnedGame(store, store_id, title)` records. `store` is your provider's name; `store_id` must be stable.

**The completeness contract.** `complete` is True only when you are sure `games` is every game the account owns. Only then may the core mark owned games missing from the result as removed. A source that sees only part of a library (local files) returns `complete=False`; the core adds and updates but removes nothing. When you cannot tell whether a result is partial (a private profile, a truncated page, a rate limit), raise `SourceError` instead of returning it.

## Installed: `installed(config) -> Iterable[str]`

Store ids of the account's games installed on this machine now. Read live, never stored, no network. Raise `SourceError` when it cannot be determined.

## Launch and install

- `launch_url(store_id) -> str`: the URL that makes the store's client start the game (for example `steam://rungameid/<id>`). The core opens it with `xdg-open`; you never spawn processes. Percent-encode `store_id`; no credentials in the URL.
- `launch_command(config, store_id) -> Sequence[str]`: an argument list that starts the game directly (no shell; `argv[0]` an absolute path). The core runs it detached as a `play` job with its output in a log. Raise `SourceError` when no single command can be determined. If both are declared, `launch_url` wins.
- `game_folder(config, store_id) -> Path`: the folder a game lives in. With it, users can attach launch settings (`ludex game set`: executable, arguments, environment, a Proton runner) and the core runs the configured executable itself, through `umu-run` when a runner is set. It counts as the `launch` capability.
- `install_url(store_id) -> str`: the URL that makes the store's client offer to install a game the account owns (`steam://install/<id>`).
- `install_command(config, store_id) -> Sequence[str]`: an argument list that installs with the store's own tool (for example Legendary), run as an `install` job. `install_url` wins when both are present.

ludex ships no downloader: these drive the owner's official client or tool.

## Search: `search(query) -> Sequence[SearchHit]`

Searches the store's catalog (any game, owned or not): `SearchHit(store, store_id, title, url, price=None)`. This and `fetch` are the hooks that may use the network. A hit whose link is not `https` is skipped and reported (unless the provider has `acquire`; then the hit is kept and its link not used). The core adds the "owned" marker and merges results across providers; a failing provider is reported and skipped.

## Metadata, match and cover

- `metadata(store_id) -> Metadata | None`: `Metadata(description, genres, developers, released)` for one game, or `None` if the store does not know it. Called only when the user asks (`ludex metadata`, the GUI) and cached. Several providers may offer it; the first that owns a copy wins.
- `match(title) -> Sequence[SearchHit]`: catalog games with a similar title, best first, for games whose own store supplies no details (a folder of local games). The core accepts only a hit whose title equals the cleaned folder name, then asks the same provider for `metadata`, and only when `auto_match` is on, since it sends the title to that service. Offer `metadata` too. If the service has terms that require attribution, the hit's `url` is what the GUI links.
- `cover(store_id) -> bytes | None`: the bytes of the cover image (PNG, JPEG or WebP, at most 4 MiB), or `None`. You do the request; the core validates the size and file signature, never decodes the image, and caches the file. A graphical frontend asks only for games on screen, and only after the user allowed contacting the stores (`auto_details`). Needs `ludex-core>=0.62.0`.
- `cover_by_title(title) -> bytes | None`: the same kind of bytes for a game that no store has a cover for (a Heroic or local game), found by its cleaned title. It is asked only after the game's own copies had none, and only when the user has filled in all your required `settings` (an API key, say): configuring the plugin is the consent to send titles to its service, so say so in its `help`. Return a cover only when the service's game name equals `title` (case and punctuation aside), never a merely similar one: wrong art is worse than none. It receives `settings` like `cover` does, and the core keeps the answer per title and remembers a miss for a week, per plugin. Needs `ludex-core>=0.66.0`.

## Play time and running

- `playtime(config) -> Mapping[str, PlayRecord]`: `PlayRecord(minutes, last_played)` per store id (ISO 8601 UTC string or `None`) from what the store's own client recorded on this machine. Read live, no network. A provider that declares it is trusted, so the core does not add the sessions it timed itself.
- `running(config) -> Iterable[str]`: store ids of games the store's client has running now (for example by looking at processes). Read about every two seconds while a launcher is open: keep it cheap, local and free of network. Games the core started itself are `play` jobs and do not need it.

## Actions: `actions(store, store_id) -> Sequence[GameAction]`

Extra actions for one owned copy of a game, whichever plugin owns the copy: a split-screen launcher can offer one for Steam and Heroic games.

```python
def actions(store, store_id):
    if store not in ("steam", "heroic"):
        return []
    return [GameAction("split", "Play split-screen", ["/usr/bin/couchplay", "--game", store_id])]
```

`GameAction(id, label, argv)`: `id` is lowercase `[a-z][a-z0-9-]*`, unique within the plugin; `label` is one line; `argv` is an absolute executable and its arguments, run without a shell. The GUI lists them under "More" next to Play; `ludex action GAME [PLUGIN:ID]` lists and runs them as background `action` jobs with output in the job log, and the game's credentials are never added. It runs when a game is shown, so keep it cheap, local and free of network. Return an empty sequence when nothing applies; an invalid action, or a call that raises, is skipped. Declare a `settings` parameter to receive the plugin's settings.

Declare a `context` parameter to learn where the game is. It receives a `GameContext` with `title`, `folder` (where the game is installed), `prefix` (the Wine prefix it runs in), and the user's launch options `executable`, `args`, `env` and `runner`. The folder and prefix come from the store's own plugin: Steam, Epic and Heroic read them from the store's files, and any plugin can provide them with `game_location(config, store_id) -> GameLocation(folder, prefix)` (either may be `None`; raise `SourceError` when unknown). A prefix the user set wins, then the store's own, then, when a Proton runner is set, the one ludex creates. `folder`, `prefix` and `executable` are `None` when unknown (`args` and `env` are empty, `env` read-only); a recorded folder may not exist on disk, so check before using it. Name the parameter explicitly, keyword-capable and after `store` and `store_id`. `game_location` is not a capability by itself.

## Acquire: `acquire(request, report) -> AcquireResult`

Does a whole download itself: fetch, unpack or drive an official client. `request` has `store_id`, `title` and a `destination` directory the core created.

```python
def acquire(request, report):
    report("downloading", done=1, total=2)        # progress lines; numbers are optional
    game = request.destination / "game"
    game.mkdir()
    ...
    return AcquireResult(game, {"executable": "run.sh"})
```

`report(message, done=None, total=None)`: with both numbers the core shows a percentage and a time estimate, otherwise only the message. The returned `directory` MUST lie inside `destination` (the core checks). `hints` are strings, for example the executable. Users run it with `ludex download STORE ID`, which runs as a background job. The core takes no position on where a plugin gets files; the author is responsible for what it fetches and for the rights to it.

## Commands and views

See [Commands and views](commands-and-views.md).
