"""The command lines of the processes of this user, for providers that tell which games are running (Linux ``/proc``)."""
from __future__ import annotations

from pathlib import Path


def command_lines() -> list[list[str]]:
    """The argument list of every readable process; empty where there is no ``/proc``. Never raises."""
    found: list[list[str]] = []
    try:
        entries = [p for p in Path("/proc").iterdir() if p.name.isdigit()]
    except OSError:
        return found
    for entry in entries:
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:  # gone since the listing, or not ours
            continue
        if raw:
            found.append(raw.decode("utf-8", "replace").rstrip("\0").split("\0"))
    return found
