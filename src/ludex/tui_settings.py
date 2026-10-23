"""Terminal forms for per-game launch settings and the default prefix folder.

Path fields complete from the file system: the grey suggestion is accepted with Tab or Right.
ponytail: one suggestion at a time (the first match, no cycling) and runners are chosen from the
detected list only; add cycling or a free path when that gets in the way.
"""
from __future__ import annotations

import shlex
from collections.abc import Callable
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from .errors import LudexError
from .game_settings import GameSettings
from .runners import Runner


class PathSuggester(Suggester):
    """Completes the last path component from the entries of its folder (directories get a ``/``)."""

    def __init__(self, base: Path | None = None, dirs_only: bool = False) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self._base = base
        self._dirs_only = dirs_only

    async def get_suggestion(self, value: str) -> str | None:
        if not value:
            return None
        folder_text, _, typed = value.rpartition("/")
        folder = Path(folder_text + "/" if value.startswith("/") and not folder_text else folder_text or ".").expanduser()
        if not folder.is_absolute() and self._base is not None:
            folder = self._base / folder
        try:
            entries = sorted(folder.iterdir(), key=lambda e: e.name)
        except OSError:
            return None
        for entry in entries:
            if entry.name.startswith(typed) and entry.name != typed and (typed.startswith(".") or not entry.name.startswith(".")):
                if entry.is_dir():
                    return value[: len(value) - len(typed)] + entry.name + "/"
                if not self._dirs_only:
                    return value[: len(value) - len(typed)] + entry.name
        return None


class PathInput(Input):
    BINDINGS = [Binding("tab", "complete", show=False)]

    def action_complete(self) -> None:
        before = self.value
        self.cursor_position = len(before)
        self.action_cursor_right()  # accepts the grey suggestion when the cursor is at the end
        if self.value == before:
            self.screen.focus_next()


class _Form(ModalScreen[None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel"), Binding("ctrl+s", "save", "Save")]
    DEFAULT_CSS = """
    _Form { align: center middle; }
    #form { width: 80%; max-width: 100; height: auto; max-height: 90%; border: thick $primary; background: $surface; padding: 1 2; }
    #form-error { color: $error; height: auto; }
    #buttons { height: auto; margin-top: 1; }
    TextArea { height: 6; }
    """

    def __init__(self, heading: str, save: Callable[[], None]) -> None:
        super().__init__()
        self._heading = heading
        self._apply = save

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        try:
            self._apply()
        except LudexError as exc:
            self.query_one("#form-error", Static).update(exc.message)
            return
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_save() if event.button.id == "save" else self.action_cancel()

    def _buttons(self) -> ComposeResult:
        yield Static("", id="form-error")
        with Horizontal(id="buttons"):
            yield Button("Save (ctrl+s)", id="save", variant="primary")
            yield Button("Cancel (esc)", id="cancel")


class GameSettingsScreen(_Form):
    """Edit one game's runner, prefix, executable, arguments and environment."""

    AUTO_FOCUS = "#runner"

    def __init__(
        self,
        title: str,
        current: GameSettings,
        runners: list[Runner],
        default_prefix: Path,
        game_folder: Path | None,
        save: Callable[[dict], None],
    ) -> None:
        super().__init__(f"Launch settings: {title}", lambda: save(self._values()))
        self._current = current
        self._runners = runners
        self._default_prefix = default_prefix
        self._game_folder = game_folder

    def compose(self) -> ComposeResult:
        options = [(r.name, r.name) for r in self._runners]
        if self._current.runner and self._current.runner not in {value for _, value in options}:
            options.append((self._current.runner, self._current.runner))
        with VerticalScroll(id="form"):
            yield Label(self._heading)
            yield Label("Runner (Proton build; blank runs the executable natively)")
            yield Select(options, value=self._current.runner or Select.NULL, allow_blank=True, id="runner")
            yield Label(f"Prefix folder (blank: {self._default_prefix}/<game>)")
            yield PathInput(self._current.prefix or "", suggester=PathSuggester(dirs_only=True), id="prefix")
            yield Label("Executable (relative to the game folder or absolute; blank: automatic)")
            yield PathInput(self._current.executable or "", suggester=PathSuggester(self._game_folder), id="executable")
            yield Label("Arguments")
            yield Input(shlex.join(self._current.args), id="args")
            yield Label("Environment variables, one NAME=VALUE per line")
            yield TextArea("\n".join(f"{k}={v}" for k, v in self._current.env.items()), id="env")
            yield from self._buttons()

    def _values(self) -> dict:
        env: dict[str, str] = {}
        for line in self.query_one("#env", TextArea).text.splitlines():
            if line.strip():
                name, sep, value = line.partition("=")
                if not sep:
                    raise LudexError("invalid_setting", f"environment line needs NAME=VALUE: {line.strip()[:40]}")
                env[name.strip()] = value
        try:
            args = shlex.split(self.query_one("#args", Input).value)
        except ValueError:
            raise LudexError("invalid_setting", "the arguments have unbalanced quotes") from None
        runner = self.query_one("#runner", Select).value
        return {
            "runner": runner if isinstance(runner, str) else None,
            "prefix": self.query_one("#prefix", Input).value.strip() or None,
            "executable": self.query_one("#executable", Input).value.strip() or None,
            "args": args,
            "env": env,
        }


class SettingsScreen(_Form):
    """Global settings (today: the folder default prefixes are created in)."""

    AUTO_FOCUS = "#folder"

    def __init__(self, current: Path, default: Path, save: Callable[[str | None], None]) -> None:
        super().__init__("Settings", lambda: save(self.query_one("#folder", Input).value.strip() or None))
        self._current = current
        self._default = default

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="form"):
            yield Label(self._heading)
            yield Label(f"Default prefix folder: each game gets its own prefix inside it. Blank resets to {self._default}")
            yield PathInput(str(self._current), suggester=PathSuggester(dirs_only=True), id="folder")
            yield from self._buttons()
