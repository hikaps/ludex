# Launcher (GUI)

`ludex-gui` is a Qt Quick launcher over the same library. It is a separate install because it brings Qt:

```sh
uv tool install ludex-games --with "ludex-gui[gamepad]"   # drop [gamepad] for mouse and keyboard only
ludex gui
```

## Pages

- **Library**: a cover-art grid (covers are fetched only for games on screen while `auto_details` is on), search, sort, store and genre filters. **Review matches** settles title matches an import was not sure about: join the game to a candidate, or keep them apart.
- **Installed**: games installed on this machine.
- **Search**: the stores' catalogs.
- **Game page**: Play or Install, with a store chooser for a game you own in several stores (otherwise the copy that is installed, else the first store alphabetically). The button shows Running or Installing while the game's job runs, so it cannot be started twice. **More** lists plugin actions. Launch options, title matching and the details are here, and a matched game shows an *Open* button linking its database entry.
- **Jobs**: installs, downloads, actions and games ludex started, with progress; stop one from here.
- **Settings**: accounts, plugins, and each plugin's settings.
- **Plugin pages**: a sidebar page for every view a plugin contributes.

The launcher imports every account when it starts unless `auto_refresh` is off.

## Controller

With the `gamepad` extra a controller drives the launcher, only while its window has focus:

| Input | Action |
|---|---|
| D-pad, left stick | move |
| A | select |
| B | back |
| X | play or install |
| LB, RB | switch pages |
| Y | jump to search |
| Start | menu with Quit and the mode switch |

On a text field, A opens an on-screen keyboard (Shift, 123 for symbols, Left/Right to move the cursor, Delete, Clear; Done submits, B closes it). Keyboard equivalents: `Ctrl+P`, `Ctrl+PgUp`, `Ctrl+PgDown`.

`ludex update` keeps the `gamepad` extra if it is in the installer's record. If an older updater removed it, reinstall with the extra: `ludex-gui[gamepad]` on stable, or `ludex-gui[gamepad] @ <the beta GUI archive URL>` on beta, as in [Install](../index.md#install).

## Console mode

```sh
ludex gui --console        # or: ludex-gui --console
```

Fullscreen and 25% larger, in a living-room layout for a TV or a handheld: a tab row instead of the sidebar, big covers, Play focused on a game, button hints in the status bar (`QT_SCALE_FACTOR` overrides the size). The Start menu, the sidebar and `F11` switch between desktop and console mode; the launcher restarts in the other mode.

## Application menu

```sh
ludex gui --install-desktop      # adds "Ludex" and "Ludex Console" with an icon
ludex gui --uninstall-desktop
```

Handy for adding them to Steam as non-Steam games.
