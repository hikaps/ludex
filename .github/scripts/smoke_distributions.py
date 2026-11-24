"""Install the built distributions the way users do and check what they get.

    python .github/scripts/smoke_distributions.py --mode stable --dist dist/stable
    python .github/scripts/smoke_distributions.py --mode beta --dist dist/beta --repository OWNER/ludex

``stable``: the eight artifacts of ``build_distributions.py`` act as a wheelhouse; core alone, CLI alone, the bundle with
uv and pipx (wheel and sdist), and a managed plugin that downloads a game.
``beta``: verifies the production artifacts (checksums, hash-pinned release URLs), rebuilds the same tree against a
loopback server, and installs ``/ludex.tar.gz`` from it with uv and pipx, fresh and reinstalled. Never publishes anything.
Run it from the checkout root with a Python that has ``build``, ``uv`` and ``pipx`` installed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_distributions import BUNDLE, BUNDLED, ROOT, metadata_of  # noqa: E402

BUILTINS = {"steam", "epic", "local", "shortcuts", "heroic", "rawg", "steamgriddb"}


def run(args, *, env=None, check=True, timeout=300, cwd=None):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, env=env, timeout=timeout, cwd=cwd)
    if check and result.returncode != 0:
        raise SystemExit(f"command failed ({result.returncode}): {' '.join(map(str, args))}\n{result.stdout}\n{result.stderr}")
    return result


def venv(path: Path) -> Path:
    run([sys.executable, "-m", "venv", path])
    return path / "bin" / "python"


class Scratch:
    """Isolated tool homes and state; nothing here touches the user's own."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="ludex-smoke-", dir="/tmp"))
        self.env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV", "LUDEX_HOME"}}
        for name, sub in {"UV_TOOL_DIR": "uv-tools", "UV_TOOL_BIN_DIR": "uv-bin", "UV_CACHE_DIR": "uv-cache", "PIPX_HOME": "pipx-home",
                          "PIPX_BIN_DIR": "pipx-bin", "PIPX_MAN_DIR": "pipx-man", "XDG_CONFIG_HOME": "xdg-config", "XDG_DATA_HOME": "xdg-data"}.items():
            (self.root / sub).mkdir()
            self.env[name] = str(self.root / sub)
        self.env["HOME"] = str(self.root)
        self.env["LUDEX_HOME"] = str(self.root / "ludex-state")
        self.env["TERM"] = "xterm-256color"
        self.env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), os.environ["PATH"]])

    def fresh_state(self, name: str) -> dict[str, str]:
        return {**self.env, "LUDEX_HOME": str(self.root / f"state-{name}")}

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def say(message: str) -> None:
    print(f"== {message}", flush=True)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


def installed_versions(python: Path, env) -> dict[str, str]:
    code = "import importlib.metadata as m\nfor n in ('ludex-core','ludex-cli','ludex-games','ludex-gui'):\n    try: print(n, m.version(n))\n    except m.PackageNotFoundError: pass\n"
    return dict(line.split() for line in run([python, "-I", "-c", code], env=env).stdout.splitlines())


FIXTURE = '''\
from pathlib import Path

from ludex.plugins import AcquireResult, FetchResult, Provider, View, ViewRow, ViewTable


def acquire(request, report):
    report("half", 1, 2)
    game = request.destination / "fixture-game"
    game.mkdir()
    (game / "run.sh").write_text("#!/bin/sh\\n")
    return AcquireResult(game, {"executable": "run.sh"})


def people(settings):
    return ViewTable(("Name", "State"), (ViewRow("alice", ("Alice", "online")),))


PLUGIN = Provider("fixture", "offline fixture", (), lambda context: FetchResult([], True, None), acquire=acquire, views=(View("people", "People", people),))
'''


def fixture_wheel(directory: Path, version: str) -> Path:
    """A plugin wheel that requires the core at exactly ``version`` and can acquire a game offline."""
    name = directory / "ludex_fixture-1.0-py3-none-any.whl"
    info = "ludex_fixture-1.0.dist-info"
    files = {
        "ludex_fixture.py": FIXTURE,
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: ludex-fixture\nVersion: 1.0\nRequires-Dist: ludex-core=={version}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: smoke\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        f"{info}/entry_points.txt": "[ludex.providers]\nfixture = ludex_fixture:PLUGIN\n",
    }
    with zipfile.ZipFile(name, "w") as wheel:
        for path, text in files.items():
            wheel.writestr(path, text)
        wheel.writestr(f"{info}/RECORD", "".join(f"{p},,\n" for p in files) + f"{info}/RECORD,,\n")
    return name


