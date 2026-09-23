"""Architecture import-boundary tests."""

import ast
from pathlib import Path

import pytest

MODULE_IMPORTS = {
    "audit": frozenset(),
    "broker": frozenset({"capability"}),
    "capability": frozenset({"identity", "policy"}),
    "identity": frozenset(),
    "knowledge": frozenset(),
    "policy": frozenset({"identity"}),
    "runtime": frozenset({"capability", "identity", "knowledge", "memory", "policy"}),
}


def _warden_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                name.name.split(".")[1] for name in node.names if name.name.startswith("warden.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("warden."):
            imports.add(node.module.split(".")[1])
    return imports


@pytest.mark.parametrize(("module", "allowed"), MODULE_IMPORTS.items())
def test_modules_only_import_permitted_warden_modules(
    module: str,
    allowed: frozenset[str],
) -> None:
    """Every module follows the directed import graph from the specification."""
    module_path = Path("src/warden") / module
    actual = set().union(*(_warden_imports(path) for path in module_path.rglob("*.py")))

    assert actual <= allowed
    if module == "runtime":
        assert "broker" not in actual
