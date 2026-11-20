# Write a ludex plugin

To add a store, a metadata service or new commands to ludex, write a plugin: a Python package that exports a `Provider` instance from the `ludex.providers` entry-point group. The contract is in the docstrings of [`packages/core/src/ludex/plugins.py`](https://github.com/hikaps/ludex/blob/main/packages/core/src/ludex/plugins.py) and [`packages/core/src/ludex/library.py`](https://github.com/hikaps/ludex/blob/main/packages/core/src/ludex/library.py); they are the source of truth.

## Summary of the contract

- A `Provider` declares capabilities by filling fields; at least one is required and the core calls only what is declared: `owned` (`fetch`), `launch`, `install`, `installed`, `search`, `metadata`, `acquire`, `commands`, `views`, `cover`.
- Do not declare ludex as a dependency. A provider whose `api_version` differs from the core's is skipped with a reported reason.
- `fetch(config)` returns a `FetchResult`. `complete` must be True only when the result is every game the account owns; only then are missing games marked removed. If the result may be partial, return `complete=False`, or raise `SourceError` when you cannot tell. Games carry the plugin's own name as `store`.
- Plugin-wide `settings` and per-account `config_fields` are `ConfigField`s (kinds `text`, `yes_no`, `choice`; `secret` and `path` for text).
- Network access belongs only in plugins: bounded responses, verified TLS, `https` links, and fixed, secret-free `SourceError` messages.
- `views` add navigation entries (a TUI tab, a drawer entry in `ludex gui`, `ludex plugin view`): a `View(id, title, fetch)` whose `fetch(settings)` returns a `ViewTable` or `ViewDetail` of plain strings. A table row may offer `ViewAction(label, command, args)` that runs one of your `commands` after the user confirms; fetching never runs one. Needs `ludex-core>=0.61.0`, and `API_VERSION` stays 3.
- `cover(store_id)` returns the bytes of a game's cover image (PNG, JPEG or WebP, at most 4 MiB) or `None`; the plugin does the request, the core validates and caches the file and a graphical frontend shows it. Like `search`, it may take a `settings` parameter. Needs `ludex-core>=0.62.0`, and `API_VERSION` stays 3.
- Imports are one transaction; removal and restore behavior is specified in `ludex.library`.

## Install and manage

```sh
ludex plugin add PACKAGE_OR_URL_OR_PATH   # runs with your permissions
ludex plugin ls
ludex plugin update [NAME]
ludex plugin rm NAME
ludex providers                           # check it loaded and its capabilities
```

Bundled sources (`steam`, `epic`, `heroic`, `local`, `shortcuts`, `rawg`) are small, real examples under [`packages/core/src/ludex/sources/`](https://github.com/hikaps/ludex/tree/main/src/ludex/sources).
