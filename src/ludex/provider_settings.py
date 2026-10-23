"""Plugin-wide settings: values for the ``Provider.settings`` a plugin declares.

Stored per provider in ``<state>/plugin-settings.json`` (mode 0600, secrets included, never
printed). ``accounts.get_account`` merges them under the account's own fields, so every plugin
function that receives a config mapping sees them; plugin commands get them as ``ctx.settings``.
"""
from __future__ import annotations

from collections.abc import Mapping

from .errors import LudexError
from .paths import StatePaths
from .plugins import ConfigField, Provider
from .private_io import read_json_private, write_json_private


def _file(paths: StatePaths):
    return paths.root / "plugin-settings.json"


def _load(paths: StatePaths) -> dict[str, dict[str, str]]:
    path = _file(paths)
    if not path.exists() and not path.is_symlink():
        return {}
    try:
        data = read_json_private(path)
    except ValueError as exc:
        raise LudexError("settings_corrupt", "the plugin settings file is unreadable") from exc
    if not isinstance(data, dict):
        raise LudexError("settings_corrupt", "the plugin settings file is unreadable")
    return {
        str(name): {str(k): str(v) for k, v in values.items()}
        for name, values in data.items()
        if isinstance(values, dict)
    }


def get_values(paths: StatePaths, provider: str) -> dict[str, str]:
    return _load(paths).get(provider, {})


def describe(paths: StatePaths, plugin: Provider) -> dict[str, str | None]:
    """Each declared setting's value for display; secret values show as ``(set)``."""
    values = get_values(paths, plugin.name)
    return {
        f.name: (("(set)" if f.secret else values[f.name]) if f.name in values else None)
        for f in plugin.settings
    }


def field_for(plugin: Provider, key: str) -> ConfigField:
    for field in plugin.settings:
        if field.name == key:
            return field
    raise LudexError("unknown_setting", f"{plugin.name} has no setting {key}")


def set_value(paths: StatePaths, plugin: Provider, key: str, value: str | None) -> None:
    """Set ``key`` (``None`` removes it, back to the plugin's own default)."""
    field_for(plugin, key)
    if value is not None and not value.strip():
        raise LudexError("empty_value", f"setting {key} must not be empty; use --reset to remove it")
    data = _load(paths)
    values = data.setdefault(plugin.name, {})
    if value is None:
        values.pop(key, None)
    else:
        values[key] = value
    if not values:
        del data[plugin.name]
    write_json_private(_file(paths), data)
