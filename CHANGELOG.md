# Changelog

All notable changes to ludex are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a single merged pull request.

## [Unreleased]

### Added

- **plugins, cli, gui:** a plugin can offer extra actions for a game with the optional `actions(store, store_id)` (API version unchanged), for example a split-screen launcher. Each `GameAction` has an id, a label and an `argv` (absolute executable, no shell). The game page shows them as buttons, `ludex action GAME` lists them and `ludex action GAME PLUGIN:ID [--store S] [--dry-run]` runs one as a background `action` job with its output in the job log. An `actions` function that declares `settings` receives the plugin's settings, as `search` does.

## [0.64.0] - 2026-11-23

### Added

- **core, cli:** `ludex dedupe` (with `--dry-run`) joins every group of games matched to one game-database entry, or matched to the Steam entry of a game you own: it catches matches made before games joined on a shared match. It also runs after every import and refresh.
- **gui, plugins:** games a store client runs show as "Running" on their card and page, whoever started them. A provider declares the optional `running(config)` (API version unchanged); Steam (the `reaper SteamLaunch AppId=` process) and Heroic sideloads (a process running the game's program) do. Heroic is a heuristic: Heroic keeps no record of what runs.
- **core:** a game matched to a database entry that another game is matched to, or owns as a store copy (a Steam match is the Steam app), is now the same game: its copies join. This also covers a match you choose by hand.
- **gui:** the ludex icon is shown beside the name in the sidebar and in the console tab row.
- **gui:** a game owned in several stores shows a store chooser next to Play (or Install) on its page; without a choice a click uses the store with an installed copy, else the first alphabetically. "Review matches" on the library page settles the title matches an import was not sure about (join the game to a candidate, or keep them apart), as `ludex review` and `ludex merge` do.
- **core:** `ludex.launch.usable_stores(conn, sources, game_id, verb)` lists the stores a game can be launched or installed from.

### Changed

- **gui:** after a game that showed as "Running" quits, the launcher raises itself and takes the focus back (it stayed behind the store client or was left unfocused, so the pad did nothing).
- **gui:** the status-bar message fades after 10 seconds (it stays while a refresh or download is running), and click or B on the pad dismisses it.
- **docs, packaging:** the tagline is now "Every game you own, in one local library" (README, docs home, site description, PyPI summaries and keywords). The README has a Launcher (GUI) section (controller, console mode, store chooser, match review) instead of one long bullet; the introduction and docs home mention the GUI.

### Fixed

- **steam:** cover art for newer Steam apps and demos (for example Fart Together Demo) that have no image at the classic path: when the usual files are missing, the banner the app's store entry names (under Steam's own image hosts, over https) is used.
- **gui:** the controller can navigate Settings in console mode: a page you switch to takes the focus (it stayed on a hidden control of the previous page, so the D-pad went nowhere), and Up and Down walk the form's controls in reading order instead of skipping the text fields and menus that sit left of a button below them.
- **gui:** the Library and Installed tabs are separate pages with their own search text, store, genre and sort (they shared one, so a search typed in one showed in the other).
- **gui:** a controller can walk a dialog that opens with no control focused (the match dialog, among others): the first D-pad press lands on its first control, and Up and Down leave a one-line text field instead of getting stuck in it, so the results can be reached and picked.
- **gui:** console mode can refresh the library: the Start menu has "Refresh library" (the Refresh button of the library page is hidden in console mode).
- **gui:** the "refreshing accounts…" message no longer stays in the status bar after a start-up refresh that found nothing new.
- **gui:** a controller that Steam shows twice (the real pad and its virtual copy) presses a button once instead of twice, and unplugging a pad releases whatever it was holding.
- **gui:** console mode says so in the status bar when controller support is not installed (`ludex-gui[gamepad]`) instead of silently ignoring the pad.

## [0.63.0] - 2026-11-21

### Added

