# Changelog

All notable changes to ludex are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Each release is a single merged pull request.

## [Unreleased]

### Changed

- **packaging:** The package is published as `ludex-games` because PyPI rejects `ludex` as too close to an existing project. The `ludex` command and the `ludex` import package are unchanged. Installs made before this change use the old package name, and `ludex update` on them cannot migrate: uninstall once (`uv tool uninstall ludex` or `pipx uninstall ludex`) and install again from the release URL.

## [0.51.0] - 2026-10-28

### Added

- **jobs:** Track, report on and stop installs ([#60](https://github.com/hikaps/ludex/pull/60))

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

## [0.46.1] - 2026-10-27

### Fixed

- **metadata:** Credit a title match with a link ([#54](https://github.com/hikaps/ludex/pull/54))

## [0.46.0] - 2026-10-27

### Added

- **metadata:** Match games no store describes by title ([#53](https://github.com/hikaps/ludex/pull/53))

## [0.45.1] - 2026-10-27

### Fixed

- **tui:** Do not select settings text on focus ([#52](https://github.com/hikaps/ludex/pull/52))

## [0.45.0] - 2026-10-27

### Added

- **tui:** Save and Discard for Settings text fields ([#51](https://github.com/hikaps/ludex/pull/51))

## [0.44.0] - 2026-10-27

### Fixed

- **local:** List game folders as installed ([#50](https://github.com/hikaps/ludex/pull/50))

## [0.43.0] - 2026-10-27

### Added

- **tui:** Vim movement keys ([#49](https://github.com/hikaps/ludex/pull/49))

## [0.42.0] - 2026-10-27

### Added

- **plugins:** Yes/no and choice fields ([#48](https://github.com/hikaps/ludex/pull/48))

## [0.41.1] - 2026-10-23

### Fixed

- **tui:** Keep search price and owned visible ([#47](https://github.com/hikaps/ludex/pull/47))

## [0.41.0] - 2026-10-23

### Added

- **tui:** Fetch game details automatically ([#46](https://github.com/hikaps/ludex/pull/46))

## [0.40.0] - 2026-10-23

### Added

- **plugins:** Metadata capability and Steam details ([#45](https://github.com/hikaps/ludex/pull/45))

## [0.39.0] - 2026-10-23

### Breaking

- **tui:** Actions per tab; calmer Settings ([#44](https://github.com/hikaps/ludex/pull/44))

## [0.38.1] - 2026-10-23

### Added

- **plugins:** Plugin ls shows the update link ([#43](https://github.com/hikaps/ludex/pull/43))

## [0.38.0] - 2026-10-23

### Added

- **tui:** Lazygit-style panes ([#42](https://github.com/hikaps/ludex/pull/42))

## [0.37.1] - 2026-10-23

### Fixed

- **tui:** No zebra stripes, one background colour ([#41](https://github.com/hikaps/ludex/pull/41))

## [0.37.0] - 2026-10-23

### Added

- **tui:** Colourful theme; fix Enter on empty list ([#40](https://github.com/hikaps/ludex/pull/40))

## [0.36.0] - 2026-10-23

### Added

- **tui:** Cleaner layout, installed marker, hints ([#39](https://github.com/hikaps/ludex/pull/39))

## [0.35.1] - 2026-10-23

### Fixed

- **tui:** Ignore the highlight event of an empty table ([#38](https://github.com/hikaps/ludex/pull/38))

## [0.35.0] - 2026-10-23

### Breaking

- **tui:** Letter shortcuts, search box on Enter ([#37](https://github.com/hikaps/ludex/pull/37))

## [0.34.0] - 2026-10-23

### Added

- **tui:** Edit plugin settings and account fields ([#36](https://github.com/hikaps/ludex/pull/36))

## [0.33.0] - 2026-10-23

### Added

- **plugins:** Plugin settings and ludex account set ([#35](https://github.com/hikaps/ludex/pull/35))

## [0.32.0] - 2026-10-23

### Added

- **tui:** Tab navigation, Settings tab, plugin switches ([#34](https://github.com/hikaps/ludex/pull/34))

## [0.31.0] - 2026-10-23

### Added

- **plugins:** Add plugin management and self-update ([#33](https://github.com/hikaps/ludex/pull/33))

## [0.30.0] - 2026-10-23

### Added

- **cli:** Yes/no settings for shortcuts and Heroic sideloads ([#32](https://github.com/hikaps/ludex/pull/32))

## [0.29.0] - 2026-10-23

### Changed

- **cli:** Move the prefix folder into global settings ([#31](https://github.com/hikaps/ludex/pull/31))

## [0.28.0] - 2026-10-23

### Added

- **tui:** Edit launch settings and the prefix folder ([#30](https://github.com/hikaps/ludex/pull/30))

## [0.27.0] - 2026-10-23

### Added

- **plugins:** Import Heroic sideloaded games ([#29](https://github.com/hikaps/ludex/pull/29))

## [0.26.0] - 2026-10-23

### Added

- **steam:** Import non-Steam shortcuts as games ([#28](https://github.com/hikaps/ludex/pull/28))

## [0.25.0] - 2026-10-23

### Added

- **local:** Run Windows games through umu-run ([#27](https://github.com/hikaps/ludex/pull/27))

## [0.24.0] - 2026-10-23

### Added

- **plugins:** Detect Proton runners and store game settings ([#26](https://github.com/hikaps/ludex/pull/26))

## [0.23.0] - 2026-10-23

### Added

- **local:** Launch native games from their folder ([#25](https://github.com/hikaps/ludex/pull/25))

## [0.22.0] - 2026-10-23

### Added

- **plugins:** Let providers add commands ([#24](https://github.com/hikaps/ludex/pull/24))

## [0.21.0] - 2026-10-23

### Added

- **plugins:** Add the acquire capability contract ([#23](https://github.com/hikaps/ludex/pull/23))

## [0.20.0] - 2026-10-23

### Added

- **plugins:** Add install capability with Steam install ([#22](https://github.com/hikaps/ludex/pull/22))

## [0.19.0] - 2026-10-22

### Added

- **tui:** Open a store page from the Search tab ([#21](https://github.com/hikaps/ludex/pull/21))

## [0.18.0] - 2026-10-22

### Added

- **plugins:** Add the search capability, find and a Search tab ([#20](https://github.com/hikaps/ludex/pull/20))

## [0.17.0] - 2026-10-22

### Added

- **plugins:** Add the installed capability and installed tabs ([#19](https://github.com/hikaps/ludex/pull/19))

## [0.16.0] - 2026-10-22

### Breaking

- **plugins:** Add the provider model with declared capabilities ([#18](https://github.com/hikaps/ludex/pull/18))

## [0.15.0] - 2026-10-22

### Added

- **cli:** Let show and launch take a game title ([#17](https://github.com/hikaps/ludex/pull/17))

## [0.14.2] - 2026-10-22

### Fixed

- **accounts:** Delete records when an account is removed ([#16](https://github.com/hikaps/ludex/pull/16))

## [0.14.1] - 2026-10-22

### Fixed

- **accounts:** Mark records removed when an account is removed ([#15](https://github.com/hikaps/ludex/pull/15))

## [0.14.0] - 2026-10-22

### Added

- **tui:** Add a terminal browser with search and launch ([#14](https://github.com/hikaps/ludex/pull/14))

## [0.13.0] - 2026-10-22

### Added

- **cli:** Launch games through their store client ([#13](https://github.com/hikaps/ludex/pull/13))

## [0.12.0] - 2026-10-22

### Added

- **local:** Accept glob paths and tab-complete path prompts ([#12](https://github.com/hikaps/ludex/pull/12))

## [0.11.1] - 2026-10-22

### Fixed

- **import:** Never remove another source's records ([#11](https://github.com/hikaps/ludex/pull/11))

## [0.11.0] - 2026-10-22

### Breaking

- **matching:** Remove the one-time dedupe command ([#10](https://github.com/hikaps/ludex/pull/10))

## [0.10.0] - 2026-10-22

### Added

- **cli:** Add export to JSON and CSV ([#9](https://github.com/hikaps/ludex/pull/9))

## [0.9.0] - 2026-10-22

### Breaking

- **accounts:** Make account names unique per source ([#8](https://github.com/hikaps/ludex/pull/8))

## [0.8.3] - 2026-10-22

### Fixed

- **cli:** Explain taken account names and check them first ([#7](https://github.com/hikaps/ludex/pull/7))

## [0.8.2] - 2026-10-22

### Fixed

- **matching:** Dedupe merges same store id across accounts ([#6](https://github.com/hikaps/ludex/pull/6))

## [0.8.1] - 2026-10-22

### Added

- **matching:** Add dedupe for already imported games ([#5](https://github.com/hikaps/ludex/pull/5))

## [0.8.0] - 2026-10-22

### Breaking

- **matching:** Join games across stores, add review and merge ([#4](https://github.com/hikaps/ludex/pull/4))

## [0.7.0] - 2026-10-22

### Added

- **local:** Import games from a local directory ([#3](https://github.com/hikaps/ludex/pull/3))

## [0.6.0] - 2026-10-22

### Added

- **epic:** Import owned games from the Legendary cache ([#2](https://github.com/hikaps/ludex/pull/2))

## [0.5.0] - 2026-10-22

### Added

- Initial repository.
