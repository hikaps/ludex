"""Find the files in a game folder that could be its executable, best guess first."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .storage import normalize_title

_SUFFIXES = {".exe", ".sh", ".appimage", ".x86_64"}
# installers, uninstallers, redistributables and crash reporters are never the game
_NOISE = re.compile(r"(unins|uninst|vc_?redist|vcredist|dxsetup|dotnet|ndp\d|oalinst|crashhandler|crashreport|crashpad|ue4prereq|directx|physx|setup)", re.I)
_MAX_DEPTH = 3
_MAX_VISITED = 5000  # a game folder can hold tens of thousands of files; stop looking after this many entries


def find_executables(folder: Path, title: str = "", limit: int = 30) -> list[Path]:
    """Candidate executables under ``folder`` (``.exe``, ``.sh``, ``.AppImage``, ``.x86_64``; at most three levels deep).

    Best guess first: nearer the top, then a name that shares a word with ``title``, then bigger. Paths are relative to ``folder``.
    ponytail: stops after 5000 entries, so a huge folder may hide some; type the path instead.
    """
    words = set(normalize_title(title).split())
    found: list[tuple[tuple[int, int, int, str], Path]] = []
    visited = 0
    root = str(folder)
    for current, dirs, files in os.walk(root):
        depth = Path(current).relative_to(root).parts.__len__()
        dirs[:] = sorted(d for d in dirs if not d.startswith(".")) if depth < _MAX_DEPTH else []
        for name in files:
            visited += 1
            if visited > _MAX_VISITED:
                break
            path = Path(current) / name
            if path.suffix.lower() not in _SUFFIXES or _NOISE.search(name) or not path.is_file():
                continue
            shared = len(words & set(normalize_title(path.stem).split()))
            try:
                size = path.stat().st_size
            except OSError:
                continue
            found.append(((depth, -shared, -size, name.lower()), path.relative_to(root)))
        if visited > _MAX_VISITED:
            break
    return [path for _, path in sorted(found, key=lambda item: item[0])[:limit]]
