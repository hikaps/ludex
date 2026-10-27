from __future__ import annotations

import asyncio

import pytest

from ludex import accounts, provider_settings
from ludex.errors import LudexError
from ludex.loader import _valid_settings
from ludex.paths import StatePaths
from ludex.plugins import ConfigField, FetchResult, Provider
from ludex.tui import LudexApp
from ludex.storage import connect
from textual.widgets import Select, Switch

YN = ConfigField("fast", "go fast", kind="yes_no", optional=True)
CH = ConfigField("region", "where", kind="choice", choices=("eu", "us"), optional=True)


def paths(tmp_path):
    tmp_path.chmod(0o700)
    return StatePaths(tmp_path, tmp_path / "library.sqlite3", tmp_path / "accounts.json", tmp_path / "import.lock")


def plugin(**kw):
    return Provider("p", "x", (ConfigField("name", "n"), ), lambda c: FetchResult([], True, None), **kw)


@pytest.mark.parametrize("given,stored", [("YES", "yes"), (" on ", "yes"), ("0", "no"), ("False", "no")])
def test_yes_no_values_are_stored_as_yes_or_no(given, stored):
    assert YN.clean(given) == stored


def test_a_bad_yes_no_or_choice_value_is_refused_and_not_stored(tmp_path):
    p = plugin(settings=(YN, CH))
    ps = paths(tmp_path)
    with pytest.raises(LudexError, match="yes or no"):
        provider_settings.set_value(ps, p, "fast", "maybe")
    with pytest.raises(LudexError, match="one of: eu, us"):
        provider_settings.set_value(ps, p, "region", "asia")
    assert provider_settings.get_values(ps, "p") == {}
    provider_settings.set_value(ps, p, "fast", "True")
    provider_settings.set_value(ps, p, "region", "eu")
    assert provider_settings.get_values(ps, "p") == {"fast": "yes", "region": "eu"}


def test_account_fields_are_validated_the_same_way(tmp_path):
    ps = paths(tmp_path)
    accounts.add_account(ps, "main", "p", {"name": "n"})
    with pytest.raises(LudexError, match="yes or no"):
        accounts.update_account(ps, "p:main", (YN,), {"fast": "x"})
    accounts.update_account(ps, "p:main", (YN,), {"fast": "off"})
    assert accounts.get_account(ps, "p:main").config["fast"] == "no"


@pytest.mark.parametrize("bad", [
    ConfigField("a", "h", kind="choice"),  # no choices
    ConfigField("a", "h", kind="choice", choices=("x", "x")),
    ConfigField("a", "h", kind="text", choices=("x",)),
    ConfigField("a", "h", kind="switch"),
    ConfigField("a", "h", kind="yes_no", secret=True),
])
def test_the_loader_rejects_malformed_kinds(bad):
    assert not _valid_settings(plugin(settings=(bad,)))
    assert _valid_settings(plugin(settings=(YN, CH)))


def test_settings_tab_shows_a_switch_and_a_dropdown_and_saves_them(tmp_path):
    ps = paths(tmp_path)
    connect(ps.database).close()
    p = plugin(settings=(YN, CH))

    async def scenario():
        app = LudexApp(ps.database, {"p": p}, paths=ps)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            switch = next(w for w in app.query(Switch) if w.id in app._fields)
            select = app.query_one(Select)
            switch.value = True
            select.value = "us"
            await pilot.pause()

    asyncio.run(scenario())
    assert provider_settings.get_values(ps, "p") == {"fast": "yes", "region": "us"}
