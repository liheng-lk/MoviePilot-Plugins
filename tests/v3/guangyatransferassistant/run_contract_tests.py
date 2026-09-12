"""零外部依赖执行光鸭转存助手的函数式契约测试。

仓库 CI 使用 unittest discover，但本目录的契约测试采用 pytest 风格的 test_* 普通函数；
unittest 不会收集这些函数。这个小型 runner 显式加载每个 test_*.py 并调用所有 test_*，
确保 CI 的“成功”真正覆盖光鸭转存助手，而不是只完成语法检查。
"""

from __future__ import annotations

import runpy
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent

ROOT = HERE.parents[2]
PLUGIN_DIR = ROOT / "plugins.v3" / "guangyatransferassistant"
# Maintenance budget: new features should extend an existing responsibility module or
# consolidate an older wrapper first. Raise this only with an explicit architecture reason.
MAX_RUNTIME_PY_FILES = 99
REMOVED_WRAPPER_FILES = {
    "resource_filter_v110.py",
    "gying_auth_verified_v1107.py",
    "gying_browser_verified_v1112.py",
    "movie_xunlei_match_v11219.py",
}


def _maintenance_guard() -> list[str]:
    errors = []
    runtime_files = sorted(PLUGIN_DIR.rglob("*.py"))
    if len(runtime_files) > MAX_RUNTIME_PY_FILES:
        errors.append(
            f"runtime Python module budget exceeded: {len(runtime_files)} > {MAX_RUNTIME_PY_FILES}; "
            "consolidate an existing responsibility before adding another module"
        )
    resurrected = sorted(
        path.name for path in runtime_files if path.name in REMOVED_WRAPPER_FILES
    )
    if resurrected:
        errors.append(
            "merged/dead wrapper modules must not be reintroduced: " + ", ".join(resurrected)
        )
    oversized = [
        path.relative_to(ROOT).as_posix()
        for path in runtime_files
        if path.stat().st_size > 250 * 1024
    ]
    if oversized:
        errors.append(
            "runtime module exceeds 250 KiB maintenance ceiling: " + ", ".join(oversized)
        )
    return errors



def main() -> int:
    total = 0
    failures = []

    maintenance_errors = _maintenance_guard()
    if maintenance_errors:
        for error in maintenance_errors:
            print(f"FAIL maintainability: {error}")
        return 3

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
