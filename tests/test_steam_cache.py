from __future__ import annotations

import struct

from ludex.sources.steam import PLUGIN
from ludex.sources.steam_cache import cached_games


def _s(key: str, value: str) -> bytes:
    return b"\x01" + key.encode() + b"\0" + value.encode() + b"\0"


def _i(key: str, value: int) -> bytes:
    return b"\x02" + key.encode() + b"\0" + struct.pack("<i", value)


def _d(key: str, body: bytes) -> bytes:
    return b"\x00" + key.encode() + b"\0" + body + b"\x08"


def _packageinfo(packages: dict[int, list[int]], magic: int = 0x06565528) -> bytes:
    out = struct.pack("<II", magic, 1)
    for package, apps in packages.items():
        entry = _d(str(package), _d("appids", b"".join(_i(str(n), a) for n, a in enumerate(apps)))) + b"\x08"
        out += struct.pack("<I", package) + b"\0" * 32 + entry
    return out + struct.pack("<I", 0xFFFFFFFF)


def _appinfo(apps: dict[int, tuple[str, str]], magic: int = 0x07564429) -> bytes:
    strings = ["appinfo", "common", "type", "name"]
    key = {s: struct.pack("<I", i) for i, s in enumerate(strings)}

    def sval(name: str, value: str) -> bytes:
        return b"\x01" + key[name] + value.encode() + b"\0"

    body = b""
    for app_id, (kind, name) in apps.items():
        kv = b"\x00" + key["appinfo"] + b"\x00" + key["common"] + sval("type", kind) + sval("name", name) + b"\x08\x08\x08"
        payload = b"\0" * 60 + kv
        body += struct.pack("<II", app_id, len(payload)) + payload
    body += struct.pack("<II", 0, 0)
    table = struct.pack("<I", len(strings)) + b"".join(s.encode() + b"\0" for s in strings)
    return struct.pack("<IIQ", magic, 1, 16 + len(body)) + body + table


def _steam(tmp_path, packages=None, apps=None, **magics):
    (tmp_path / "steamapps").mkdir(parents=True)
    cache = tmp_path / "appcache"
    cache.mkdir()
    (cache / "packageinfo.vdf").write_bytes(_packageinfo(packages or {}, **({"magic": magics["pkg"]} if "pkg" in magics else {})))
    (cache / "appinfo.vdf").write_bytes(_appinfo(apps or {}, **({"magic": magics["app"]} if "app" in magics else {})))
    return tmp_path


def test_cached_games_keeps_only_licensed_games(tmp_path):
    steam = _steam(
        tmp_path,
        {1: [10, 11], 2: [30]},
        {10: ("Game", "Alpha"), 11: ("DLC", "Alpha DLC"), 30: ("game", "Gamma"), 99: ("Game", "Not licensed")},
    )
    assert cached_games(steam) == {10: "Alpha", 30: "Gamma"}


def test_unknown_format_or_missing_cache_yields_nothing(tmp_path):
    assert cached_games(tmp_path) == {}
    steam = _steam(tmp_path / "a", {1: [10]}, {10: ("Game", "Alpha")}, app=0x07564428)
    assert cached_games(steam) == {}
    (steam / "appcache" / "packageinfo.vdf").write_bytes(b"\x28\x55\x56\x06" + b"\x01")
    assert cached_games(steam) == {}


def test_local_mode_merges_cache_with_installed(tmp_path):
    steam = _steam(tmp_path, {1: [10, 20, 1493710]}, {10: ("Game", "Alpha"), 20: ("Game", "Beta"), 1493710: ("Game", "Proton 9")})
    (steam / "steamapps" / "appmanifest_10.acf").write_text('"AppState"\n{\n"appid" "10"\n"name" "Alpha"\n}\n')
    result = PLUGIN.fetch({"steam_dir": str(steam)})
    games = {g.store_id: g.extra for g in result.games}
    assert games == {"10": {"installed": True}, "20": {"installed": False}}
    assert result.complete is False
