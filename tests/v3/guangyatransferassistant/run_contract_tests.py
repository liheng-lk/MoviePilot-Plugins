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


def main() -> int:
    total = 0
    failures = []
    for path in sorted(HERE.glob("test_*.py")):
        namespace = runpy.run_path(str(path))
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
