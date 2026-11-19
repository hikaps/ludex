from __future__ import annotations

import asyncio
import threading

from textual.widgets import DataTable, Static, Tabs

from ludex.errors import LudexError
from ludex.paths import StatePaths
from ludex.plugins import Command, CommandResult, Provider, View, ViewAction, ViewDetail, ViewRow, ViewTable
from ludex_tui.app import LudexApp
from ludex_tui.view_actions import ViewActionsScreen


async def _until(pilot, check, tries: int = 200) -> None:
    for _ in range(tries):
        if check():
            return
        await pilot.pause(0.05)
    raise AssertionError("timed out")


def _detail(app: LudexApp) -> str:
    return str(app.query_one("#detail", Static).visual.plain)


def _world(tmp_path):
    root = tmp_path / "home"
    root.mkdir(mode=0o700)
    paths = StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")
    marker = tmp_path / "marker"
    fetched = {"people": 0, "status": 0}
    gate = threading.Event()

    def mark(ctx, args):
        marker.write_text(" ".join(args))
        return CommandResult(None, "marked [b]alice[/b]")

    def people(settings):
        fetched["people"] += 1
        state = marker.read_text().split()[-1] if marker.exists() else "online"
        return ViewTable(("Name", "State"), (ViewRow("alice", ("Alice", state), (ViewAction("Mark away", "mark", ("alice", "away")),)),))

    def status(settings):
        fetched["status"] += 1
        return ViewDetail((("State", "Ready"),))

    def flaky(settings):
        gate.wait(5)
        raise LudexError("rate_limited", "try later")

    provider = Provider(
        "demo", "Demo", (),
        commands=(Command("mark", "mark", mark),),
        views=(View("people", "People", people), View("status", "Status", status), View("flaky", "Flaky [b]", flaky)),
    )
    app = LudexApp(paths.database, {"demo": provider}, paths=paths, lock=paths.import_lock)
    return app, marker, fetched, gate


def test_a_view_fetches_on_first_visit_and_an_action_needs_a_confirmed_choice(tmp_path):
    app, marker, fetched, _ = _world(tmp_path)

    async def scenario():
        async with app.run_test() as pilot:
            assert fetched == {"people": 0, "status": 0}  # nothing is fetched at startup
            await pilot.press("s", "tab")
            assert app.query_one(Tabs).active == "view-demo_people"
            table = app.query_one("#view-demo_people-table", DataTable)
            await _until(pilot, lambda: table.row_count == 1)
            assert [str(c) for c in table.get_row("alice")] == ["Alice", "online"]
            await _until(pilot, lambda: "Enter: actions" in _detail(app))
            assert fetched == {"people": 1, "status": 0}

            await pilot.press("enter")  # opening the chooser runs nothing, and Esc leaves it
            assert isinstance(app.screen, ViewActionsScreen)
            assert app.screen.query_one("#view-actions-run").disabled
            await pilot.press("escape")
            assert not isinstance(app.screen, ViewActionsScreen) and not marker.exists()

            await pilot.press("enter")  # choosing is not confirming: Cancel still runs nothing
            await pilot.press("enter")
            assert not app.screen.query_one("#view-actions-run").disabled
            await pilot.click("#view-actions-cancel")
            await pilot.pause()
            assert not isinstance(app.screen, ViewActionsScreen) and not marker.exists()

            await pilot.press("enter", "enter", "enter")  # open, choose, Run
            await _until(pilot, lambda: marker.exists() and [str(c) for c in table.get_row("alice")] == ["Alice", "away"])
            assert marker.read_text() == "alice away"
            assert fetched["people"] == 2  # a successful action fetches the view again
            assert any(n.message == "marked [b]alice[/b]" and not n.markup for n in app._notifications)  # plugin text is not markup
            assert app.query_one("#view-demo_flaky").label.plain == "Flaky [b]"

    asyncio.run(scenario())


def test_reload_refreshes_only_the_shown_view_and_a_slow_failure_never_lands_on_another_tab(tmp_path):
    app, marker, fetched, gate = _world(tmp_path)

    async def scenario():
        async with app.run_test() as pilot:
            await pilot.press("s", "tab", "tab")
            assert app.query_one(Tabs).active == "view-demo_status"
            await _until(pilot, lambda: app.query_one("#view-demo_status-table", DataTable).row_count == 1)
            assert fetched == {"people": 1, "status": 1}  # the People tab was visited on the way and fetched once
            await pilot.press("r")
            await _until(pilot, lambda: fetched["status"] == 2)
            assert fetched["people"] == 1  # r refreshed the shown view only

            await pilot.press("tab")  # the slow view starts and is still waiting when we leave
            assert app.query_one(Tabs).active == "view-demo_flaky"
            await _until(pilot, lambda: "Loading" in _detail(app))
            await pilot.press("shift+tab")
            assert app.query_one(Tabs).active == "view-demo_status"
            gate.set()
            await _until(pilot, lambda: app._views["view-demo_flaky"].error is not None)
            await pilot.pause()
            assert "try later" not in _detail(app) and "Status" in _detail(app)

            await pilot.press("tab")
            assert "try later" in _detail(app) and "Press r to retry" in _detail(app)

    asyncio.run(scenario())
