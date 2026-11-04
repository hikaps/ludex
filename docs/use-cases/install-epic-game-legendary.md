# Find installed games and install an Epic game through Legendary

To see which of your games are installed on this machine, and to install an Epic game you own, use `ludex ls --installed` and `ludex install`. Epic installs run through Legendary (the Heroic Flatpak's bundled copy, otherwise a `legendary` on your PATH), using Heroic's config so Heroic sees the result.

## Find installed games

```sh
ludex ls --installed
```

Installed state is read live from each source and never stored. Search the stores' catalogs (uses the network):

```sh
ludex find "hades"
```

## Install an Epic game

```sh
ludex install "Game Title" --dry-run   # show the exact command, run nothing
ludex install "Game Title"             # start the install in the background
ludex install "Game Title" --store epic   # when several stores can install it
ludex install --status                 # progress of installs ludex started
ludex install "Game Title" --stop      # cancel; run install again to resume
```

Games go under the account's `install_dir` (default `~/Games/Heroic`):

```sh
ludex account set epic --set install_dir=/mnt/games/epic
```

If neither the Heroic Flatpak nor `legendary` is found, the command fails with an error saying so. Other stores install through their own client (for example Steam).

Then start it:

```sh
ludex launch "Game Title" --dry-run
ludex launch "Game Title"
```
