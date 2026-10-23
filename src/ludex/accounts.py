from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .errors import LudexError
from .paths import StatePaths
from .private_io import read_json_private, write_json_private

_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")


@dataclass(frozen=True, slots=True)
class Account:
    name: str
    source: str
    config: Mapping[str, str]

    def __repr__(self) -> str:
        return f"Account(name={self.name!r}, source={self.source!r})"


def _load(paths: StatePaths) -> dict[str, Any]:
    if not paths.accounts.exists() and not paths.accounts.is_symlink():
        return {}
    try:
        data = read_json_private(paths.accounts)
    except ValueError as exc:
        raise LudexError("accounts_corrupt", "accounts file is unreadable") from exc
    if not isinstance(data, dict):
        raise LudexError("accounts_corrupt", "accounts file is unreadable")
    return data


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise LudexError("invalid_account_name", "account name must match [a-z][a-z0-9_-]{0,31}")


def add_account(paths: StatePaths, name: str, source: str, config: Mapping[str, str]) -> None:
    _check_name(name)
    data = _load(paths)
    if name in data:
        raise LudexError("account_exists", f"account {name} already exists")
    data[name] = {"source": source, "config": dict(config)}
    write_json_private(paths.accounts, data)


def get_account(paths: StatePaths, name: str) -> Account:
    entry = _load(paths).get(name)
    if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
        raise LudexError("account_not_found", f"account {name} not found")
    config = entry.get("config")
    if not isinstance(config, dict):
        config = {}
    return Account(name, entry["source"], MappingProxyType({str(k): str(v) for k, v in config.items()}))


def list_accounts(paths: StatePaths) -> list[tuple[str, str]]:
    data = _load(paths)
    return sorted(
        (name, entry["source"])
        for name, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("source"), str)
    )


def remove_account(paths: StatePaths, name: str) -> None:
    data = _load(paths)
    if name not in data:
        raise LudexError("account_not_found", f"account {name} not found")
    del data[name]
    write_json_private(paths.accounts, data)
