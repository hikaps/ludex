# Changelog

All notable changes to ludex are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a single merged pull request.

## [Unreleased]

## [0.56.0] - 2026-11-15

### Added

- **plugins:** `acquire`'s `report(message, done=None, total=None)` takes optional numbers (any one unit). With both, a download shows a percentage and a time estimate in the Jobs tab (bar in the detail card), in `ludex download --status` and in `--json` (`progress_detail`); without them only the message shows, as before. Old plugins need no change (`API_VERSION` stays 3)

## [0.55.0] - 2026-11-15

### Added

- **jobs:** `ludex download STORE ID [--to DIR]` runs a plugin's `acquire` in the background as a `download` job (survives closing the TUI); `--status` shows its latest progress line and `--stop STORE ID` cancels it
- **tui:** a Jobs tab lists installs, downloads and games ludex started (running first, with a running count on the tab); `x` stops the selected one. `i` on a Search hit now starts a download job instead of a session-bound worker

## [0.54.0] - 2026-11-10

### Added

- **tui:** `i` on a Search hit of a plugin that downloads games asks for a folder and downloads there, instead of asking the desktop to open the hit's link (which failed with "the system could not open ... client")
- **config:** `download_dir` setting (default `~/Games`); `ludex acquire` uses it when `--to` is omitted

### Fixed

- **update:** `ludex update` on a uv tool install failed with "Executable already exists"; it now passes `--force`

## [0.53.0] - 2026-11-09

### Added

- **playtime:** Play time and last played for each game, from Steam's and Heroic's own records and from the games ludex started itself: `ludex show`, `ludex ls --sort played|recent`, the TUI Detail pane and `o`. New optional plugin capability `playtime`

## [0.52.0] - 2026-11-09

### Added

- **jobs:** Games ludex starts itself run as tracked jobs: `launch --status` and `--stop`, `x` stops one in the TUI, and a failed start is reported with its log (a game's output was discarded before)

### Changed

- **jobs:** A job's end time is when its process ended, not when ludex next looked. `launch_game` returns `(target, job)`

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
