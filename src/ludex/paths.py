from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class StatePaths:
    root: Path
    database: Path
    accounts: Path
    import_lock: Path


def _requested_root() -> Path:
    configured = os.environ.get("LUDEX_HOME")
    if configured:
        return Path(configured).expanduser().absolute()
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return (base / "ludex").absolute()


def _check_private_directory(root: Path) -> None:
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        root.parent.mkdir(parents=True, exist_ok=True)
        try:
            root.mkdir(mode=0o700)
        except FileExistsError:
            pass
        metadata = root.lstat()
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"state root must be a real directory: {root}")
    if metadata.st_uid != os.getuid():
        raise PermissionError(f"state root is owned by another user: {root}")
    if metadata.st_mode & 0o077:
        raise PermissionError(f"state root must have mode 0700: {root}")


def state_paths() -> StatePaths:
    root = _requested_root()
    _check_private_directory(root)
    return StatePaths(
        root=root,
        database=root / "library.sqlite3",
        accounts=root / "accounts.json",
        import_lock=root / "import.lock",
    )


def ensure_private_file(path: Path) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PermissionError(f"state file must be a regular file: {path.name}")
    if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
        raise PermissionError(f"state file must be owned by this user and have mode 0600: {path.name}")
