from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from textual.app import App

from ludex.tui import LudexApp


@pytest.fixture(autouse=True)
def _wait_for_the_screen_to_mount(monkeypatch):
    """run_test can hand back the pilot before the main screen is composed (seen on slow CI)."""
    original = App.run_test

    @asynccontextmanager
    async def run_test(self, *args, **kwargs):
        async with original(self, *args, **kwargs) as pilot:
            if isinstance(self, LudexApp):
                for _ in range(200):
                    if self.query("#owned-table") and self.query("#settings-table"):
                        break
                    await pilot.pause(0.05)
                await pilot.pause()
            yield pilot

    monkeypatch.setattr(App, "run_test", run_test)
