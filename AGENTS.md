# Repository Guidelines

## Project Overview

`ludex` is a headless, scriptable library of the games a user owns across stores, with a stable plugin API. Linux, Python 3.11+, SQLite. The core never provides or endorses content; store, metadata and sync access are plugins.

The plugin API contract and the removal policy are specified in the docstrings of `ludex.plugins` and `ludex.library` (`packages/core/src/ludex/`); they are the source of truth. Requirements and plans are not tracked in this repository.

## Constraints

- Network only inside plugins: bounded responses, TLS verified, redacted URLs in output.
- Local-only and private by default: no telemetry, no hosted component.

## Development Commands

Run from the repository root:

```sh
uv sync --locked --all-packages --extra test
.venv/bin/python -m pytest --basetemp=/tmp/ludex-pytest -q
.venv/bin/ludex --version
```

The repository is a uv workspace of three distributions with lockstep versions: `ludex-core` (`packages/core`, import `ludex`: library, plugin API, bundled providers), `ludex-cli` (`packages/cli`, `ludex_cli`) and `ludex-gui` (`packages/gui`, `ludex_gui`, Qt Quick/QML launcher); the root `ludex-games` bundles core and cli (not the GUI) and keeps the `ludex` command. `.github/scripts/build_distributions.py` and `smoke_distributions.py` build and install-test them; after changing a dependency or version run `uv lock`. GUI tests run offscreen (`QT_QPA_PLATFORM=offscreen`, `QT_QUICK_BACKEND=software`).

`LUDEX_HOME` points ludex at a scratch state directory for manual runs.

`--basetemp` deletes that scratch directory; do not share it across concurrent runs. No lint, formatter, type-check or coverage tool is configured; do not invent one.

## Code Conventions

- Four-space indentation, type hints, `from __future__ import annotations`, `snake_case` functions/modules, `PascalCase` classes, `_private_helpers`. Value records use frozen/slotted dataclasses.
- All behavior lives in the core library; `ludex_cli` and `ludex_gui` only parse input, call the core, and format output.
- Pass paths, connections and HTTP clients explicitly; avoid global service state.
- Boundary errors expose stable `.code`/`.message`.
- Parameterized SQL only; keep schema-version checks and WAL.
- Never print or log credentials; redact URLs in output.

## Testing

- Pytest with `tmp_path`, `monkeypatch`, `capsys`; mock store APIs (for example `httpx.MockTransport`). Tests are offline and need no credentials.
- Add behavioral regressions for changed paths: idempotent re-import, removal and restore, partial-fetch safety, credential redaction, and broken-plugin skipping.
- Exercise the real CLI (`ludex ...`) for user-visible changes; mocked APIs do not prove live store compatibility.

## Workflow

Branching, commit conventions, PRs and releases are in [CONTRIBUTING.md](CONTRIBUTING.md). A change to a command or convention updates README.md or this file in the same PR.

**Never merge a pull request (feature or release) without the maintainer's explicit approval for that PR**, even when CI is green and an earlier PR was approved. Open the PR, wait for CI, report the result and stop; merge only after the maintainer says so. This applies to agents and automation alike.
