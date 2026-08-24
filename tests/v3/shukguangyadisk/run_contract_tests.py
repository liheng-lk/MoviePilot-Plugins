"""零外部依赖执行光鸭云盘助手的函数式契约测试。

本目录同时包含 unittest.TestCase 和普通 test_* 函数；unittest discover 不会收集后者。
本 runner 只执行普通函数契约，TestCase 继续由 unittest discover 执行。
"""

from __future__ import annotations

import runpy
import traceback
from pathlib import Path


HERE = Path(__file__).resolve().parent
RUNNER = Path(__file__).resolve()


def main() -> int:
    total = 0
    failures: list[tuple[str, str]] = []
    for path in sorted(HERE.glob("test_*.py")):
        if path == RUNNER:
            continue
        namespace = runpy.run_path(str(path))
        tests = [
            (name, value)
            for name, value in namespace.items()
            if name.startswith("test_") and callable(value)
        ]
        for name, test in sorted(tests):
            total += 1
            label = f"{path.name}::{name}"
            try:
                test()
            except Exception:  # noqa: BLE001 - runner must report all failures
                failures.append((label, traceback.format_exc()))
                print(f"FAIL {label}")
            else:
                print(f"PASS {label}")

    print(f"ShukGuangYaDisk function contracts: {total} run, {len(failures)} failed")
    if failures:
        for label, detail in failures:
            print(f"\n--- {label} ---\n{detail}")
        return 1
    if total == 0:
        print("ERROR: no function-style ShukGuangYaDisk contracts were executed")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
