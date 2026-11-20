from __future__ import annotations

from pathlib import Path

from ludex.executables import find_executables


def make(root: Path, files: dict[str, int]) -> None:
    for name, size in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)


def test_finds_the_game_first_and_leaves_out_installers_and_deep_or_hidden_files(tmp_path):
    make(tmp_path, {
        "Hades.exe": 10, "launcher.exe": 500, "unins000.exe": 900, "vcredist_x64.exe": 900, "UnityCrashHandler64.exe": 9,
        "bin/hades_dx.exe": 800, "start.sh": 1, "readme.txt": 1, ".hidden/x.exe": 5,
        "a/b/c/deep.exe": 5, "a/b/c/d/toodeep.exe": 5, "Game.AppImage": 7,
    })
    found = [str(p) for p in find_executables(tmp_path, "Hades")]
    assert found[0] == "Hades.exe"  # the title match leads its level, ahead of the bigger launcher.exe
    assert set(found) == {"Hades.exe", "launcher.exe", "start.sh", "Game.AppImage", "bin/hades_dx.exe", "a/b/c/deep.exe"}
    assert found.index("bin/hades_dx.exe") > found.index("start.sh")  # nearer the top comes first


def test_a_huge_folder_is_cut_off_and_limit_applies(tmp_path):
    make(tmp_path, {f"g{i}.exe": i + 1 for i in range(40)})
    assert len(find_executables(tmp_path, "", limit=30)) == 30
    assert str(find_executables(tmp_path, "", limit=1)[0]) == "g39.exe"  # bigger first when nothing else separates them
    assert find_executables(tmp_path / "missing") == []
