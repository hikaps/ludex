# List the games you own across stores on Linux

To see every game you own on Steam, Epic, Heroic and local folders in one list on Linux, import each store into ludex once and then use `ludex ls`. Games that several stores share are shown as one entry with all its stores.

## Import your stores

```sh
ludex setup steam
ludex setup epic
ludex setup heroic
ludex setup local
```

Each `setup` asks for the source's settings, adds an account and imports it. See the per-store pages: [Steam](import-steam-library.md), [Epic and Heroic](import-epic-heroic-games.md), [local folders](add-local-games.md). To refresh everything later:

```sh
ludex import --all
```

## List and search

```sh
ludex ls                          # all games (first 50)
ludex ls portal                   # search by title
ludex ls --store steam            # only one store
ludex ls --account steam         # only one account (by account name)
ludex ls --installed              # only games installed on this machine
ludex ls --removed                # include games removed from a store
ludex ls --limit 100 --offset 100 # paging
ludex show "Portal"               # details for one game (id or title)
```

## Same game in two stores

When a title matches more than one game, ludex does not merge it automatically; it queues it for you:

```sh
ludex review              # list title matches that need a decision
ludex merge 12 40         # merge game 40 into game 12
ludex review --dismiss 3  # keep that item's game separate
```
