# Repository Guidelines

## Project Overview

`ludex` is a headless, scriptable library of the games a user owns across stores, with a stable plugin API ("beets for games"). Linux, Python 3.11+, SQLite. The core never provides or endorses content; store, metadata and sync access are plugins.

The plugin API contract and the removal policy are specified in the docstrings of `ludex.plugins` and `ludex.library`; they are the source of truth. Requirements and plans are not tracked in this repository.

## Constraints

- Network only inside plugins: bounded responses, TLS verified, redacted URLs in output.
- Local-only and private by default: no telemetry, no hosted component.

## Development Commands

Run from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[test]"
python -m pytest --basetemp=/tmp/ludex-pytest -q
ludex --version
```

`LUDEX_HOME` points ludex at a scratch state directory for manual runs.

`--basetemp` deletes that scratch directory; do not share it across concurrent runs. No lint, formatter, type-check or coverage tool is configured; do not invent one.

## Code Conventions

- Four-space indentation, type hints, `from __future__ import annotations`, `snake_case` functions/modules, `PascalCase` classes, `_private_helpers`. Value records use frozen/slotted dataclasses.
- All behavior lives in the core library; `cli.py` (and later the TUI) only parse input, call the core, and format output.
- Pass paths, connections and HTTP clients explicitly; avoid global service state.
- Boundary errors expose stable `.code`/`.message`.
- Parameterized SQL only; keep schema-version checks and WAL.
- Never print or log credentials; redact URLs in output.

## Branching, PRs and Releases

- `main`: stable. Every push publishes the rolling `stable` GitHub Release (`X.Y.Z.postN`).
- `develop`: integration. Every push publishes the rolling `beta` prerelease (`X.Y.Z.devN`).
- One feature or fix per branch, created from `develop`, named after the change (for example `steam-import`, `ls-filters`). Open the PR with `gh pr create --base develop`; the repo default branch is `main`, so `--base` is required.
- Feature PRs are squash-merged into `develop`; the PR title becomes the commit subject and must follow the commit conventions below.
- Releases: open a PR from `develop` to `main` and merge it with a merge commit (never squash, or the branches diverge). Bump `version` in `pyproject.toml` and `__version__` in `src/ludex/__init__.py` together, in a feature PR on `develop`, before a release that changes behavior; both must be plain `X.Y.Z` and equal or the release build fails.
- Both branches are protected: changes land only through PRs, and `Tests (Python 3.11)` and `Tests (Python 3.14)` must pass. Never force-push `main` or `develop`.
- CI: `.github/workflows/tests.yml` runs on every push, PR and manual dispatch. `.github/workflows/releases.yml` builds the sdist and wheel, smoke-installs them with uv, pipx and pip, and then moves the `beta` or `stable` tag and release.

## Commit Conventions

- Conventional Commits: `<type>(<optional-scope>): <summary>`; types `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. Scopes name the subsystem (`import`, `matching`, `storage`, `plugins`, `accounts`, `steam`, `cli`, `tui`).
- Imperative subject, no trailing period, at most 72 characters including the `(#N)` that squash merges append, so keep PR titles to 68 or fewer.
- One logical change per commit, with its tests and docs. A change to a command or convention updates this file or the README in the same PR. Body: motivation, constraints, and verification actually performed.
- Breaking CLI, `--json` or persisted-state changes: `!` after the type/scope and a `BREAKING CHANGE:` body.
- PR descriptions follow `.github/pull_request_template.md` (What, Why, Verification) and state what was not verified. Keep PR communication in the description and update it when scope or verification changes; do not post progress comments.

## Testing

- Pytest with `tmp_path`, `monkeypatch`, `capsys`; mock store APIs (for example `httpx.MockTransport`). Tests are offline and need no credentials.
- Add behavioral regressions for changed paths: idempotent re-import, removal and restore, partial-fetch safety, credential redaction, and broken-plugin skipping.
- Exercise the real CLI (`ludex ...`) for user-visible changes; mocked APIs do not prove live store compatibility.
