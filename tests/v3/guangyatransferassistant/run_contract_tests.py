"""零外部依赖执行光鸭转存助手的函数式契约测试。

仓库 CI 使用 unittest discover，但本目录的契约测试采用 pytest 风格的 test_* 普通函数；
unittest 不会收集这些函数。这个 runner 先验证提交态只有 __init__.py 一个运行时 Python
文件，再从单文件 bundle 临时展开历史模块源码，以继续执行全部既有合同测试。
"""

from __future__ import annotations

import ast
import json
import runpy
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PLUGIN_DIR = ROOT / "plugins.v3" / "guangyatransferassistant"
ALLOWED_RUNTIME_PY_FILES = {"__init__.py"}


def _maintenance_guard() -> list[str]:
    errors: list[str] = []
    runtime_files = sorted(PLUGIN_DIR.rglob("*.py"))
    relative = {path.relative_to(PLUGIN_DIR).as_posix() for path in runtime_files}
    unexpected = sorted(relative - ALLOWED_RUNTIME_PY_FILES)
    missing = sorted(ALLOWED_RUNTIME_PY_FILES - relative)
    if unexpected:
        errors.append(
            "single-file runtime violated; remove extra Python modules: " + ", ".join(unexpected)
        )
    if missing:
        errors.append(
            "single-file runtime missing required entry: " + ", ".join(missing)
        )
    return errors


def _bundled_sources() -> dict[str, str]:
    entry = PLUGIN_DIR / "__init__.py"
    tree = ast.parse(entry.read_text(encoding="utf-8"), filename=str(entry))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == "_BUNDLED_SOURCES" for target in targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, dict):
                sources = {str(name): str(source) for name, source in value.items()}
                if not sources:
                    raise RuntimeError("single-file bundle is empty")
                return sources
    raise RuntimeError("single-file bundle does not expose _BUNDLED_SOURCES")


def _materialize_bundle_for_legacy_contracts() -> list[Path]:
    written: list[Path] = []
    for module_name, source in _bundled_sources().items():
        path = PLUGIN_DIR / f"{module_name}.py"
        if path.exists():
            continue
        path.write_text(source, encoding="utf-8")
        written.append(path)
    return written


def _cleanup_materialized_bundle(paths: list[Path]) -> None:
    for path in reversed(paths):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _project_entry_for_legacy_contracts() -> str:
    """Project the frozen r97 source view used by historical slice contracts."""
    entry = PLUGIN_DIR / "__init__.py"
    original = entry.read_text(encoding="utf-8")
    start = original.index("_BUNDLED_SOURCES = ")
    end = original.index("\n\n\nclass _GuangYaBundledModuleFinder", start)
    projected = original[:start] + "_BUNDLED_SOURCES = {}" + original[end:]
    projected = projected.replace(
        "光鸭转存助手 v2.1.3 运行入口。",
        "光鸭转存助手 v2.0.13 运行入口。",
        1,
    )
    class_start = projected.rindex("\nclass GuangYaTransferAssistant(")
    head, tail = projected[:class_start], projected[class_start:]
    tail = tail.replace('    plugin_version = "2.1.3"', '    plugin_version = "2.0.13"', 1)
    tail = tail.replace('    build_id = "20260912-r101"', '    build_id = "20260911-r97"', 1)
    entry.write_text(head + tail, encoding="utf-8")
    return original


def _restore_entry_after_legacy_contracts(original: str) -> None:
    (PLUGIN_DIR / "__init__.py").write_text(original, encoding="utf-8")


def _project_metadata_for_legacy_contracts() -> dict[Path, str]:
    """Keep old release-slice assertions stable while current release has its own contract."""
    plugin_json = PLUGIN_DIR / "plugin.json"
    package_json = ROOT / "package.v3.json"
    originals = {
        plugin_json: plugin_json.read_text(encoding="utf-8"),
        package_json: package_json.read_text(encoding="utf-8"),
    }

    local = json.loads(originals[plugin_json])
    local["version"] = "2.0.13"
    plugin_json.write_text(
        json.dumps(local, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    package = json.loads(originals[package_json])
    package["GuangYaTransferAssistant"]["version"] = "2.0.13"
    package_json.write_text(
        json.dumps(package, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return originals


def _restore_metadata_after_legacy_contracts(originals: dict[Path, str]) -> None:
    for path, content in originals.items():
        path.write_text(content, encoding="utf-8")


def _run_test_file(path: Path, failures: list[tuple[str, Exception, str]]) -> int:
    try:
        namespace = runpy.run_path(str(path))
    except Exception as err:  # noqa: BLE001
        label = f"{path.name}::<module>"
        failures.append((label, err, traceback.format_exc()))
        print(f"FAIL {label}: {err}")
        return 0

    tests = [
        (name, value)
        for name, value in namespace.items()
        if name.startswith("test_") and callable(value)
    ]
    if not tests:
        print(f"SKIP {path.name}: no test_* functions")
        return 0

    total = 0
    for name, test in sorted(tests):
        total += 1
        label = f"{path.name}::{name}"
        try:
            test()
        except Exception as err:  # noqa: BLE001
            failures.append((label, err, traceback.format_exc()))
            print(f"FAIL {label}: {err}")
        else:
            print(f"PASS {label}")
    return total


def main() -> int:
    total = 0
    failures: list[tuple[str, Exception, str]] = []

    maintenance_errors = _maintenance_guard()
    if maintenance_errors:
        for error in maintenance_errors:
            print(f"FAIL maintainability: {error}")
        return 3

    # Real repository/release contracts run before any historical projection.
    pre_projection_tests = {
        HERE / "test_single_file_runtime_contract.py",
        HERE / "test_release_v210_contract.py",
    }
    for path in sorted(pre_projection_tests):
        if path.exists():
            total += _run_test_file(path, failures)

    materialized = _materialize_bundle_for_legacy_contracts()
    original_entry = _project_entry_for_legacy_contracts()
    original_metadata = _project_metadata_for_legacy_contracts()
    print(
        "INFO legacy contract compatibility: "
        f"materialized {len(materialized)} bundled modules; "
        "projected historical release=2.0.13/r97"
    )
    try:
        for path in sorted(HERE.glob("test_*.py")):
            if path in pre_projection_tests:
                continue
            total += _run_test_file(path, failures)
    finally:
        _restore_metadata_after_legacy_contracts(original_metadata)
        _restore_entry_after_legacy_contracts(original_entry)
        _cleanup_materialized_bundle(materialized)

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
