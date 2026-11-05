from __future__ import annotations

from ludex.loader import load_providers
from ludex.plugins import API_VERSION, Provider


def _plugin(name: str = "demo", **overrides: object) -> Provider:
    return Provider(name=name, help="demo", config_fields=(), fetch=lambda config: [], **overrides)  # type: ignore[arg-type]


class _Entry:
    def __init__(self, name: str, value: object = None, error: BaseException | None = None) -> None:
        self.name = name
        self.value = value
        self.error = error
        self.loads = 0

    def load(self) -> object:
        self.loads += 1
        if self.error is not None:
            raise self.error
        return self.value


def test_valid_plugin_is_loaded() -> None:
    plugin = _plugin()
    loaded, problems = load_providers([_Entry("demo", plugin)])  # type: ignore[list-item]
    assert loaded == {"demo": plugin}
    assert problems == {}


def test_broken_import_is_skipped_and_named_without_message() -> None:
    broken = _Entry("broken", error=ImportError("secret-token-123"))
    good = _Entry("good", _plugin("good"))
    loaded, problems = load_providers([broken, good])  # type: ignore[list-item]
    assert set(loaded) == {"good"}
    assert problems == {"broken": "failed to import (ImportError)"}
    assert "secret-token-123" not in repr(problems)


def test_system_exit_during_import_is_contained() -> None:
    loaded, problems = load_providers([_Entry("quit", error=SystemExit("boom"))])  # type: ignore[list-item]
    assert loaded == {}
    assert problems == {"quit": "failed to import (SystemExit)"}


def test_duplicate_names_are_rejected_without_importing() -> None:
    first = _Entry("dup", _plugin("dup"))
    second = _Entry("dup", _plugin("dup"))
    loaded, problems = load_providers([first, second])  # type: ignore[list-item]
    assert loaded == {}
    assert problems == {"dup": "registered more than once"}
    assert first.loads == 0 and second.loads == 0


def test_wrong_type_is_rejected() -> None:
    loaded, problems = load_providers([_Entry("fake", object())])  # type: ignore[list-item]
    assert loaded == {}
    assert problems == {"fake": "must be a Provider"}


def test_wrong_api_version_is_rejected() -> None:
    entry = _Entry("old", _plugin("old", api_version=API_VERSION + 1))
    loaded, problems = load_providers([entry])  # type: ignore[list-item]
    assert loaded == {}
    assert problems == {"old": f"unsupported api_version (ludex requires {API_VERSION})"}


def test_invalid_name_is_rejected_without_importing() -> None:
    entry = _Entry("Bad Name", _plugin())
    loaded, problems = load_providers([entry])  # type: ignore[list-item]
    assert loaded == {}
    assert list(problems.values()) == ["invalid extension name"]
    assert entry.loads == 0


def test_default_entry_points_come_from_group(monkeypatch) -> None:
    seen: list[str] = []

    def fake_entry_points(*, group: str) -> list[_Entry]:
        seen.append(group)
        return [_Entry("demo", _plugin())]

    monkeypatch.setattr("ludex.loader._entry_points", fake_entry_points)
    loaded, problems = load_providers()
    assert seen == ["ludex.providers"]
    assert set(loaded) == {"demo"} and problems == {}


def test_provider_without_any_capability_is_rejected():
    empty = Provider(name="empty", help="x", config_fields=())
    loaded, problems = load_providers([_Entry("empty", empty)])
    assert loaded == {} and problems == {"empty": "declares no capability"}


def test_invalid_plugin_settings_are_rejected():
    from ludex.plugins import ConfigField

    cases = [
        ((ConfigField("Bad-Name", "x"),), ()),
        ((ConfigField("a", "x"), ConfigField("a", "y")), ()),
        ((ConfigField("shared", "x"),), (ConfigField("shared", "y"),)),
        (("not a field",), ()),
    ]
    for settings, fields in cases:
        plugin = Provider(name="demo", help="d", config_fields=fields, fetch=lambda c: [], settings=settings)  # type: ignore[arg-type]
        loaded, problems = load_providers([_Entry("demo", plugin)])
        assert loaded == {} and "invalid settings" in problems["demo"], settings


def test_valid_plugin_settings_load():
    from ludex.plugins import ConfigField

    plugin = _plugin(settings=(ConfigField("region", "r", optional=True),))
    assert load_providers([_Entry("demo", plugin)])[0] == {"demo": plugin}
