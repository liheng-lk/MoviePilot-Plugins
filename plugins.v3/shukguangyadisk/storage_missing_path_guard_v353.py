"""v3.5.3：查询型存储接口兼容整理后路径已消失。

MoviePilot 在一次 move/rename 完成后，仍可能用旧 FileItem 调用 ``any_files`` 或
``list_files`` 检查源目录是否还有媒体。对于光鸭同盘移动，旧目录可能已经被清空并删除，
此时 ``GuangYaApi.list`` 会通过 ``_path_to_id`` 抛 ``FileNotFoundError``。

这不是存储故障，而是一个合法终态：
- any_files -> False
- list_files -> []

只收口这两个只读查询接口；move/copy/delete/get_item 等真实操作仍保留原有异常/失败语义，
避免掩盖整理链中的路径错误。
"""

from __future__ import annotations

from typing import Any

from app.sdk.logging import logger

from . import _plugin_legacy as _legacy


def install_storage_missing_path_guard_v353() -> None:
    plugin_cls = _legacy.ShukGuangYaDisk
    if getattr(plugin_cls, "_guangya_missing_query_path_guard_v353", False):
        return

    original_any_files = plugin_cls.any_files
    original_list_files = plugin_cls.list_files

    def any_files(self: Any, fileitem: Any, extensions: list = None):
        try:
            return original_any_files(self, fileitem, extensions)
        except FileNotFoundError:
            path = str(getattr(fileitem, "path", "") or "")
            logger.debug(
                "【光鸭云盘助手】【存储查询】any_files 检查时目录已不存在，按无文件处理: %s",
                path,
            )
            return False

    def list_files(self: Any, fileitem: Any, recursion: bool = False):
        try:
            return original_list_files(self, fileitem, recursion)
        except FileNotFoundError:
            path = str(getattr(fileitem, "path", "") or "")
            logger.debug(
                "【光鸭云盘助手】【存储查询】list_files 检查时目录已不存在，按空目录处理: %s",
                path,
            )
            return []

    plugin_cls.any_files = any_files
    plugin_cls.list_files = list_files
    plugin_cls._guangya_missing_query_path_guard_v353 = True
    logger.info("【光鸭云盘助手】【v3.5.3】整理后旧路径查询容错已启用")


__all__ = ["install_storage_missing_path_guard_v353"]
