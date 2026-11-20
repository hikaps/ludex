"""Build the four ludex distributions (core, cli, tui and the ludex-games bundle) plus ludex-gui with one consistent version.

    python .github/scripts/build_distributions.py --outdir dist
    python .github/scripts/build_distributions.py --outdir dist --beta-run-number 7 --asset-base https://github.com/OWNER/ludex/releases/download/beta

Stable mode builds an sdist and a wheel of each (eight files). Beta mode stamps ``<base>.dev<N>`` into a private copy of
the tree, builds the three member wheels and the bundle's wheel and sdist (renamed ``ludex.tar.gz``), and points the
bundle's requirements at the member wheels under ``--asset-base`` by direct URL with their SHA-256; it also writes
``SHA256SUMS``. The beta URLs exist only in the generated artifacts, never in the source tree.
"""
from __future__ import annotations

import argparse
import email
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = "ludex-games"
MEMBERS = {"ludex-core": "packages/core", "ludex-cli": "packages/cli", "ludex-tui": "packages/tui"}
GUI = ("ludex-gui", "packages/gui")  # lockstep and published, but not in the ludex-games bundle (it brings Qt) nor in beta builds
VERSION = re.compile(r"\d+\.\d+\.\d+")
LOOPBACK = re.compile(r"http://127\.0\.0\.1:\d+")
_IGNORE = shutil.ignore_patterns("build", "dist", "*.egg-info", "__pycache__", "*.pyc", ".pytest_cache")


def _project(root: Path, relative: str) -> dict:
    return tomllib.loads((root / relative / "pyproject.toml").read_text())["project"]


def check_tree(root: Path) -> str:
    """Validate names, versions and exact internal pins of the source tree; return its base version."""
    projects = {BUNDLE: _project(root, "."), GUI[0]: _project(root, GUI[1])} | {name: _project(root, path) for name, path in MEMBERS.items()}
    for name, project in projects.items():
        if project["name"] != name:
            raise SystemExit(f"expected project {name}, found {project['name']!r}")
    versions = {name: project["version"] for name, project in projects.items()}
    base = versions[BUNDLE]
    if not VERSION.fullmatch(base) or set(versions.values()) != {base}:
        raise SystemExit(f"expected one plain X.Y.Z version for all distributions, got {versions}")
    init = (root / MEMBERS["ludex-core"] / "src/ludex/__init__.py").read_text()
    if re.findall(r'^__version__ = "([^"]+)"$', init, re.MULTILINE) != [base]:
        raise SystemExit(f"__version__ disagrees with project version {base!r}")
    pins = {f"{name}=={base}" for name in MEMBERS}
    for name in (BUNDLE, "ludex-cli", "ludex-tui", GUI[0]):
        wanted = pins if name == BUNDLE else {f"ludex-core=={base}"}
        found = {d for d in projects[name]["dependencies"] if d.split("==")[0] in MEMBERS}
        if found != wanted:
            raise SystemExit(f"{name} must pin exactly {sorted(wanted)}, found {sorted(found)}")
    return base


def _build(project_dir: Path, outdir: Path, *, sdist: bool, wheel: bool) -> None:
    command = [sys.executable, "-m", "build", "--outdir", str(outdir)]
    command += (["--sdist"] if sdist else []) + (["--wheel"] if wheel else []) + [str(project_dir)]
    subprocess.run(command, check=True)


def metadata_of(path: Path) -> email.message.Message:
    """The core metadata of a wheel or an sdist."""
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as wheel:
            name = next(n for n in wheel.namelist() if n.endswith(".dist-info/METADATA"))
            return email.message_from_bytes(wheel.read(name))
    with tarfile.open(path, "r:gz") as archive:
        member = next(m for m in archive.getmembers() if m.name.count("/") == 1 and m.name.endswith("/PKG-INFO"))
        return email.message_from_bytes(archive.extractfile(member).read())


