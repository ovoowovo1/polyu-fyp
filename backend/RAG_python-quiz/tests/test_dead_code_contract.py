import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FALSE_POSITIVE_MODULES = {
    # FastAPI runtime imports routers in main.py and mounts them via include_router.
    "app.routers.auth",
    "app.routers.classes",
    "app.routers.exam",
    "app.routers.files_pg",
    "app.routers.query_stream",
    "app.routers.quiz",
    "app.routers.sse",
    "app.routers.tts",
    "app.routers.upload",
}

TOOLS_ONLY_MODULES = {
    # Used by evaluation/*.py scripts, not by FastAPI runtime routes.
    "app.utils.dev_credentials",
}


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _imported_modules(path: Path) -> set[str]:
    try:
        tree = ast.parse(_read(path))
    except SyntaxError:
        return set()

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _project_imports(paths: list[Path]) -> set[str]:
    imports: set[str] = set()
    for path in paths:
        imports.update(_imported_modules(path))
    return imports


def test_backend_app_modules_are_not_only_referenced_by_tests():
    app_modules = {
        _module_name(path)
        for path in (ROOT / "app").rglob("*.py")
        if path.name != "__init__.py"
    }
    runtime_paths = [
        *(ROOT / "app").rglob("*.py"),
        *(ROOT / "scripts").rglob("*.py"),
        *(ROOT / "evaluation").rglob("*.py"),
        *(ROOT / "evaluation_exam").rglob("*.py"),
        ROOT / "main.py",
    ]
    test_paths = list((ROOT / "tests").rglob("*.py"))

    runtime_imports = _project_imports([path for path in runtime_paths if path.exists()])
    test_imports = _project_imports(test_paths)
    allowed = FALSE_POSITIVE_MODULES | TOOLS_ONLY_MODULES

    suspicious = sorted(
        module
        for module in app_modules
        if module in test_imports and module not in runtime_imports and module not in allowed
    )

    assert suspicious == []




def test_dev_credentials_is_documented_as_evaluation_tooling():
    source = _read(ROOT / "app" / "utils" / "dev_credentials.py")

    assert "evaluation scripts and manual tooling" in source
    assert "outside the FastAPI runtime auth flow" in source
