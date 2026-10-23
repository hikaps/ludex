"""Find installed Proton builds (ge-proton, proton-cachyos, Valve Proton, UMU-Proton...).

A runner is a folder that contains an executable ``proton`` script. They are looked up in Steam's
``compatibilitytools.d``, Steam's own ``steamapps/common`` (``Proton *``), and Heroic's
``tools/proton``, native and Flatpak. The folder is what umu-run takes as ``PROTONPATH``.
ponytail: Proton only (no plain Wine, no Lutris runners); add when a game needs them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import LudexError


@dataclass(frozen=True, slots=True)
class Runner:
    name: str
    path: Path
    origin: str


def _roots(home: Path) -> list[tuple[str, Path]]:
    steam = [home / ".local/share/Steam", home / ".steam/root", home / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    heroic = [home / ".config/heroic", home / ".var/app/com.heroicgameslauncher.hgl/config/heroic"]
    found = [("steam", s / "compatibilitytools.d") for s in steam]
    found += [("steam", s / "steamapps/common") for s in steam]
    found += [("heroic", h / "tools/proton") for h in heroic]
    return found


def find_runners(home: Path | None = None) -> list[Runner]:
    """Every Proton build found, in lookup order; the same folder reached twice appears once."""
    home = home or Path.home()
    runners: list[Runner] = []
    seen: set[Path] = set()
    for origin, root in _roots(home):
        try:
            children = sorted(root.iterdir())
        except OSError:
            continue
        for folder in children:
            script = folder / "proton"
            if not (folder.is_dir() and script.is_file() and os.access(script, os.X_OK)):
                continue
            if origin == "steam" and root.name == "common" and not folder.name.startswith("Proton"):
                continue
            real = folder.resolve()
            if real not in seen:
                seen.add(real)
                runners.append(Runner(folder.name, folder, origin))
    return runners


def resolve_runner(ref: str, home: Path | None = None) -> Runner:
    """A runner by its exact name, or by the path of a folder holding a ``proton`` script."""
    for runner in find_runners(home):
        if runner.name == ref:
            return runner
    path = Path(ref).expanduser()
    if path.is_absolute() and (path / "proton").is_file():
        return Runner(path.name, path, "path")
    raise LudexError("runner_not_found", f"no runner named {ref!r}; see 'ludex runners'")
