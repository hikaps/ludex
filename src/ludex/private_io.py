from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any

from .paths import ensure_private_file


def atomic_write_private(path: Path, data: bytes) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_private_file(path)
    temporary = path.parent / f".{path.name}.{secrets.token_hex(8)}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def write_json_private(path: Path, value: Any) -> None:
    atomic_write_private(path, json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def read_json_private(path: Path, *, maximum_bytes: int = 1024 * 1024) -> Any:
    ensure_private_file(path)
    raw = path.read_bytes()
    if len(raw) > maximum_bytes:
        raise ValueError("private state file exceeds its size limit")
    return json.loads(raw)
