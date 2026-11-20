"""Create and delete accounts (what ``ludex account add`` and ``ludex account rm`` do), for any front end."""
from __future__ import annotations

from collections.abc import Mapping

from .accounts import add_account, get_account, list_accounts, remove_account
from .errors import LudexError
from .library import delete_account_records
from .paths import StatePaths
from .plugins import Provider
from .storage import connect, writer_lock


def create_account(paths: StatePaths, plugin: Provider, name: str, values: Mapping[str, str]) -> None:
    """Save a new account of ``plugin``: unknown fields are refused, required ones must be given, every value is cleaned.

    Blank values of optional fields are left out. The account is not imported; the caller does that.
    """
    if plugin.fetch is None:
        raise LudexError("no_owned_capability", f"provider {plugin.name} cannot list owned games, so it has no accounts")
    fields = {f.name: f for f in plugin.config_fields}
    for key in values:
        if key not in fields:
            raise LudexError("unknown_field", f"source {plugin.name} has no field {key}")
    config: dict[str, str] = {}
    for field in plugin.config_fields:
        value = values.get(field.name, "")
        if not value:
            if not field.optional:
                raise LudexError("empty_value", f"field {field.name} must not be empty")
            continue
        config[field.name] = field.clean(value)
    add_account(paths, name, plugin.name, config)


def delete_account(paths: StatePaths, ref: str) -> int:
    """Forget an account and delete its records (the games only it owned go with them). Returns how many records went."""
    try:
        account = get_account(paths, ref)
    except LudexError as exc:
        if exc.code != "account_not_found" or ":" in ref:
            raise
        # an account already gone from the file can still have stale records: clear those
        name, scope = ref, {"keep_stores": [s for n, s in list_accounts(paths) if n == ref]}
    else:
        remove_account(paths, ref)
        name, scope = account.name, {"store": account.source}
    with writer_lock(paths.import_lock):
        conn = connect(paths.database)
        try:
            changed = delete_account_records(conn, name, **scope)
        finally:
            conn.close()
    if "keep_stores" in scope and not changed:
        raise LudexError("account_not_found", f"account {ref} not found")
    return changed
