# Quick start: a plugin in two files

This plugin reads a JSON file of games, so you can see the whole path from code to `ludex ls` without any store account.

## The code

Create a folder `ludex-hello` with two files.

`ludex_hello.py`:

```python
import json
from pathlib import Path

from ludex.plugins import ConfigField, FetchResult, OwnedGame, Provider, SourceError


def fetch(config):
    path = Path(config["file"]).expanduser()
    try:
        entries = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SourceError("hello_unreadable", "cannot read the games file") from None
    games = [OwnedGame("hello", str(e["id"]), e["title"]) for e in entries]
    return FetchResult(games, complete=True, mode="file")


PLUGIN = Provider(
    "hello",
    "Games listed in a JSON file",
    (ConfigField("file", "JSON file: a list of {id, title}", path=True),),
    fetch,
)
```

`pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"

[project]
name = "ludex-hello"
version = "0.1.0"
description = "A tiny ludex plugin: games listed in a JSON file"
requires-python = ">=3.11"

[project.entry-points."ludex.providers"]
hello = "ludex_hello:PLUGIN"

[tool.setuptools]
py-modules = ["ludex_hello"]
```

What matters:

- The entry-point name (`hello`) is the provider's name in the loader. Keep it equal to the first argument of `Provider` and to the `store` of every game it returns. Names start with a lowercase letter, then lowercase letters, digits and `-`, up to 32 characters.
- `Provider(name, help, config_fields, fetch)`: `config_fields` are what the user is asked for when adding an account. `path=True` makes interactive prompts offer tab completion.
- `fetch(config)` receives the account's field values as strings and returns a `FetchResult`. `complete=True` says the list is every game the account owns; only then may the core mark games missing from it as removed. `mode` is a short label shown after an import.
- Errors the user should see are `SourceError(code, message)` with a fixed message. Never put keys, tokens or URLs with query strings in it.

## Install and try it

```sh
echo '[{"id": 1, "title": "Hades"}, {"id": 2, "title": "Celeste"}]' > games.json

ludex plugin add ./ludex-hello          # runs with your permissions
ludex providers                         # hello  [owned]  Games listed in a JSON file
ludex account add hello mine --set file=$PWD/games.json
ludex import mine                       # hello:mine: 2 added, 0 restored, 0 removed, 2 total [file]
ludex ls
```

Use a scratch state directory while you develop: `export LUDEX_HOME=$(mktemp -d)`.

Edit the code and run `ludex plugin add ./ludex-hello` again; it replaces the installed copy. `ludex plugin rm ludex-hello` removes it; its accounts and games stay until `ludex account rm`.

## Next

- Make the plugin do more: [capabilities](capabilities.md) (launch, install, search, metadata, covers, actions, downloads).
- Add commands and GUI pages: [commands and views](commands-and-views.md).
- Test it offline and publish it: [packaging and testing](packaging.md).
