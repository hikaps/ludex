# Community plugins

Plugins that are not part of ludex. They are written and maintained by their own authors, and the ludex project does not review, vouch for or endorse them. A plugin runs with your permissions: read its source before you install it.

Install with `ludex plugin add`, then check that it loaded with `ludex providers`. To list your own plugin here, open a pull request that adds a row; to write one, see [Write a ludex plugin](write-a-plugin.md).

| Plugin | What it does | Install |
| --- | --- | --- |
| [ludex-emulators](https://github.com/hikaps/ludex-emulators) | Installs pinned emulators (PCSX2 for PlayStation 2 first) and launches your own ROMs with them. It never downloads BIOS, firmware or games. Linux x86_64. | `ludex plugin add git+https://github.com/hikaps/ludex-emulators` |
