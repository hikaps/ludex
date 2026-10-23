from __future__ import annotations

import stat

import pytest

from ludex.accounts import add_account, get_account
from ludex.errors import LudexError
from ludex.paths import StatePaths
from ludex.plugins import ConfigField, Provider
from ludex.provider_settings import describe, get_values, set_value

PLUGIN = Provider("demo", "d", (), lambda c: [], settings=(ConfigField("region", "r", optional=True), ConfigField("token", "t", secret=True, optional=True)))


@pytest.fixture
def paths(tmp_path):
    root = tmp_path / "s"
    root.mkdir(mode=0o700)
    return StatePaths(root, root / "library.sqlite3", root / "accounts.json", root / "import.lock")


def test_set_describe_and_unset_hide_secrets_and_use_a_private_file(paths):
    set_value(paths, PLUGIN, "region", "eu")
    set_value(paths, PLUGIN, "token", "s3cret")
    assert get_values(paths, "demo") == {"region": "eu", "token": "s3cret"}
    assert describe(paths, PLUGIN) == {"region": "eu", "token": "(set)"}
    assert stat.S_IMODE((paths.root / "plugin-settings.json").stat().st_mode) == 0o600
    set_value(paths, PLUGIN, "region", None)
    set_value(paths, PLUGIN, "token", None)
    assert get_values(paths, "demo") == {} and describe(paths, PLUGIN) == {"region": None, "token": None}


def test_unknown_and_empty_settings_are_rejected(paths):
    for key, value in (("nope", "x"), ("region", " ")):
        with pytest.raises(LudexError):
            set_value(paths, PLUGIN, key, value)
    assert get_values(paths, "demo") == {}


def test_account_config_is_merged_over_plugin_settings(paths):
    add_account(paths, "a", "demo", {"region": "us", "user": "u"})
    set_value(paths, PLUGIN, "region", "eu")
    set_value(paths, PLUGIN, "token", "t")
    config = get_account(paths, "demo:a").config
    assert dict(config) == {"region": "us", "user": "u", "token": "t"}  # the account's own field wins


def test_update_account_sets_unsets_and_validates(paths):
    from ludex.accounts import update_account

    fields = (ConfigField("user", "u"), ConfigField("tag", "t", optional=True))
    add_account(paths, "a", "demo", {"user": "u1", "tag": "x"})
    assert update_account(paths, "a", fields, {"user": "u2"}, ["tag"]) == ["tag", "user"]
    assert dict(get_account(paths, "demo:a").config) == {"user": "u2"}
    for values, unset in (({"nope": "1"}, []), ({"user": ""}, []), ({}, ["user"])):
        with pytest.raises(LudexError):
            update_account(paths, "a", fields, values, unset)
    assert dict(get_account(paths, "demo:a").config) == {"user": "u2"}
