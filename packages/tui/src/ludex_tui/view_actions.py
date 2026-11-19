"""Pick and confirm one action a plugin view offers for a row."""
from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static

from ludex.plugins import ViewAction


class ViewActionsScreen(ModalScreen["int | None"]):
    """Select an action, then press Run; dismisses with its index, or None on cancel. Nothing runs here."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]
    DEFAULT_CSS = """
    ViewActionsScreen { align: center middle; }
    #view-actions { width: 70%; max-width: 80; height: auto; max-height: 90%; border: thick $primary; background: $surface; padding: 1 2; }
    #view-actions-list { height: auto; max-height: 10; margin: 1 0; }
    #view-actions-buttons { height: 3; }
    #view-actions-hint { color: $text-muted; }
    """

    def __init__(self, source: str, subject: str, actions: Sequence[ViewAction]) -> None:
        super().__init__()
        self._source = source
        self._subject = subject
        self._actions = tuple(actions)
        self._chosen: int | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="view-actions"):
            yield Static(Text(self._source, style="dim"))
            yield Static(Text(self._subject, style="bold"))
            yield OptionList(*(Text(f"{a.label}   ({a.command})") for a in self._actions), id="view-actions-list")
            yield Static("Choose an action with Enter, then Run. Esc cancels.", id="view-actions-hint")
            with Horizontal(id="view-actions-buttons"):
                yield Button("Run", id="view-actions-run", variant="primary", disabled=True)
                yield Button("Cancel", id="view-actions-cancel")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._chosen = event.option_index
        self.query_one("#view-actions-run", Button).disabled = False
        self.query_one("#view-actions-hint", Static).update(Text(f"Selected: {self._actions[event.option_index].label}. Press Run to confirm."))
        self.query_one("#view-actions-run", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        self.dismiss(self._chosen if event.button.id == "view-actions-run" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
