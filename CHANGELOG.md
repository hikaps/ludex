# Changelog

All notable changes to ludex are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a single merged pull request.

## [Unreleased]

## [0.51.0] - 2026-10-28

### Added

- **jobs:** Track, report on and stop installs ([#60](https://github.com/hikaps/ludex/pull/60))

### Changed

- **packaging:** The package is published as `ludex-games` because PyPI rejects `ludex` as too close to an existing project. The `ludex` command and the `ludex` import package are unchanged. Installs made before this change use the old package name, and `ludex update` on them cannot migrate: uninstall once (`uv tool uninstall ludex` or `pipx uninstall ludex`) and install again from the release URL.

## [0.50.0] - 2026-10-28

### Added

- **epic:** Install a game through Legendary ([#59](https://github.com/hikaps/ludex/pull/59))

## [0.49.0] - 2026-10-28

### Added

- **tui:** Fuzzy filter ([#58](https://github.com/hikaps/ludex/pull/58))

## [0.48.1] - 2026-10-28

### Fixed

- **local:** Refuse relative and over-broad paths ([#57](https://github.com/hikaps/ludex/pull/57))

## [0.48.0] - 2026-10-27

### Added

- **metadata:** Choose a game's match by hand ([#56](https://github.com/hikaps/ludex/pull/56))

## [0.47.0] - 2026-10-27

### Added

- **local:** Exclude folders from a local account ([#55](https://github.com/hikaps/ludex/pull/55))

Older releases: see the [merged pull requests](https://github.com/hikaps/ludex/pulls?q=is%3Apr+is%3Amerged) and `git log`.
