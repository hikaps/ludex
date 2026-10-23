# ludex

[![Tests](https://github.com/hikaps/ludex/actions/workflows/tests.yml/badge.svg?branch=develop)](https://github.com/hikaps/ludex/actions/workflows/tests.yml)
[![Rolling packages](https://github.com/hikaps/ludex/actions/workflows/releases.yml/badge.svg?branch=main)](https://github.com/hikaps/ludex/actions/workflows/releases.yml)

A headless, scriptable library of the games you own across stores. It stores what you own and never provides content; stores, metadata and sync are plugins.

Status: early development. Contributor rules live in [AGENTS.md](AGENTS.md).

## Install

`main` publishes the rolling **stable** build and `develop` the rolling **beta** build.

```sh
uv tool install https://github.com/hikaps/ludex/releases/download/stable/ludex.tar.gz
# Or: pipx install https://github.com/hikaps/ludex/releases/download/stable/ludex.tar.gz
```

Replace `stable` with `beta` for the beta channel.

## License

GPL-3.0-or-later.

