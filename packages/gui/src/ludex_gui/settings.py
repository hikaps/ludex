"""Settings for QML: library switches, prefix folder, sources, plugins, plugin settings and accounts.

Sections are plain dictionaries. A secret value never leaves this module: a field only says whether one is set, and
saving a blank secret keeps the saved one.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from ludex.accounts import get_account, list_accounts, update_account
from ludex.errors import LudexError
from ludex.game_settings import get_prefix_root, set_prefix_root
from ludex.metadata import get_auto_details, get_auto_match, set_auto_details, set_auto_match
from ludex.paths import StatePaths
from ludex.plugin_manager import list_plugins, set_plugin_enabled
from ludex.plugins import ConfigField, Provider
from ludex.provider_settings import get_values, set_value
from ludex.refresh import get_auto_refresh, set_auto_refresh
from ludex.storage import writer_lock
from ludex.switches import get_switch, set_switch

SOURCE_LABELS = {"steam_shortcuts": "Steam non-Steam shortcuts", "heroic_sideload": "Heroic sideloaded games"}


def _flag(on: bool) -> str:
    return "yes" if on else "no"


def _field(name: str, label: str, value: str, *, kind: str = "yes_no", help: str = "") -> dict[str, Any]:
    return {"name": name, "label": label, "kind": kind, "value": value, "help": help, "choices": [], "optional": False, "hasValue": bool(value)}


def _config_field(field: ConfigField, value: str | None) -> dict[str, Any]:
    kind = "secret" if field.secret else "path" if field.path else field.kind
    return {
        "name": field.name, "label": field.name + (" (optional)" if field.optional else ""), "kind": kind, "help": field.help,
        "value": "" if field.secret else (value or ""), "choices": list(field.choices), "optional": field.optional, "hasValue": bool(value),
    }


class SettingsController(QObject):
    changed = Signal()
    notice = Signal(str, bool)
    libraryChanged = Signal()  # a source switch added or removed games

    def __init__(
        self, paths: StatePaths, conn: sqlite3.Connection, sources: Mapping[str, Provider], default_prefix: Path,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._paths, self._conn, self._sources, self._default_prefix = paths, conn, sources, default_prefix
        self._sections: list[dict[str, Any]] = []
        self.reload()

    def _get_sections(self) -> list[dict[str, Any]]:
        return self._sections

    sections = Property("QVariantList", _get_sections, notify=changed)

    def _write(self, change: Callable[[], object]) -> bool:
        try:
            with writer_lock(self._paths.import_lock):
                change()
        except LudexError as exc:
            self.notice.emit(exc.message, True)
            return False
        return True

    def reload(self) -> None:
        conn, paths = self._conn, self._paths
        sections: list[dict[str, Any]] = [
            {"id": "library", "title": "Library", "hint": "", "instant": True, "fields": [
                _field("auto_refresh", "Import every account when ludex starts (stores are asked; turn off when offline)", _flag(get_auto_refresh(conn))),
                _field("auto_details", "Fetch details and cover art for games on screen (the store sees their ids)", _flag(get_auto_details(conn))),
                _field("auto_match", "Match games no store describes by name (sends the folder name to the database plugin)", _flag(get_auto_match(conn))),
            ]},
            {"id": "prefix", "title": "Default prefix folder", "hint": "Each game gets its own prefix inside it. Blank resets.", "instant": False, "fields": [
                _field("prefix", "folder", str(get_prefix_root(conn, self._default_prefix)), kind="path"),
            ]},
            {"id": "sources", "title": "Sources", "hint": "", "instant": True, "fields": [
                _field(key, text, _flag(get_switch(paths, key))) for key, text in SOURCE_LABELS.items()
            ]},
        ]
        plugins = list_plugins()
        sections.append({
            "id": "plugins", "title": "Plugins", "instant": True,
            "hint": "Enabling or disabling applies the next time ludex starts. Add plugins with: ludex plugin add <git link or package>" if plugins
            else "No plugins installed. Add one with: ludex plugin add <git link or package>",
            "fields": [_field(p["name"], f"{p['name']} {p['version']}  ({', '.join(p['providers'])})", _flag(p["enabled"])) for p in plugins],
        })
        for provider in sorted(self._sources.values(), key=lambda p: p.name):
            if provider.settings:
                values = get_values(paths, provider.name)
                sections.append({"id": f"plugin:{provider.name}", "title": f"{provider.name} settings", "hint": "", "instant": False, "fields": [_config_field(f, values.get(f.name)) for f in provider.settings]})
        for name, source in list_accounts(paths):
            if source in self._sources:
                ref = f"{source}:{name}"
                config = get_account(paths, ref).config
                sections.append({"id": f"account:{ref}", "title": ref, "hint": "Save, then run 'ludex import' to pick up the change.", "instant": False,
                                 "fields": [_config_field(f, config.get(f.name)) for f in self._sources[source].config_fields]})
        self._sections = sections
        self.changed.emit()

    # --- changes --------------------------------------------------------------------------------------------

    @Slot(str, str, str)
    def setInstant(self, section: str, name: str, value: str) -> None:
        on = value == "yes"
        ok = True
        if section == "library":
            setter = {"auto_refresh": set_auto_refresh, "auto_details": set_auto_details, "auto_match": set_auto_match}.get(name)
            ok = setter is not None and self._write(lambda: setter(self._conn, on))
        elif section == "sources" and name in SOURCE_LABELS:
            count: list[int] = []
            ok = self._write(lambda: count.append(set_switch(self._paths, self._conn, self._sources, name, on)))
            if ok:
                self.notice.emit(f"{SOURCE_LABELS[name]}: {'added ' + str(count[0]) + ' games' if on else 'removed ' + str(count[0]) + ' records'}", False)
                self.libraryChanged.emit()
        elif section == "plugins":
            try:
                set_plugin_enabled(name, on)
            except LudexError as exc:
                ok = False
                self.notice.emit(exc.message, True)
            else:
                self.notice.emit(f"{'enabled' if on else 'disabled'} {name}; restart ludex to apply", False)
        if not ok:
            self.reload()  # show what is true

    @Slot(str, "QVariantMap")
    def save(self, section: str, values: dict[str, Any]) -> None:
        """Save the edited fields of one section: a blank secret keeps the saved one, a blank optional value is removed."""
        if section == "prefix":
            text = str(values.get("prefix", "")).strip()
            if self._write(lambda: set_prefix_root(self._conn, text or None)):
                shown = str(get_prefix_root(self._conn, self._default_prefix))
                self.notice.emit(f"prefix folder: {shown}", False)
            self.reload()
            return
        kind, _, name = section.partition(":")
        fields: tuple[ConfigField, ...]
        if kind == "plugin" and name in self._sources:
            provider, fields, saved = self._sources[name], self._sources[name].settings, get_values(self._paths, name)
        elif kind == "account":
            provider = self._sources.get(name.partition(":")[0])
            if provider is None:
                return
            fields, saved = provider.config_fields, get_account(self._paths, name).config
        else:
            return
        put: dict[str, str] = {}
        drop: list[str] = []
        for field in fields:
            if field.name not in values:
                continue
            text = str(values[field.name]).strip()
            current = "" if field.secret else saved.get(field.name, "") or ("no" if field.kind == "yes_no" else "")
            if text == current:
                continue  # unchanged (a blank secret never replaces the saved one)
            if field.kind == "yes_no" or text:
                put[field.name] = text
            else:
                drop.append(field.name)
        if not (put or drop):
            return

        def apply() -> None:
            if kind == "plugin":
                for key, text in put.items():
                    set_value(self._paths, provider, key, text)
                for key in drop:
                    set_value(self._paths, provider, key, None)
            else:
                update_account(self._paths, name, provider.config_fields, put, drop)

        if self._write(apply):
            self.notice.emit("saved", False)
        self.reload()
