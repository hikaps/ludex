# Launching, installing and jobs

## Launch

```sh
ludex launch "Some Game"               # through the store that owns it
ludex launch "Some Game" --store gog   # when several stores can
ludex launch "Some Game" --dry-run     # show the command, do not start it
ludex launch --status                  # games ludex started itself
ludex launch --stop "Some Game"
```

A store with its own client (Steam, Heroic) is started through that client, which then owns the game: ludex does not track it as a job, but the launcher still shows it as Running. A game ludex starts itself (a local folder) is a background `play` job with its output in a log.

## Per-game settings

For games ludex runs itself:

```sh
ludex runners                          # detected Proton builds
ludex game set "Some Game" --runner GE-Proton --prefix /games/prefixes/some --exe bin/game.exe --args='-windowed' --env DXVK_HUD=fps
ludex game show "Some Game"
ludex game exes "Some Game"            # executables in the game folder, best guess first
```

A runner makes ludex start the game through `umu-run`. Arguments and environment also apply to a plugin's `launch_command`.

## Install

```sh
ludex install "Some Game"              # asks the owning store's client; Epic goes through Legendary
ludex install --status
ludex install --stop "Some Game"
```

## Downloads

A plugin that can download games (it has `acquire`) is used with:

```sh
ludex download STORE STORE_ID          # a background job; --to DIR overrides download_dir
ludex download --status
ludex download --stop STORE STORE_ID
ludex acquire STORE STORE_ID           # the same, in the foreground
```

Progress shows as a bar and a time estimate when the plugin reports numbers. Stores with their own client (Steam, Heroic) still open that client instead.

## Plugin actions

Plugins can offer extra actions for a game, for example a split-screen launcher.

```sh
ludex action "Some Game"                          # list them
ludex action "Some Game" couch:split --dry-run    # show the command
ludex action "Some Game" couch:split              # run it as a background job
```

The GUI lists them under **More** next to Play.

## Jobs, running state and play time

- Everything ludex starts in the background (`play`, `install`, `download`, `action`, plugin `service`s) is a job with a state, a log and, when known, progress. The GUI **Jobs** page lists them and can stop one.
- **Running**: the launcher shows a game as Running when its store client has it running (Steam, Heroic sideloads), also when ludex did not start it.
- **Play time**: `show` and `ls --sort played|recent` report time played from what Steam and Heroic (Epic and sideloads) recorded on this machine, plus the games ludex started itself.
