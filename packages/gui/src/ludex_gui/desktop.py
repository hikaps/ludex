"""Menu entries for the launcher: two ``.desktop`` files and an icon in the user's XDG data directory.

A Python package cannot place files outside its own directory when it is installed with pip or uv, so
``ludex gui --install-desktop`` writes them on request and ``--uninstall-desktop`` removes them again.
"""
from __future__ import annotations

import shutil
import sys
from collections.abc import Mapping
from importlib import resources
from pathlib import Path

from ludex.errors import LudexError

ICON = "ludex"
# desktop file name -> (menu name, comment, extra argument)
ENTRIES = {
    "ludex": ("Ludex", "Your game library across stores", ""),
    "ludex-console": ("Ludex Console", "Your game library, fullscreen, for a controller", " --console"),
}


def data_home(env: Mapping[str, str], home: Path) -> Path:
    """The XDG data directory: ``$XDG_DATA_HOME`` when it is an absolute path, else ``~/.local/share``."""
    configured = env.get("XDG_DATA_HOME", "")
    return Path(configured) if configured.startswith("/") else home / ".local" / "share"


def launcher_path() -> Path:
    """The ``ludex-gui`` script of this environment (``uv tool install --with`` does not put it on PATH)."""
    beside = Path(sys.executable).parent / "ludex-gui"
    found = beside if beside.is_file() else shutil.which("ludex-gui")
    if not found:
        raise LudexError("gui_launcher_missing", "cannot find the ludex-gui script to start from the menu")
    return Path(found)


def _quote(path: Path) -> str:
    """Quote a path for the Exec key of a desktop file (Desktop Entry Specification, "The Exec key")."""
    text = str(path).replace("%", "%%")
    if not any(c in text for c in " \t\n\"'\\><~|&;$*?#()`"):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def _entry(name: str, comment: str, exec_line: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        "GenericName=Game Library\n"
        f"Comment={comment}\n"
        f"Exec={exec_line}\n"
        f"Icon={ICON}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
        "Keywords=games;library;launcher;steam;gog;epic;\n"
        "StartupWMClass=ludex\n"
    )


def _targets(base: Path) -> dict[str, Path]:
    return {
        **{key: base / "applications" / f"{key}.desktop" for key in ENTRIES},
        "icon": base / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON}.svg",
    }


def install(base: Path, launcher: Path) -> list[Path]:
    """Write the entries and the icon under ``base`` (an XDG data directory); return the files written."""
    targets = _targets(base)
    written = []
    for key, (name, comment, extra) in ENTRIES.items():
        _write(targets[key], _entry(name, comment, _quote(launcher) + extra).encode())
        written.append(targets[key])
    _write(targets["icon"], (resources.files("ludex_gui") / "assets" / "ludex.svg").read_bytes())
    written.append(targets["icon"])
    return written


def uninstall(base: Path) -> list[Path]:
    """Delete what ``install`` wrote under ``base``; return the files that were there."""
    removed = []
    for path in _targets(base).values():
        if path.is_file():
            path.unlink()
            removed.append(path)
    return removed


def manage(add: bool, env: Mapping[str, str], home: Path) -> list[Path]:
    """Install (``add``) or remove the menu entries in the user's data directory; return the files touched."""
    base = data_home(env, home)
    return install(base, launcher_path()) if add else uninstall(base)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    temp.chmod(0o644)
    temp.replace(path)
