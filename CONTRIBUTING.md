# Contributing

Setup, code conventions and testing are in [AGENTS.md](AGENTS.md).

## Branches

- `main`: stable. Every push publishes the rolling `stable` GitHub Release.
- `develop`: integration. Every push publishes the rolling `beta` prerelease.
- One feature or fix per branch, created from `develop` and named after the change (for example `steam-import`). Open the PR with `gh pr create --base develop`; the default branch is `main`, so `--base` is required.
- Feature PRs are squash-merged into `develop`; the PR title becomes the commit subject and must follow the commit conventions below.
- Both branches are protected: changes land only through PRs, and `Tests (Python 3.11)` and `Tests (Python 3.14)` must pass. Never force-push them.

## Commits and PRs

- Conventional Commits: `<type>(<optional-scope>): <summary>`; types `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. Scopes name the subsystem (`import`, `matching`, `storage`, `plugins`, `accounts`, `steam`, `cli`, `tui`).
- Imperative subject, no trailing period, at most 72 characters including the `(#N)` that squash merges append, so keep PR titles to 68 or fewer.
- One logical change per commit, with its tests and docs. Body: motivation, constraints, and verification actually performed.
- Breaking CLI, `--json` or persisted-state changes: `!` after the type/scope and a `BREAKING CHANGE:` body.
- PR descriptions follow `.github/pull_request_template.md` (What, Why, Verification) and state what was not verified. Keep PR communication in the description; do not post progress comments.

## Releases

1. In a feature PR on `develop`, bump `version` in `pyproject.toml` and `__version__` in `src/ludex/__init__.py` together. Both must be plain `X.Y.Z` and equal.
2. Open a PR from `develop` to `main` and merge it with a merge commit (never squash, or the branches diverge).
3. That merge releases the version: `.github/workflows/pypi.yml` publishes to PyPI (trusted publishing, no token), then creates tag `vX.Y.Z` and a GitHub Release with the sdist and wheel. A push to `main` whose tag already exists only builds.

A PyPI version can never be reused, so keep a required reviewer on the `pypi` environment (GitHub Settings, Environments): the release waits for approval. Re-running after a failed tag or release step is safe. Pushing tag `vX.Y.Z` by hand also publishes it.

The PyPI project is `ludex-games`; the command and import package stay `ludex`. One-time setup: a PyPI pending publisher for project `ludex-games`, owner `hikaps`, repository `ludex`, workflow `pypi.yml`, environment `pypi`.

CI: `tests.yml` runs on every push and PR. `releases.yml` builds the sdist and wheel, smoke-installs them with uv, pipx and pip, then moves the rolling `beta` or `stable` tag and release.
