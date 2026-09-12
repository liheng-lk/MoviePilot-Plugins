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
# Runtime architecture contract: this plugin is intentionally a single-file runtime.
ALLOWED_RUNTIME_PY_FILES = {"__init__.py"}


def _maintenance_guard() -> list[str]:
    errors = []
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