def wait_for(predicate, what: str, seconds: float = 60):
    deadline = time.time() + seconds
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.3)
    raise SystemExit(f"FAILED: timed out waiting for {what}")


def providers_of(binary: Path, env) -> tuple[set[str], dict]:
    data = json.loads(run([binary, "--json", "providers"], env=env).stdout)["data"]
    return {p["name"] for p in data["providers"]}, data["problems"]


def download_through_cli(binary: Path, env, scratch: Path) -> None:
    destination = scratch / "downloads"
    run([binary, "--json", "download", "fixture", "1", "--to", destination], env=env)
    jobs = lambda: json.loads(run([binary, "--json", "download", "--status"], env=env).stdout)["data"]["jobs"]  # noqa: E731
    job = wait_for(lambda: next((j for j in jobs() if j["state"] != "running"), None), "the download job")
    check(job["state"] == "done" and (destination / "fixture-game" / "run.sh").is_file(), f"download did not finish cleanly: {job}")
    check("half 50%" in Path(job["log"]).read_text(), "download log lacks the progress line")


def check_stable(dist: Path) -> None:
    wheels = {p.name.split("-")[0]: p for p in dist.glob("*.whl")}
    version = metadata_of(wheels["ludex_games"])["Version"]
    check(re.fullmatch(r"\d+\.\d+\.\d+", version) is not None, f"unexpected version {version}")
    scratch = Scratch()
    try:
        scratch.env |= {"PIP_FIND_LINKS": str(dist), "UV_FIND_LINKS": str(dist)}  # the wheelhouse also serves managed plugin installs
        env = scratch.env
        plugin = fixture_wheel(scratch.root, version)

        say("core alone: importable, no frontend, all built-in providers, offline download through a managed plugin")
        python = venv(scratch.root / "core-venv")
        run([python, "-m", "pip", "install", "-q", f"ludex-core=={version}"], env=env)
        code = (
            "import importlib.util as u, os, sys, time\nos.umask(0o077)\n"
            "import ludex.plugins, ludex.library, ludex.services\n"
            "assert all(u.find_spec(n) is None for n in ('ludex_cli', 'ludex_gui')), 'frontend installed'\n"
            "from ludex.loader import load_providers\n"
            "from ludex.plugin_manager import add_plugin\n"
            f"print(add_plugin({str(plugin)!r}))\n"
            "providers, problems = load_providers()\n"
            f"assert not problems and {sorted(BUILTINS | {'fixture'})!r} == sorted(providers), (providers, problems)\n"
            "from ludex.acquire import download_game\n"
            "from ludex.jobs import list_jobs\n"
            "from ludex.paths import state_paths\n"
            "from ludex.storage import connect\n"
            "from pathlib import Path\n"
            "paths = state_paths(); conn = connect(paths.database)\n"
            f"dest = Path({str(scratch.root / 'core-dl')!r})\n"
            "download_game(conn, providers, 'fixture', '1', 'Fixture', dest, paths.root / 'logs')\n"
            "end = time.time() + 60\n"
            "while time.time() < end and list_jobs(conn, 'download')[0].state == 'running': time.sleep(0.3)\n"
            "job = list_jobs(conn, 'download')[0]\n"
            "assert job.state == 'done' and (dest / 'fixture-game' / 'run.sh').is_file(), job\n"
            "assert 'half 50%' in job.log.read_text(), job.log.read_text()\n"
        )
        run([python, "-c", code], env=scratch.fresh_state("core"))

        say("CLI alone: no GUI")
        python = venv(scratch.root / "cli-venv")
        run([python, "-m", "pip", "install", "-q", f"ludex-cli=={version}"], env=env)
        binary = python.parent / "ludex"
        check(run([binary, "--version"], env=env).stdout.strip() == f"ludex {version}", "cli version")
        check(run([python, "-c", "import importlib.util as u; raise SystemExit(u.find_spec('ludex_gui') is not None)"]).returncode == 0, "the GUI was installed with the CLI")
        result = run([binary, "update"], env=scratch.fresh_state("cli"), check=False)
        check(result.returncode == 1 and "requires ludex-games" in result.stderr, f"standalone update: {result.stderr}")

        say("GUI without the CLI: ludex-gui loads its launcher offscreen")
        gui_python = venv(scratch.root / "gui-venv")
        run([gui_python, "-m", "pip", "install", "-q", f"ludex-gui=={version}"], env=env)
        check(not (gui_python.parent / "ludex").exists(), "ludex-gui must not provide the ludex command")
        check(run([gui_python, "-c", "import importlib.util as u; raise SystemExit(any(u.find_spec(n) is not None for n in ('ludex_cli',)))"]).returncode == 0, "the CLI came with ludex-gui")
        code = (
            "import os\nos.umask(0o077)\n"
            "from PySide6.QtCore import QObject\n"
            "from PySide6.QtGui import QGuiApplication\n"
            "app = QGuiApplication([])\n"
            "from ludex.loader import load_providers\n"
            "from ludex.paths import state_paths\n"
            "from ludex_gui.app import build_engine\n"
            "sources, _ = load_providers(); paths = state_paths()\n"
            "launcher = build_engine(paths, sources, lambda: set(), lambda s, a: {}, lambda c: {}, paths.root / 'prefixes')\n"
            "assert launcher.window is not None and not launcher.warnings, launcher.warnings\n"
            "for name in ('library', 'installed', 'search', 'jobs', 'settings'):\n"
            "    assert launcher.window.findChild(QObject, 'nav-' + name) is not None, name\n"
            "app.processEvents(); launcher.backend.closeDown()\n"
        )
        run([gui_python, "-c", code], env=scratch.fresh_state("gui") | {"QT_QPA_PLATFORM": "offscreen", "QT_QUICK_BACKEND": "software"})

        say("bundle with uv and pipx: wheel and sdist, one command, plugin download")
        sdist = next(dist.glob("ludex_games-*.tar.gz"))
        for label, source in (("wheel", wheels["ludex_games"]), ("sdist", sdist)):
            for tool in ("uv", "pipx"):
                bin_dir = Path(scratch.env["UV_TOOL_BIN_DIR" if tool == "uv" else "PIPX_BIN_DIR"])
                if tool == "uv":
                    run([sys.executable, "-m", "uv", "tool", "install", "--force", "--reinstall", "--python", sys.executable, source], env=env)
                    tool_python = Path(scratch.env["UV_TOOL_DIR"]) / "ludex-games" / "bin" / "python"
                else:
                    run([sys.executable, "-m", "pipx", "install", "--force", f"--pip-args=--find-links={dist}", "--python", sys.executable, source], env=env)
                    tool_python = Path(scratch.env["PIPX_HOME"]) / "venvs" / "ludex-games" / "bin" / "python"
                binary = bin_dir / "ludex"
                check([p.name for p in bin_dir.iterdir()] == ["ludex"], f"{tool} {label}: unexpected commands {[p.name for p in bin_dir.iterdir()]}")
                check(run([binary, "--version"], env=env).stdout.strip() == f"ludex {version}", f"{tool} {label} version")
                check(set(installed_versions(tool_python, env).values()) == {version} and len(installed_versions(tool_python, env)) == 3, f"{tool} {label} versions")
                names, problems = providers_of(binary, scratch.fresh_state(f"{tool}{label}"))
                check(names == BUILTINS and not problems, f"{tool} {label} providers {names} {problems}")
        state = scratch.fresh_state("bundle-plugin")
        run([binary, "plugin", "add", plugin], env=env | {"LUDEX_HOME": state["LUDEX_HOME"]})
        names, problems = providers_of(binary, state)
        check(names == BUILTINS | {"fixture"} and not problems, f"providers with plugin: {names} {problems}")
        download_through_cli(binary, state, scratch.root / "bundle-dl")
        shown = json.loads(run([binary, "--json", "plugin", "view", "fixture", "people"], env=state).stdout)["data"]
        check(shown["kind"] == "table" and shown["rows"] == [{"id": "alice", "cells": ["Alice", "online"], "actions": []}], f"plugin view: {shown}")
        missing = run([binary, "--json", "plugin", "view", "fixture", "nope"], env=state, check=False)
        check(missing.returncode == 1 and json.loads(missing.stderr)["error"]["code"] == "unknown_view", f"unknown view: {missing.stderr}")
        say("stable smoke passed")
    finally:
        scratch.close()


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


