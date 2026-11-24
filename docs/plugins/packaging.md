# Packaging and testing

## Package layout

A plugin is an ordinary Python package. All ludex needs is the entry point:

```toml
[project.entry-points."ludex.providers"]
demo = "ludex_demo:PLUGIN"
```

- One plugin package registers one provider. `ludex plugin add` refuses a package with no `ludex.providers` entry point and one that registers several.
- The entry-point name is the provider name: it starts with a lowercase letter, then lowercase letters, digits and `-`, up to 32 characters. Keep it equal to `Provider.name`. It cannot clash with a provider another package already provides (a name registered twice is rejected).
- The entry point must point at a `Provider` instance (not a subclass or a factory), declare at least one capability, and use `api_version` equal to the core's; otherwise `ludex providers` reports why it was skipped. Plugin-wide `settings` names must be unique and must not repeat an account field.
- Package (distribution) names: `ludex`, `ludex-games`, `ludex-core`, `ludex-cli` and `ludex-tui` are reserved for ludex itself and cannot be used. Pick a distinct name such as `ludex-yourstore`.
- Do not declare `ludex` as a dependency. If you need to state a minimum, depend on `ludex-core>=X.Y.Z` (for example `>=0.62.0` for `cover`, `>=0.61.0` for views). A requirement the index cannot satisfy still blocks the install.
- A plugin may depend on any other library; each managed plugin gets its own folder with its own dependencies.

## Installing and managing

```sh
ludex plugin add PACKAGE_OR_URL_OR_PATH   # a PyPI name, name==1.2, a wheel, a path, or a GitHub/GitLab repository link
ludex plugin ls
ludex plugin update [NAME]                # reinstalls from the spec it was added with
ludex plugin disable NAME                 # keep it installed but do not load it
ludex plugin enable NAME
ludex plugin rm NAME                      # accounts and games it imported stay until `ludex account rm`
ludex providers                           # did it load, and what can it do
```

- Managed plugins live in `<state>/plugins/<name>/`, one self-contained folder each, added to the end of `sys.path`, so they survive ludex upgrades and can never shadow ludex's own libraries.
- A plugin runs with the user's permissions: only install code you trust. Specs must not contain credentials.
- Installing is done by `uv`, else `pip`, only when the user runs `plugin add`, `plugin update` or `update`. ludex opens no connection itself.
- You can also install a plugin with any Python installer into the same environment as ludex; managed install is the supported path.

## Testing offline

Tests need no store, no credentials and no network. Build a `Provider` and exercise it directly, and mock HTTP with `httpx.MockTransport` (or whatever your client supports):

```python
import httpx

from ludex_demo import make_provider


def test_fetch_is_complete_and_never_leaks_the_token():
    def handler(request):
        return httpx.Response(200, json=[{"id": 1, "title": "Hades"}])

    provider = make_provider(client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.fetch({"token": "s3cret"})
    assert result.complete and [g.title for g in result.games] == ["Hades"]
```

To exercise the core path, import into a temporary library: connect with `ludex.storage.connect(tmp_path / "library.sqlite3")` and call `ludex.library.import_account` or `run_import`. Cases worth a test:

- a failed or partial fetch returns `complete=False` or raises `SourceError`, and removes nothing;
- an error message contains no key, token or URL with a query string;
- an idempotent re-import adds nothing twice, and a removed game restores when it returns;
- `ludex.loader.load_providers()` loads it (it reports problems rather than raising).

For a manual run against the real CLI, use a scratch state directory: `LUDEX_HOME=$(mktemp -d) ludex plugin add ./my-plugin`.

## Rules every plugin follows

- **Network** only in the hooks that allow it (`fetch`, `search`, `metadata`, `match`, `cover`, `acquire`), with bounded responses, verified TLS and `https` links.
- **Secrets**: never log or print credentials; `SourceError` and `LudexError` messages are fixed strings without keys, tokens or URLs with query strings. Mark credentials `secret=True` so they are prompted for and never shown.
- **No processes from hooks** that return URLs or argument lists: the core runs them. No shell anywhere; `argv[0]` is an absolute path.
- **Local and cheap** hooks (`installed`, `playtime`, `running`, `actions`) are called often: no network, no long blocking.
- **Content**: ludex takes no position on where a plugin gets files; you are responsible for what yours fetches and your rights to it.

## Publishing

Publish like any Python package (PyPI or a repository link). In the README tell users to run `ludex plugin add <name>`, which pins nothing for them: ask for a version (`name==1.2`) in the instructions if you want one. A user updates it with `ludex plugin update`.
