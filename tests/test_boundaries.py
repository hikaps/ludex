"""The core must stay usable without a frontend: only the frontend modules may import a UI toolkit or each other."""
from __future__ import annotations

import ast
from pathlib import Path

import ludex

FRONTEND = {"cli", "tui", "tui_settings", "__main__"}
TOOLKITS = {"textual", "rich"}


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                found.add((node.module or "").split(".")[0])
            elif node.level == 1 and node.module:
                found.add("ludex." + node.module.split(".")[0])  # ``from .cli import x`` inside the package
            elif node.level == 1:
                found.update("ludex." + alias.name for alias in node.names)
    return found


def test_no_core_module_imports_a_ui_toolkit_or_a_frontend():
    root = Path(ludex.__file__).parent
    bad = {}
    for path in sorted(root.rglob("*.py")):
        if path.parent == root and path.stem in FRONTEND:
            continue
        leaked = {name for name in _imports(path) if name in TOOLKITS or name.removeprefix("ludex.") in FRONTEND}
        if leaked:
            bad[str(path.relative_to(root))] = sorted(leaked)
    assert bad == {}


def test_only_the_tui_modules_import_textual():
    root = Path(ludex.__file__).parent
    users = {p.stem for p in root.rglob("*.py") if "textual" in _imports(p)}
    assert users == {"tui", "tui_settings"}
