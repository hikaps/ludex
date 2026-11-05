from __future__ import annotations

from collections.abc import Sequence

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from .errors import LudexError
from .paths import StatePaths
from .plugins import ConfigField
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
    """Accounts keyed ``source:name``. Files written before names were per source used ``name``."""
    if not paths.accounts.exists() and not paths.accounts.is_symlink():
        return {}
    try:
        data = read_json_private(paths.accounts)
    except ValueError as exc:
        raise LudexError("accounts_corrupt", "accounts file is unreadable") from exc
    if not isinstance(data, dict):
        raise LudexError("accounts_corrupt", "accounts file is unreadable")
    return {
        key if ":" in key or not isinstance(entry, dict) else f"{entry.get('source')}:{key}": entry
        for key, entry in data.items()
    }


def _check_name(name: str) -> None:
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise LudexError("invalid_account_name", "account name must match [a-z][a-z0-9_-]{0,31}")


def _resolve(data: dict[str, Any], ref: str) -> str:
    """``source:name`` or a bare name that is unique across sources."""
    if ref in data:
        return ref
    matches = [key for key in data if ":" not in ref and key.partition(":")[2] == ref]
    if len(matches) > 1:
        raise LudexError("account_ambiguous", f"account {ref} exists for several sources; use one of: {', '.join(sorted(matches))}")
    if not matches:
        raise LudexError("account_not_found", f"account {ref} not found")
    return matches[0]


def add_account(paths: StatePaths, name: str, source: str, config: Mapping[str, str]) -> None:
    _check_name(name)
    data = _load(paths)
    key = f"{source}:{name}"
    if key in data:
        raise LudexError("account_exists", f"account {name} already exists for source {source}")
    data[key] = {"source": source, "config": dict(config)}
    write_json_private(paths.accounts, data)


def get_account(paths: StatePaths, ref: str) -> Account:
    data = _load(paths)
    key = _resolve(data, ref)
    entry = data[key]
    if not isinstance(entry, dict) or not isinstance(entry.get("source"), str):
        raise LudexError("account_not_found", f"account {ref} not found")
    config = entry.get("config")
    if not isinstance(config, dict):
        config = {}
    from .provider_settings import get_values  # plugin-wide settings sit under the account's own fields

    merged = {**get_values(paths, entry["source"]), **{str(k): str(v) for k, v in config.items()}}
    return Account(key.partition(":")[2], entry["source"], MappingProxyType(merged))


def list_accounts(paths: StatePaths) -> list[tuple[str, str]]:
    data = _load(paths)
    return sorted(
        (key.partition(":")[2], entry["source"])
        for key, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("source"), str)
    )


def remove_account(paths: StatePaths, ref: str) -> None:
    data = _load(paths)
    del data[_resolve(data, ref)]
    write_json_private(paths.accounts, data)


def update_account(
    paths: StatePaths, ref: str, fields: Sequence[ConfigField], values: Mapping[str, str], unset: Sequence[str] = ()
) -> list[str]:
    """Change an account's configuration in place (records are untouched). Returns the keys changed."""
    known = {f.name: f for f in fields}
    for key in [*values, *unset]:
        if key not in known:
            raise LudexError("unknown_field", f"this account's source has no field {key}")
    for key, value in values.items():
        if not value:
            raise LudexError("empty_value", f"field {key} must not be empty")
    values = {key: known[key].clean(value) for key, value in values.items()}
    for key in unset:
        if not known[key].optional:
            raise LudexError("required_field", f"field {key} is required; set a new value instead")
    data = _load(paths)
    key = _resolve(data, ref)
    entry = data[key]
    config = dict(entry["config"]) if isinstance(entry.get("config"), dict) else {}
    config.update(values)
    for name in unset:
        config.pop(name, None)
    entry["config"] = config
    write_json_private(paths.accounts, data)
    return sorted({*values, *unset})
