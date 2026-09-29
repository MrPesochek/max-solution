import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

FORBIDDEN = {
    "app/core": ("app.adapters", "app.modules", "app.worker"),
    "app/modules": ("app.adapters", "app.worker"),
    "app/infra": ("app.core", "app.modules", "app.adapters", "app.worker"),
}


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def _violations(package: str, forbidden: tuple[str, ...]) -> list[str]:
    found = []
    for path in (APP_DIR.parent / package).rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for module in _imported_modules(tree):
            if any(module == f or module.startswith(f + ".") for f in forbidden):
                found.append(f"{path.relative_to(APP_DIR.parent)} → {module}")
    return found


def test_layers_do_not_import_upwards() -> None:
    violations: list[str] = []
    for package, forbidden in FORBIDDEN.items():
        violations += _violations(package, forbidden)
    assert violations == []


def test_modules_talk_to_each_other_only_through_api() -> None:
    violations = []
    for path in (APP_DIR / "modules").rglob("*.py"):
        own_module = path.relative_to(APP_DIR / "modules").parts[0]
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported in _imported_modules(tree):
            parts = imported.split(".")
            if len(parts) < 3 or parts[:2] != ["app", "modules"]:
                continue
            if parts[2] == own_module:
                continue
            if len(parts) > 3 and parts[3] != "api":
                violations.append(f"{path.relative_to(APP_DIR.parent)} → {imported}")
    assert violations == []
