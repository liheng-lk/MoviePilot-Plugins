"""MoviePilot V3 宿主导入兼容桥。

插件历史实现仍有少量 ``app.log`` / ``app.helper.storage`` 导入。新版 MoviePilot V3
已把这些能力迁移到稳定 SDK；在旧实现彻底迁移前，仅在缺少旧模块时提供最小别名，
避免插件在安装/加载阶段因 ImportError 直接失败。
"""

from __future__ import annotations

import sys
import types


def install_host_compat() -> None:
    """为新版 MoviePilot V3 补齐历史导入别名；已有旧模块时不覆盖。"""
    try:
        import app.log  # type: ignore  # noqa: F401
    except ModuleNotFoundError:
        from app.sdk.logging import logger

        log_module = types.ModuleType("app.log")
        log_module.logger = logger
        sys.modules.setdefault("app.log", log_module)

    try:
        import app.helper.storage  # type: ignore  # noqa: F401
    except ModuleNotFoundError:
        from app.sdk.services import StorageHelper

        storage_module = types.ModuleType("app.helper.storage")
        storage_module.StorageHelper = StorageHelper
        sys.modules.setdefault("app.helper.storage", storage_module)


__all__ = ["install_host_compat"]
