"""Layering: the core imports no frontend or UI toolkit, the CLI no toolkit and only lazily the TUI, the TUI never the CLI."""
from __future__ import annotations

import ast
from pathlib import Path

import ludex
import ludex_cli
import ludex_tui

TOOLKITS = {"textual", "rich"}
FRONTENDS = {"ludex_cli", "ludex_tui"}


def _imports(path: Path, package: str) -> set[str]:
    """Dotted names imported by ``path`` (inside ``package``), relative imports resolved."""
    found: set[str] = set()
    parts = package.split(".")
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = ".".join(parts[: len(parts) - node.level + 1]) if node.level else ""
            module = ".".join(x for x in (base, node.module) if x)
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
    return found


def _tree(module, forbidden: set[str], allowed_in: dict[str, set[str]] | None = None) -> dict[str, list[str]]:
    root = Path(module.__file__).parent
    bad = {}
    for path in sorted(root.rglob("*.py")):
        package = ".".join((root.name, *path.relative_to(root).parts[:-1]))
        leaked = sorted(n for n in _imports(path, package) if n.split(".")[0] in forbidden)
        leaked = [n for n in leaked if n.split(".")[0] not in (allowed_in or {}).get(path.name, set())]
        if leaked:
            bad[str(path.relative_to(root))] = leaked
    return bad


def test_core_imports_no_frontend_or_ui_toolkit():
    assert _tree(ludex, TOOLKITS | FRONTENDS) == {}


def test_cli_imports_no_toolkit_and_only_hands_off_to_the_tui():
    assert _tree(ludex_cli, TOOLKITS | {"ludex_tui"}, {"cli.py": {"ludex_tui"}}) == {}
    source = (Path(ludex_cli.__file__).parent / "cli.py").read_text()
    tree = ast.parse(source)
    top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(_imports_module(n, "ludex_tui") for n in top_level)  # lazy: --help and --version never load the TUI


def _imports_module(node: ast.stmt, name: str) -> bool:
    if isinstance(node, ast.Import):
        return any(a.name.split(".")[0] == name for a in node.names)
    return isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == name


def test_tui_never_imports_the_cli():
    assert _tree(ludex_tui, {"ludex_cli"}) == {}