def read_sums(path: Path) -> dict[str, str]:
    entries = dict(line.split("  ", 1)[::-1] for line in path.read_text().splitlines())
    return entries


def verify_production(dist: Path, repository: str) -> str:
    sums = read_sums(dist / "SHA256SUMS")
    names = {p.name for p in dist.iterdir()} - {"SHA256SUMS"}
    check(set(sums) == names and len(names) == 5 and {"ludex.tar.gz", "ludex-gui.tar.gz"} <= names, f"unexpected artifact set {sorted(names)}")
    for name, digest in sums.items():
        check(hashlib.sha256((dist / name).read_bytes()).hexdigest() == digest, f"checksum mismatch: {name}")
    meta = metadata_of(dist / "ludex.tar.gz")
    version = meta["Version"]
    check(meta["Name"] == BUNDLE and re.fullmatch(r"\d+\.\d+\.\d+\.dev\d+", version) is not None, f"bundle sdist metadata {meta['Name']} {version}")
    base = f"https://github.com/{repository}/releases/download/beta"
    requires = {r.split(" @ ")[0]: r.split(" @ ")[1] for r in meta.get_all("Requires-Dist") or [] if " @ " in r}
    check(set(requires) == set(BUNDLED), f"direct requirements {requires}")
    for name, target in requires.items():
        url, _, fragment = target.partition("#sha256=")
        wheel = f"{name.replace('-', '_')}-{version}-py3-none-any.whl"
        check(url == f"{base}/{wheel}" and fragment == sums.get(wheel) and fragment, f"{name}: URL/hash identity {target}")
    gui = metadata_of(dist / "ludex-gui.tar.gz")
    core = requires["ludex-core"]
    check(gui["Name"] == "ludex-gui" and gui["Version"] == version, f"gui sdist metadata {gui['Name']} {gui['Version']}")
    check(f"ludex-core @ {core}" in {r.partition(";")[0].strip() for r in gui.get_all("Requires-Dist") or []}, "gui sdist must pin core by the bundle's URL")
    return version


