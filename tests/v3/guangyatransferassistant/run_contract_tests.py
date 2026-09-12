"""零外部依赖执行光鸭转存助手的函数式契约测试。

仓库 CI 使用 unittest discover，但本目录的契约测试采用 pytest 风格的 test_* 普通函数；
unittest 不会收集这些函数。这个小型 runner 显式加载每个 test_*.py 并调用所有 test_*，
确保 CI 的“成功”真正覆盖光鸭转存助手，而不是只完成语法检查。
"""

from __future__ import annotations

import ast
import runpy
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent

ROOT = HERE.parents[2]
PLUGIN_DIR = ROOT / "plugins.v3" / "guangyatransferassistant"
# Single-file runtime contract: repository plugin code lives only in __init__.py.
INLINE_RUNTIME_FILE = PLUGIN_DIR / "__init__.py"
REMOVED_WRAPPER_FILES = {
    "resource_filter_v110.py",
    "gying_auth_verified_v1107.py",
    "gying_browser_verified_v1112.py",
    "movie_xunlei_match_v11219.py",
    "status_hardening_v193.py",
}


def _maintenance_guard() -> list[str]:
    errors = []
    runtime_files = sorted(PLUGIN_DIR.rglob("*.py"))
    expected = [INLINE_RUNTIME_FILE]
    if runtime_files != expected:
        errors.append(
            "single-file runtime violated: expected only plugins.v3/guangyatransferassistant/__init__.py; "
            + "found "
            + ", ".join(path.relative_to(ROOT).as_posix() for path in runtime_files)
        )
    if not INLINE_RUNTIME_FILE.exists():
        errors.append("single-file runtime missing __init__.py")
    resurrected = sorted(
        path.name for path in runtime_files if path.name in REMOVED_WRAPPER_FILES
    )
    if resurrected:
        errors.append(
            "merged/dead wrapper modules must not be reintroduced: " + ", ".join(resurrected)
        )
    return errors


def _inline_module_sources() -> dict[str, str]:
    """Read embedded legacy module sources without importing MoviePilot."""
    text = INLINE_RUNTIME_FILE.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(INLINE_RUNTIME_FILE))
    sources: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Subscript):
            continue
        if not isinstance(target.value, ast.Name) or target.value.id != "_INLINE_MODULE_SOURCES":
            continue
        try:
            key = ast.literal_eval(target.slice)
            value = ast.literal_eval(node.value)
        except Exception:
            continue
        if isinstance(key, str) and isinstance(value, str):
            sources[key] = value
    if not sources:
        raise RuntimeError("single-file runtime contains no _INLINE_MODULE_SOURCES")
    return sources


def _materialize_contract_modules() -> list[Path]:
    """Temporarily restore old module paths so the full historical contract suite still runs."""
    created: list[Path] = []
    for short_name, source in _inline_module_sources().items():
        path = PLUGIN_DIR / f"{short_name}.py"
        if path.exists():
            raise RuntimeError(f"contract materialization target already exists: {path}")
        path.write_text(source, encoding="utf-8")
        created.append(path)
    return created


def _cleanup_contract_modules(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
    cache = PLUGIN_DIR / "__pycache__"
    if cache.exists():
        try:
            for item in cache.iterdir():
                item.unlink(missing_ok=True)
            cache.rmdir()
        except Exception:
            pass



def main() -> int:
    total = 0
    failures = []

    maintenance_errors = _maintenance_guard()
    if maintenance_errors:
        for error in maintenance_errors:
            print(f"FAIL maintainability: {error}")
        return 3

    materialized: list[Path] = []
    try:
        materialized = _materialize_contract_modules()
        for path in sorted(HERE.glob("test_*.py")):
            try:
                namespace = runpy.run_path(str(path))
            except Exception as err:  # noqa: BLE001 - surface module-load crashes clearly
                label = f"{path.name}::<module>"
                failures.append((label, err, traceback.format_exc()))
                print(f"FAIL {label}: {err}")
                continue
            tests = [
                (name, value)
                for name, value in namespace.items()
                if name.startswith("test_") and callable(value)
            ]
            if not tests:
                print(f"SKIP {path.name}: no test_* functions")
                continue
            for name, test in sorted(tests):
                total += 1
                label = f"{path.name}::{name}"
                try:
                    test()
                except Exception as err:  # noqa: BLE001 - test runner must report every failure
                    failures.append((label, err, traceback.format_exc()))
                    print(f"FAIL {label}: {err}")
                else:
                    print(f"PASS {label}")
    finally:
        _cleanup_contract_modules(materialized)

    print(f"GuangYa contract tests: {total} run, {len(failures)} failed")
    if failures:
        for label, _, detail in failures:
            print(f"\n--- {label} ---\n{detail}")
        return 1
    if total == 0:
        print("ERROR: no GuangYa contract tests were executed")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
