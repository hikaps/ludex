# Write a ludex plugin

To add a store, a metadata service or new commands to ludex, write a plugin: a Python package that exports a `Provider` instance from the `ludex.providers` entry-point group. The contract is in the docstrings of [`src/ludex/plugins.py`](https://github.com/hikaps/ludex/blob/main/src/ludex/plugins.py) and [`src/ludex/library.py`](https://github.com/hikaps/ludex/blob/main/src/ludex/library.py); they are the source of truth.

## Summary of the contract

- A `Provider` declares capabilities by filling fields; at least one is required and the core calls only what is declared: `owned` (`fetch`), `launch`, `install`, `installed`, `search`, `metadata`, `acquire`, `commands`.
- Do not declare ludex as a dependency. A provider whose `api_version` differs from the core's is skipped with a reported reason.
- `fetch(config)` returns a `FetchResult`. `complete` must be True only when the result is every game the account owns; only then are missing games marked removed. If the result may be partial, return `complete=False`, or raise `SourceError` when you cannot tell. Games carry the plugin's own name as `store`.
- Plugin-wide `settings` and per-account `config_fields` are `ConfigField`s (kinds `text`, `yes_no`, `choice`; `secret` and `path` for text).
- Network access belongs only in plugins: bounded responses, verified TLS, `https` links, and fixed, secret-free `SourceError` messages.
- Imports are one transaction; removal and restore behavior is specified in `ludex.library`.

## Install and manage

```sh
ludex plugin add PACKAGE_OR_URL_OR_PATH   # runs with your permissions
ludex plugin ls
ludex plugin update [NAME]
ludex plugin rm NAME
ludex providers                           # check it loaded and its capabilities
```

Bundled sources (`steam`, `epic`, `heroic`, `local`, `shortcuts`, `rawg`) are small, real examples under [`src/ludex/sources/`](https://github.com/hikaps/ludex/tree/main/src/ludex/sources).
