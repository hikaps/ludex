# Changelog

All notable changes to ludex are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a single merged pull request.

## [Unreleased]

## [0.62.0] - 2026-11-20

Also includes 0.61.0 below, which was never published to PyPI.

### Added

- **gui:** `ludex-gui` is a new distribution with a Qt desktop window (`ludex gui`, or the `ludex-gui` command on its own). A drawer lists Owned, Installed, Search, Jobs and Settings, then one entry per plugin view; it launches and installs games, searches and downloads, shows job progress, and edits the same settings as the TUI. A plugin view's row actions run only after a separate confirmation. It uses only the core API (`ludex.plugin_views` for plugin entries) and is not part of `ludex-games`, because it brings Qt (PySide6): install it next to `ludex-games`. Without it `ludex gui` reports `gui_missing`

### Changed

- **packaging:** the workspace has a fifth member, `ludex-gui`, versioned in lockstep and published last by `pypi.yml` from the new `pypi-gui` environment, so a missing PyPI publisher cannot hold back the tag or the other projects. Beta builds and the `ludex-games` bundle do not include it

## [0.61.0] - 2026-11-19

### Added

- **plugins:** a provider can contribute `views`: a table or a detail panel with optional confirmed row actions that run its own commands (`View`, `ViewTable`, `ViewRow`, `ViewAction`, `ViewDetail` in `ludex.plugins`). The TUI shows each as a tab, fetched on first visit and again with `r`; an action opens a chooser and runs only after you press Run. `ludex plugin view [PROVIDER [VIEW]]` lists views or prints one (`--json` too). `ludex.plugin_views` (`list_views`, `get_view`, `fetch_view`, `run_view_action`) is the frontend-neutral API a future GUI drawer would use. `API_VERSION` stays 3; a plugin that declares views needs `ludex-core>=0.61.0`

## [0.60.0] - 2026-11-19

Also includes 0.55.0 to 0.59.1 below, which were never published to PyPI.

### Added

- **jobs:** `ludex download STORE ID [--to DIR]` runs a plugin's `acquire` in the background as a `download` job (survives closing the TUI); `--status` shows its latest progress line and `--stop STORE ID` cancels it. The TUI has a Jobs tab listing installs, downloads and games ludex started (`x` stops one); `i` on a Search hit starts a download job
- **plugins:** `acquire`'s `report(message, done=None, total=None)` takes optional numbers; with both, a download shows a percentage and time estimate in the Jobs tab, `ludex download --status` and `--json` (`progress_detail`). Old plugins need no change (`API_VERSION` stays 3)
- **plugins:** `ludex.services` (`start_service`, `stop_service`, `service_status`): a plugin command can run a long-running background process as a game-less `service` job with a private log and a process-group stop
- **tui:** the game settings form (`e`) lists executables found in the game folder, best guess first; `ludex game exes GAME` prints the same candidates

### Changed

- **packaging:** one repository now publishes four lockstep distributions: `ludex-core` (import `ludex`: library, plugin API, bundled providers), `ludex-cli`, `ludex-tui` and `ludex-games`, which bundles all three, installs the same `ludex` command and keeps the rolling beta URL. Plugins keep importing `ludex`; `API_VERSION` and the database are unchanged. Nothing changes for `uv tool install ludex-games` users. `python -m ludex` is now `python -m ludex_cli`; `ludex.cli`, `ludex.tui` and `ludex.tui_settings` are now `ludex_cli.cli`, `ludex_tui.app` and `ludex_tui.settings`. `ludex-cli` alone reports `tui_missing` for `ludex tui`; `ludex-tui` alone provides a `ludex-tui` command
- **downloads:** a background download runs a private core worker instead of `ludex acquire`, so it works without the CLI installed
- **plugins:** a plugin may require `ludex-core`; the copy it installs into its own folder is ignored in favor of the running one, so built-in providers do not register twice
- **update:** `ludex update` on a standalone `ludex-cli` says it needs `ludex-games`
- **tui:** the library refreshes itself: every account is imported in the background when the TUI starts and whenever you press `r`. A toast reports new, restored and removed games and names an account that failed. Turn the startup import off in Settings or with `ludex config auto_refresh no`

### Fixed

- **jobs:** a job being stopped could be recorded as `lost` instead of `stopped` when another reader (the TUI's job poll) noticed the process had ended at the same moment
- **find:** a search hit without an `https://` link was dropped even from a plugin that downloads through `acquire`; now only hits ludex would open need https, and skipped hits are reported
- **services:** an older running service is found even after 1000 newer runs; `stop_service` returns `False` when the service ends just before it is stopped; provider names no longer allow `_`; a service that exits at startup is reported as soon as it ends

## [0.59.1] - 2026-11-17

### Fixed

- **services:** an older running service is found even after 1000 newer service runs (the lookup used to filter after a limit); `stop_service` returns `False` when the service ends just before it is stopped, instead of raising; provider names no longer allow `_`, so two services can never share a log file; a service that exits at startup is reported as soon as it ends rather than after the full wait. The one-at-a-time check is documented as needing the writer lock (plugin commands hold it)

## [0.59.0] - 2026-11-17

### Added

- **plugins:** `ludex.services` (`start_service`, `stop_service`, `service_status`): a plugin command can run a long-running background process as a game-less `service` job, with a private log, liveness by pid and start time, and a process-group stop. It shows in the TUI Jobs tab. No daemon and no schema change; `API_VERSION` is unchanged

## [0.58.1] - 2026-11-15

### Fixed

- **find:** a search hit without an `https://` link was dropped silently, even from a plugin that downloads through `acquire` and never opens the link. Now only hits ludex would open need https; an `acquire` plugin's hits are kept (the link is not shown or used). Skipped hits are reported ("N results skipped (link is not https)")

## [0.58.0] - 2026-11-15

### Changed

- **tui:** the library refreshes itself: every account is imported (in the background) when the TUI starts and whenever you press `r`, which used to re-read only local state. A toast reports new, restored and removed games and names an account that failed; the same safe removal rules apply as for `ludex import`. Turn the startup import off in Settings or with `ludex config auto_refresh no` (for example when offline); `r` still works

## [0.57.0] - 2026-11-15

### Added

- **tui:** the game settings form (`e`) has a "Pick one found in the game folder" list above the Executable field: `.exe`, `.sh`, `.AppImage` and `.x86_64` files up to three folders deep, best guess first (nearer the top, name shares a word with the title, bigger), leaving out installers, uninstallers, redistributables and crash handlers
- **cli:** `ludex game exes GAME` prints the same candidates

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