- **gui:** a game controller drives the launcher when `ludex-gui[gamepad]` is installed (SDL2 through PySDL2): D-pad or left stick move focus, A selects, B goes back, X plays or installs, LB and RB switch between pages; `Ctrl+P`, `Ctrl+PgUp` and `Ctrl+PgDown` do the same on a keyboard. It acts only while the launcher window has focus, so a running game's input never reaches ludex. Every control can now be reached and activated from the keyboard (Return on buttons, chips and toggles, lists of matches, search results and plugin view rows, with a visible focus ring), and the page scrolls to the focused control.
- **gui:** `ludex gui --console` (and `ludex-gui --console`) opens the launcher fullscreen and 25% larger (unless `QT_SCALE_FACTOR` is set) in a living-room layout: a tab row replaces the sidebar, covers are bigger, a game page starts on Play, and the status bar lists the controller buttons for the current screen; on the controller Y jumps to the search field and Start opens a menu to resume or quit.
- **gui:** `ludex gui --install-desktop` (or `ludex-gui --install-desktop`) adds Ludex and Ludex Console to the application menu with an icon, in `$XDG_DATA_HOME` (default `~/.local/share`); `--uninstall-desktop` removes them. The window now has the icon and, on Wayland, the application id `ludex` that matches the menu entry.
- **gui:** an on-screen keyboard for the controller: A on a text field (search, Settings, account forms, launch options) opens it; Shift, a symbols layer, cursor keys, Delete, Clear and Done (which submits the field like Return); B closes it. Secret fields show dots in its preview.
- **gui:** switch between the desktop and the console layout without restarting by hand: "Console mode" at the bottom of the sidebar, "Switch to desktop/console mode" in the Start menu, or `F11`. The launcher restarts in the other mode (the console scale is only applied in console mode).
- **gui:** Settings can update a managed plugin (reinstalled from the source it was added with, after a trust confirmation) and remove one (after a confirmation). Both take effect after a restart.

### Fixed

- **gui:** the Play button on a game card no longer flickers while the pointer is on it (the hover moved from under the button to the button and back). The card and the game page now follow the game's job: Play shows "Running…" or "Installing…" and is disabled while it runs (and "Starting…" for a few seconds when a store client was asked to start it), so a click, the controller or `Ctrl+P` no longer starts the game two or three times.
- **gui:** the Search and Settings labels in the sidebar sit centred in their rows like the others; their glyphs come from a taller fallback font, which pushed the label to the top.
- **update:** `ludex update` no longer removes `ludex-gui` (or other `--with` extras it knew of): it reinstalls the GUI next to ludex-games. The rolling beta release now carries `ludex-gui.tar.gz` for this (and for `uv tool install <beta>/ludex.tar.gz --with <beta>/ludex-gui.tar.gz`). The stable channel reinstalls from PyPI (the old `stable` release URL did not exist), and any version without `.dev` counts as stable. The JSON result now lists `commands` instead of `command`.

## [0.62.0] - 2026-11-20

Also includes 0.61.0 below, which was never published to PyPI.

### Added

- **gui:** `ludex-gui` is a new distribution: a Qt Quick game launcher (`ludex gui`, or the `ludex-gui` command on its own) in the style of Heroic or Hydra. A dark window with a sidebar, a cover-art grid library, a game page with a hero banner and a Play or Install button, Search, Jobs and Settings (which can also add a plugin after a trust confirmation), a Launch options dialog and a title-match chooser on each game page, account setup and removal in Settings, and one sidebar page per plugin view (row actions run only after a separate confirmation). It uses only the core API and is not part of `ludex-games`, because it brings Qt (PySide6): install it next to `ludex-games`. Without it `ludex gui` reports `gui_missing`
- **genres:** filter and browse by genre from the kept details of your games. `ludex ls --genre`, `ludex genres`, and `ludex metadata --all` (asks for the details of every game that has none, one request each) in the CLI; `f` cycles the genre filter and `d` fetches missing details in the TUI; a genre box and a Fetch details button in the GUI library. Core: `list_games(genre=)`, `ludex.library.list_genres`, and `ludex.details` (`fetch_missing_details`, `games_without_details`). Games a plugin has no details for are asked again on the next run.
- **plugins:** a provider can contribute `cover(store_id)`, the bytes of a game's cover image; `ludex.artwork` (`cached_cover`, `fetch_cover`) asks the plugins, checks the size (4 MiB) and file signature, and keeps the file under the state folder, remembering "no cover" for a week. The Steam provider serves Steam's portrait art (else the store banner); the RAWG provider serves its image, including for games matched by title. The GUI fetches covers only for games on screen and only while `auto_details` is on. `cached_match` also returns the match's `id`. A plugin that offers `cover` needs `ludex-core>=0.62.0`; `API_VERSION` stays 3

### Changed

- **accounts:** `ludex.account_setup` (`create_account`, `delete_account`) holds what `ludex account add` and `ludex account rm` do, so the GUI shares it with the CLI
- **game settings:** `ludex.game_settings` gains `format_arguments`, `parse_arguments`, `format_environment` and `parse_environment`, shared by the TUI and GUI launch-settings forms
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
