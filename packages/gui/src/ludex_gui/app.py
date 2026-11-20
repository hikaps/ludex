"""The ludex desktop launcher (Qt Quick): a sidebar, a cover-art library grid, game pages, search, jobs, settings
and one sidebar page per plugin view.

Like the TUI it only collects input, calls the core and shows results. ``backend.py`` bridges the core to QML;
the screens are the files under ``qml/``.
"""
from __future__ import annotations

import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import sqlite3

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ludex.accounts import get_account
from ludex.installed import installed_keys
from ludex.loader import load_providers
from ludex.paths import StatePaths, state_paths
from ludex.playtime import Played, play_stats
from ludex.plugins import Provider

from .backend import Backend

QML_DIR = Path(__file__).with_name("qml")


@dataclass(frozen=True, slots=True)
class Launcher:
    """A loaded launcher: the engine, its backend and the QML warnings seen while loading."""

    engine: QQmlApplicationEngine
    backend: Backend
    warnings: list[str]

    @property
    def window(self) -> QObject | None:
        roots = self.engine.rootObjects()
        return roots[0] if roots else None


def build_engine(
    paths: StatePaths,
    sources: Mapping[str, Provider],
    installed: Callable[[], set[tuple[str, str]]],
    config_for: Callable[[str, str], Mapping[str, str]],
    played: Callable[[sqlite3.Connection], Mapping[int, Played]],
    prefix_root: Path,
) -> Launcher:
    """Build the backend and load the window without running the event loop."""
    QQuickStyle.setStyle("Basic")
    backend = Backend(paths, sources, installed, config_for, played, prefix_root)
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda found: warnings.extend(w.toString() for w in found))
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    backend.reload()
    return Launcher(engine, backend, warnings)


def main() -> int:
    """Run the launcher on the user's library; ``ludex gui`` and the ``ludex-gui`` script land here."""
    sources, _ = load_providers()
    paths = state_paths()
    previous_umask = os.umask(0o077)
    try:
        app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        app.setApplicationName("ludex")
        launcher = build_engine(
            paths, sources, lambda: installed_keys(paths, sources)[0],
            lambda store, account: get_account(paths, f"{store}:{account}").config,
            lambda conn: play_stats(paths, sources, conn)[0],
            paths.root / "prefixes",
        )
        if launcher.window is None:
            return 1
        launcher.backend.autoRefresh()
        code = app.exec()
        launcher.backend.closeDown()
    finally:
        os.umask(previous_umask)
    return code
