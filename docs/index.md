# ludex: every game you own, in one local library

ludex is a headless, scriptable catalog of the games you own on Steam, Epic/Heroic and in local folders, for Linux. It stores everything in a local SQLite database, has a plugin API for stores and metadata, sends no telemetry and has no hosted component. The core never provides or endorses content; store access lives in plugins.

Use it from the command line or the desktop launcher (`ludex gui`, installed separately), which a game controller can drive and which has a fullscreen console mode for a TV or handheld.

Requires Python 3.11 or newer.

## Install

Install from PyPI with [uv](https://docs.astral.sh/uv/) or [pipx](https://pipx.pypa.io/). The package is `ludex-games`; the command is `ludex`:

```sh
uv tool install ludex-games
# or
pipx install ludex-games
```

Check it works:

```sh
ludex --version
```

Run `ludex update` for a uv tool or pipx install. It uses the installer's recorded requirements, so GUI extras, add-ons, and version pins stay in place. Beta updates refresh the rolling release archives. Use `ludex update --dry-run` to see the installer command.

`ludex update --channel stable|beta` can switch a uv tool install between PyPI and the rolling release when its recorded requirements can be carried over. Two errors change nothing: `install_spec_unknown` means ludex found no uv or pipx install record (a plain-pip install: upgrade it with pip, using your original requirements and extras), and `channel_switch_unsupported` means the switch cannot be replayed (pipx can update in place but not switch, and uv installs with custom constraints or other options must be reinstalled). To switch by hand, reinstall with the target Ludex sources and keep your extras, add-ons, and options. For a beta GUI install with controller support:

```sh
base=https://github.com/hikaps/ludex/releases/download/beta
uv tool install "$base/ludex.tar.gz" --with "ludex-gui[gamepad] @ $base/ludex-gui.tar.gz"
```

## First steps

```sh
ludex providers      # list available sources and what each can do
ludex setup          # guided: add an account for a source and import it
ludex ls             # list your games
```

## Guides

- [Library and command line](guide/library.md): accounts, importing, searching, scripting, settings
- [Launching, installing and jobs](guide/launching.md)
- [Details, matching and covers](guide/metadata.md)
- [Launcher (GUI)](guide/launcher.md): controller and console mode

## Plugin SDK

Stores, metadata services and extra commands are plugins, and you can write one: start with the [Plugin SDK](plugins/index.md) and its [quick start](plugins/quickstart.md).

## Use cases

- [List the games you own across stores on Linux](use-cases/list-games-across-stores.md)
- [Import your Steam library](use-cases/import-steam-library.md)

Source code and issues: <https://github.com/hikaps/ludex>.