def check_beta(dist: Path, repository: str) -> None:
    version = verify_production(dist, repository)
    run_number = version.rsplit(".dev", 1)[1]
    scratch = Scratch()
    served = scratch.root / "served"
    served.mkdir()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(served)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        say(f"loopback rebuild of {version} at {base}")
        run([sys.executable, ROOT / ".github/scripts/build_distributions.py", "--outdir", served, "--beta-run-number", run_number, "--asset-base", base], cwd=ROOT)
        url = f"{base}/ludex.tar.gz"
        env = scratch.env
        expected = f"ludex {version}"
        for tool in ("uv", "pipx"):
            bin_dir = Path(scratch.env["UV_TOOL_BIN_DIR" if tool == "uv" else "PIPX_BIN_DIR"])
            tool_python = (Path(scratch.env["UV_TOOL_DIR"]) / "ludex-games" / "bin" / "python") if tool == "uv" else Path(scratch.env["PIPX_HOME"]) / "venvs" / "ludex-games" / "bin" / "python"
            if tool == "uv":
                installs = [["tool", "install"], ["tool", "install", "--force", "--reinstall"]]
                module = [sys.executable, "-m", "uv"]
            else:
                installs = [["install"], ["install", "--force", "--pip-args=--no-cache-dir"]]
                module = [sys.executable, "-m", "pipx"]
            for step, install in enumerate(installs):
                say(f"{tool} {'fresh install' if step == 0 else 'force reinstall'}")
                with_gui = ["--with", f"{base}/ludex-gui.tar.gz"] if tool == "uv" else []
                run([*module, *install, "--python", sys.executable, *with_gui, url], env=env)
                binary = bin_dir / "ludex"
                check([p.name for p in bin_dir.iterdir()] == ["ludex"], f"{tool}: unexpected commands")
                check(run([binary, "--version"], env=env).stdout.strip() == expected, f"{tool} version")
                versions = installed_versions(tool_python, env)
                check(set(versions.values()) == {version} and len(versions) == (4 if tool == "uv" else 3), f"{tool} versions {versions}")
                names, problems = providers_of(binary, scratch.fresh_state(f"{tool}{step}"))
                check(names == BUILTINS and not problems, f"{tool} providers {names} {problems}")
        say("beta smoke passed")
    finally:
        server.shutdown()
        thread.join(timeout=10)
        server.server_close()
        scratch.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["stable", "beta"], required=True)
    parser.add_argument("--dist", required=True, type=Path)
    parser.add_argument("--repository", default="hikaps/ludex")
    args = parser.parse_args(argv)
    dist = args.dist.resolve()
    (check_stable if args.mode == "stable" else partial(check_beta, repository=args.repository))(dist)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