def _wheel_files(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as wheel:
        return wheel.namelist()


def _sdist_has_license(path: Path) -> bool:
    with tarfile.open(path, "r:gz") as archive:
        return any(m.isfile() and m.name.count("/") == 1 and m.name.endswith("/LICENSE") for m in archive.getmembers())


_OWNS = {"ludex-core": "ludex/", "ludex-cli": "ludex_cli/", "ludex-tui": "ludex_tui/", GUI[0]: "ludex_gui/", BUNDLE: None}


def verify(outdir: Path, version: str, expected_requires: dict[str, set[str]], *, sdists: bool) -> list[Path]:
    """Check every artifact: name, version, dependencies, owned top-level package, no stray direct URL (unless expected)."""
    wheels = []
    for name, owns in ((n, o) for n, o in _OWNS.items() if n in expected_requires):
        stem = name.replace("-", "_")
        found = sorted(outdir.glob(f"{stem}-{version}*.whl"))
        if len(found) != 1:
            raise SystemExit(f"expected one wheel for {name} {version}, found {found}")
        wheels.append(found[0])
        kinds = [found[0]] + (sorted(outdir.glob(f"{stem}-{version}.tar.gz")) if sdists else [])
        if sdists and len(kinds) != 2:
            raise SystemExit(f"expected an sdist for {name} {version}")
        for artifact in kinds:
            meta = metadata_of(artifact)
            if meta["Name"] != name or meta["Version"] != version:
                raise SystemExit(f"{artifact.name}: unexpected metadata {meta['Name']!r} {meta['Version']!r}")
            requires = {r.partition(";")[0].strip() for r in (meta.get_all("Requires-Dist") or []) if "extra ==" not in r}
            internal = {r for r in requires if r.split("==")[0].split(" @")[0] in MEMBERS}
            if internal != expected_requires[name]:
                raise SystemExit(f"{artifact.name}: internal requirements {sorted(internal)} != {sorted(expected_requires[name])}")
        top = {n.split("/")[0] for n in _wheel_files(found[0]) if not n.split("/")[0].endswith((".dist-info", ".data"))}
        if top != ({owns.rstrip("/")} if owns else set()):
            raise SystemExit(f"{found[0].name}: unexpected top-level contents {sorted(top)}")
        if sdists and name != BUNDLE and not _sdist_has_license(kinds[1]):
            raise SystemExit(f"{kinds[1].name}: no LICENSE file in the sdist")
    return wheels


def build_stable(outdir: Path) -> None:
    base = check_tree(ROOT)
    for path in (*MEMBERS.values(), GUI[1]):
        _build(ROOT / path, outdir, sdist=True, wheel=True)
    _build(ROOT, outdir, sdist=True, wheel=True)
    expected = {BUNDLE: {f"{name}=={base}" for name in MEMBERS}} | {"ludex-core": set(), "ludex-cli": {f"ludex-core=={base}"}, "ludex-tui": {f"ludex-core=={base}"}, GUI[0]: {f"ludex-core=={base}"}}
    verify(outdir, base, expected, sdists=True)


def build_beta(outdir: Path, run_number: str, asset_base: str) -> None:
    if not run_number.isdigit():
        raise SystemExit(f"--beta-run-number must be numeric, got {run_number!r}")
    if not (asset_base.startswith("https://") or LOOPBACK.fullmatch(asset_base)):
        raise SystemExit("--asset-base must be https:// (or http://127.0.0.1:PORT for smoke tests)")
    base = check_tree(ROOT)
    version = f"{base}.dev{run_number}"
    with tempfile.TemporaryDirectory(prefix="ludex-beta-") as tmp:
        work = Path(tmp)
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(ROOT / name, work / name)
        shutil.copytree(ROOT / "packages", work / "packages", symlinks=True, ignore=_IGNORE)
        files = [work / "pyproject.toml", *(work / p / "pyproject.toml" for p in MEMBERS.values()), work / MEMBERS["ludex-core"] / "src/ludex/__init__.py"]
        for file in files:
            text = file.read_text()
            stamped = re.sub(rf'(?m)^(version|__version__) = "{re.escape(base)}"$', rf'\1 = "{version}"', text)
            stamped = stamped.replace(f"=={base}\"", f"=={version}\"")
            file.write_text(stamped)
        for path in MEMBERS.values():
            _build(work / path, outdir, sdist=False, wheel=True)
        digests = {}
        for name in MEMBERS:
            wheel = next(outdir.glob(f"{name.replace('-', '_')}-{version}-*.whl"))
            digests[name] = (wheel.name, hashlib.sha256(wheel.read_bytes()).hexdigest())
        pyproject = work / "pyproject.toml"
        text = pyproject.read_text()
        for name, (wheel_name, digest) in digests.items():
            text = text.replace(f'"{name}=={version}"', f'"{name} @ {asset_base}/{wheel_name}#sha256={digest}"')
        pyproject.write_text(text)
        _build(work, outdir, sdist=True, wheel=True)
    expected = {BUNDLE: {f"{name} @ {asset_base}/{wheel}#sha256={digest}" for name, (wheel, digest) in digests.items()},
                "ludex-core": set(), "ludex-cli": {f"ludex-core=={version}"}, "ludex-tui": {f"ludex-core=={version}"}}
    wheels = verify(outdir, version, expected, sdists=False)
    sdist = next(outdir.glob(f"ludex_games-{version}.tar.gz"))
    meta = metadata_of(sdist)
    if meta["Name"] != BUNDLE or meta["Version"] != version:
        raise SystemExit(f"unexpected bundle sdist metadata {meta['Name']!r} {meta['Version']!r}")
    archive = outdir / "ludex.tar.gz"
    sdist.rename(archive)
    (outdir / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in [*wheels, archive]
    ))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outdir", required=True, type=Path)
    parser.add_argument("--beta-run-number")
    parser.add_argument("--asset-base")
    args = parser.parse_args(argv)
    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if any(outdir.iterdir()):
        raise SystemExit(f"{outdir} is not empty")
    if (args.beta_run_number is None) != (args.asset_base is None):
        raise SystemExit("--beta-run-number and --asset-base go together")
    if args.beta_run_number is None:
        build_stable(outdir)
    else:
        build_beta(outdir, args.beta_run_number, args.asset_base.rstrip("/"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
