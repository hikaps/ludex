"""The Settings page: library switches, prefix folder, sources, plugins, plugin settings and accounts."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

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


class _Field:
    """One plugin or account field: a widget and what to save. Secrets are never shown; blank keeps the saved value."""

    def __init__(self, field: ConfigField, value: str | None) -> None:
        self.field = field
        self.saved = "" if field.secret else (value or "")
        if field.kind == "yes_no":
            self.widget: QWidget = QCheckBox()
            self.widget.setChecked(value == "yes")
        elif field.kind == "choice":
            self.widget = QComboBox()
            if field.optional:
                self.widget.addItem("")
            self.widget.addItems(list(field.choices))
            self.widget.setCurrentText(value or "")
        else:
            self.widget = QLineEdit(self.saved)
            if field.secret:
                self.widget.setEchoMode(QLineEdit.EchoMode.Password)
                self.widget.setPlaceholderText("(set; type to replace)" if value else "")
        self.widget.setToolTip(field.help)

    def text(self) -> str:
        if isinstance(self.widget, QCheckBox):
            return "yes" if self.widget.isChecked() else "no"
        if isinstance(self.widget, QComboBox):
            return self.widget.currentText()
        return self.widget.text().strip()

    def changed(self) -> bool:
        if isinstance(self.widget, QCheckBox):
            return (self.saved == "yes") != self.widget.isChecked()
        return self.text() != self.saved

    def remember(self) -> None:
        self.saved = "" if self.field.secret else self.text()
        if isinstance(self.widget, QLineEdit) and self.field.secret:
            self.widget.clear()
            self.widget.setPlaceholderText("(set; type to replace)")


class SettingsPage(QScrollArea):
    def __init__(
        self,
        paths: StatePaths,
        conn: sqlite3.Connection,
        sources: Mapping[str, Provider],
        notify: Callable[[str, bool], None],
        changed: Callable[[], None],
        default_prefix: Path,
    ) -> None:
        super().__init__()
        self._paths, self._conn, self._sources, self._notify, self._changed = paths, conn, sources, notify, changed
        self._default_prefix = default_prefix
        self.setWidgetResizable(True)
        body = QWidget()
        self._layout = QVBoxLayout(body)
        self.setWidget(body)
        self._build()
        self._layout.addStretch(1)

    def _write(self, change: Callable[[], object]) -> bool:
        try:
            with writer_lock(self._paths.import_lock):
                change()
        except LudexError as exc:
            self._notify(exc.message, True)
            return False
        return True

    def _group(self, title: str, hint: str = "") -> QFormLayout:
        box = QGroupBox(title)
        form = QFormLayout(box)
        if hint:
            form.addRow(QLabel(hint))
        self._layout.addWidget(box)
        return form

    def _switch(self, form: QFormLayout, text: str, on: bool, apply: Callable[[bool], None]) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(on)
        box.toggled.connect(apply)
        form.addRow(box)
        return box

    def _build(self) -> None:
        library = self._group("Library")
        self.auto_refresh = self._switch(library, "Import every account when ludex starts (stores are asked; turn off when offline)", get_auto_refresh(self._conn), lambda on: self._write(lambda: set_auto_refresh(self._conn, on)))
        self.auto_details = self._switch(library, "Fetch details for the selected game (the store sees its id)", get_auto_details(self._conn), lambda on: self._write(lambda: set_auto_details(self._conn, on)))
        self.auto_match = self._switch(library, "Match games no store describes by name (sends the folder name to the database plugin)", get_auto_match(self._conn), lambda on: self._write(lambda: set_auto_match(self._conn, on)))

        prefix = self._group("Default prefix folder", "Each game gets its own prefix inside it. Blank resets.")
        self.prefix = QLineEdit(str(get_prefix_root(self._conn, self._default_prefix)))
        browse, save = QPushButton("Browse…"), QPushButton("Save")
        browse.clicked.connect(self._browse)
        save.clicked.connect(self._save_prefix)
        row = QHBoxLayout()
        for widget in (self.prefix, browse, save):
            row.addWidget(widget)
        prefix.addRow(row)

        sources = self._group("Sources")
        self.sources: dict[str, QCheckBox] = {}
        for key, text in SOURCE_LABELS.items():
            self.sources[key] = self._switch(sources, text, get_switch(self._paths, key), lambda on, k=key: self._set_source(k, on))

        plugins = list_plugins()
        form = self._group("Plugins", "Enabling or disabling applies the next time ludex starts. Add plugins with: ludex plugin add <git link or package>" if plugins else "No plugins installed. Add one with: ludex plugin add <git link or package>")
        self.plugins: dict[str, QCheckBox] = {}
        for plugin in plugins:
            self.plugins[plugin["name"]] = self._switch(form, f"{plugin['name']} {plugin['version']}  ({', '.join(plugin['providers'])})", plugin["enabled"], lambda on, n=plugin["name"]: self._set_plugin(n, on))

        for plugin in sorted(self._sources.values(), key=lambda p: p.name):
            if plugin.settings:
                values = get_values(self._paths, plugin.name)
                self._fields(f"{plugin.name} settings", plugin.settings, values, lambda put, drop, p=plugin: self._save_plugin(p, put, drop), "")
        accounts = [(f"{source}:{name}", source) for name, source in list_accounts(self._paths) if source in self._sources]
        for ref, source in accounts:
            provider = self._sources[source]
            config = get_account(self._paths, ref).config
            self._fields(ref, provider.config_fields, config, lambda put, drop, r=ref, p=provider: self._save_account(r, p, put, drop), "Save, then run 'ludex import' to pick up the change.")

    def _fields(self, title: str, fields: tuple[ConfigField, ...], values: Mapping[str, str], save: Callable[..., None], hint: str) -> None:
        form = self._group(title, hint)
        editors = []
        for field in fields:
            editor = _Field(field, values.get(field.name))
            editors.append(editor)
            form.addRow(f"{field.name}" + (" (optional)" if field.optional else ""), editor.widget)
        button = QPushButton("Save")
        button.clicked.connect(lambda: self._save_fields(editors, save))
        form.addRow(button)

    def _save_fields(self, editors: list[_Field], save: Callable[[dict[str, str], list[str]], None]) -> None:
        put: dict[str, str] = {}
        drop: list[str] = []
        for editor in editors:
            if not editor.changed():
                continue
            text = editor.text()
            if isinstance(editor.widget, QCheckBox) or text:
                put[editor.field.name] = text
            else:
                drop.append(editor.field.name)
        if (put or drop) and self._write(lambda: save(put, drop)):
            self._notify("saved", False)
            for editor in editors:
                editor.remember()

    def _save_plugin(self, plugin: Provider, put: dict[str, str], drop: list[str]) -> None:
        for name, text in put.items():
            set_value(self._paths, plugin, name, text)
        for name in drop:
            set_value(self._paths, plugin, name, None)

    def _save_account(self, ref: str, plugin: Provider, put: dict[str, str], drop: list[str]) -> None:
        update_account(self._paths, ref, plugin.config_fields, put, drop)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Default prefix folder", self.prefix.text())
        if folder:
            self.prefix.setText(folder)

    def _save_prefix(self) -> None:
        text = self.prefix.text().strip()
        if self._write(lambda: set_prefix_root(self._conn, text or None)):
            shown = str(get_prefix_root(self._conn, self._default_prefix))
            self.prefix.setText(shown)
            self._notify(f"prefix folder: {shown}", False)

    def _set_source(self, key: str, on: bool) -> None:
        count: list[int] = []
        if self._write(lambda: count.append(set_switch(self._paths, self._conn, self._sources, key, on))):
            self._notify(f"{SOURCE_LABELS[key]}: {'added ' + str(count[0]) + ' games' if on else 'removed ' + str(count[0]) + ' records'}", False)
            self._changed()
            return
        box = self.sources[key]  # the change failed: show what is true
        box.blockSignals(True)
        box.setChecked(get_switch(self._paths, key))
        box.blockSignals(False)

    def _set_plugin(self, name: str, on: bool) -> None:
        try:
            set_plugin_enabled(name, on)
        except LudexError as exc:
            self._notify(exc.message, True)
            return
        self._notify(f"{'enabled' if on else 'disabled'} {name}; restart ludex to apply", False)
