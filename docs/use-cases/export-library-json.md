# Export your game library to JSON or CSV

To export your game library from ludex for scripts, spreadsheets or backups, run `ludex export`: it writes the whole library to standard output as JSON (default) or CSV.

```sh
ludex export > library.json
ludex export --format csv > library.csv
ludex export --removed > library-with-removed.json   # include removed records
```

## Machine-readable output for any command

The global `--json` flag makes every command print JSON instead of text. It goes before the subcommand:

```sh
ludex --json ls --store steam
ludex --json import --all
```

Back to [use cases](../index.md#use-cases).
