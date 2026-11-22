"""The ludex desktop launcher (Qt Quick): a sidebar, a cover-art library grid, game pages, search, jobs, settings
and one sidebar page per plugin view.

Like the TUI it only collects input, calls the core and shows results. ``backend.py`` bridges the core to QML;
the screens are the files under ``qml/``.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
import sqlite3

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from ludex.accounts import get_account
from ludex.installed import installed_keys
from ludex.loader import load_providers
from ludex.paths import StatePaths, state_paths
from ludex.playtime import Played, play_stats
from ludex.plugins import Provider

from . import desktop
from .backend import Backend
from .gamepad import Gamepad, open_sdl_source

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
    console: bool = False,
) -> Launcher:
    """Build the backend and load the window without running the event loop; ``console`` opens it fullscreen with controller hints."""
    QQuickStyle.setStyle("Basic")
    backend = Backend(paths, sources, installed, config_for, played, prefix_root)
    engine = QQmlApplicationEngine()
    warnings: list[str] = []
    engine.warnings.connect(lambda found: warnings.extend(w.toString() for w in found))
    engine.rootContext().setContextProperty("backend", backend)
    engine.rootContext().setContextProperty("consoleMode", console)
    engine.load(QUrl.fromLocalFile(str(QML_DIR / "Main.qml")))
    backend.reload()
    return Launcher(engine, backend, warnings)


CONSOLE_SCALE = "1.25"


def console_environment(env: MutableMapping[str, str]) -> bool:
    """Make everything a little larger for a couch distance, unless the user set a scale; True when it did."""
    if "QT_SCALE_FACTOR" in env:
        return False
    env["QT_SCALE_FACTOR"] = CONSOLE_SCALE
    return True


def restart_command(console: bool) -> list[str]:
    """The command that starts this launcher again in the other mode (the same interpreter, so the same environment)."""
    code = "import sys; from ludex_gui.app import main; sys.exit(main(sys.argv[1:]))"
    return [sys.executable, "-c", code, *(["--console"] if console else [])]


def restart_environment(env: Mapping[str, str], scale_set_here: bool) -> dict[str, str]:
    """The environment for the restart: without the console scale this process added, which desktop mode must not inherit."""
    kept = dict(env)
    if scale_set_here:
        kept.pop("QT_SCALE_FACTOR", None)
    return kept


def main(argv: Sequence[str] | None = None) -> int:
    """Run the launcher on the user's library; ``ludex gui`` and the ``ludex-gui`` script land here.

    ``--console`` opens it fullscreen and larger, for a controller on a TV or a handheld.
    """
    parser = argparse.ArgumentParser(prog="ludex-gui", description="the ludex desktop launcher")
    parser.add_argument("--console", action="store_true", help="fullscreen and larger, for a controller on a TV or a handheld")
    parser.add_argument("--install-desktop", action="store_true", help="add Ludex and Ludex Console to the application menu, then exit")
    parser.add_argument("--uninstall-desktop", action="store_true", help="remove them from the application menu again, then exit")
    args = parser.parse_args(argv)
    if args.install_desktop or args.uninstall_desktop:
        files = desktop.manage(args.install_desktop, os.environ, Path.home())
        print("\n".join(f"{'wrote' if args.install_desktop else 'removed'} {path}" for path in files))
        return 0
    scale_set_here = console_environment(os.environ) if args.console else False
    sources, _ = load_providers()
    paths = state_paths()
    previous_umask = os.umask(0o077)
    try:
        app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
        app.setApplicationName("ludex")
        app.setDesktopFileName(desktop.ICON)
        app.setWindowIcon(QIcon(str(resources.files("ludex_gui") / "assets" / "ludex.svg")))
        launcher = build_engine(
            paths, sources, lambda: installed_keys(paths, sources)[0],
            lambda store, account: get_account(paths, f"{store}:{account}").config,
            lambda conn: play_stats(paths, sources, conn)[0],
            paths.root / "prefixes", args.console,
        )
        if launcher.window is None:
            return 1
        source = open_sdl_source()
        gamepad = Gamepad(launcher.window, source) if source is not None else None
        if source is None and args.console:
            launcher.backend.notify('no controller support: install it with  uv tool install ludex-games --with "ludex-gui[gamepad]"', True)
        if gamepad is not None:
            gamepad.start()
        launcher.backend.autoRefresh()
        code = app.exec()
        if gamepad is not None:
            gamepad.close()
        launcher.backend.closeDown()
    finally:
        os.umask(previous_umask)
    if launcher.backend.requested_console is not None:
        command = restart_command(launcher.backend.requested_console)
        os.execve(command[0], command, restart_environment(os.environ, scale_set_here))
    return code
