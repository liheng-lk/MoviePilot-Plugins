"""v3.6.10：MoviePilot 存储快照使用严格远端读取，网络失败不再伪装成删除。

V3StorageContractMixin.snapshot_storage 会从 previous_snapshot 起步，并在成功枚举目录后删除
已经不存在的直接子项。legacy GuangYaApi.list() 遇到 API/网络失败会返回当前结果（可能是
空列表），这会把“读取失败”错误解释为“目录真实为空”，进而从 MoviePilot 快照中删掉仍然
存在的文件。

v3.6.9 已为运行时 GuangYaApi 提供 list_strict：只有远端明确成功才返回列表，失败抛异常。
本层把同样的不变量扩展到 MoviePilot 存储快照：
- 目录成功完整枚举后才允许 remove_deleted_children；
- 子目录读取失败保留 previous_snapshot 中该子树，等待下一轮对账；
- 根路径读取失败直接返回上一轮快照，而不是制造空快照；
- 根路径被远端明确确认不存在时才返回空快照。
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Dict, Optional

from app.sdk.logging import logger

from .storage_contract import V3StorageContractMixin


_PATCH_FLAG = "_v3610_strict_snapshot_ready"


def install_storage_snapshot_guard_v3610() -> None:
    """幂等替换 V3 storage snapshot；不修改上传、删除、整理或 MoviePilot 媒体规则。"""
    if getattr(V3StorageContractMixin, _PATCH_FLAG, False):
        return

    def snapshot_storage(
        self: Any,
        storage: str,
        path: Path,
        last_snapshot_time: float = None,
        max_depth: int = 5,
        previous_snapshot: Optional[Dict[str, Dict]] = None,
    ) -> Optional[Dict[str, Dict]]:
        if not self._matches_storage(storage):
            return None
        api = getattr(self, "_guangya_api", None)
        if not api:
            return {}

        root_path = PurePosixPath(Path(path).as_posix())
        files_info: Dict[str, Dict] = {}
        for file_path, file_info in (previous_snapshot or {}).items():
            try:
                if PurePosixPath(str(file_path)).is_relative_to(root_path):
                    files_info[str(file_path)] = dict(file_info or {})
            except (TypeError, ValueError):
                continue

        strict_list = getattr(api, "list_strict", None)
        if not callable(strict_list):
            # v3.6.9 应保证该能力存在。异常加载顺序下宁可保留旧快照，也不能把读取失败当删除。
            logger.warning(
                "【光鸭云盘助手】【v3.6.10】【存储快照】严格目录读取能力未就绪，本轮保留上一快照"
            )
            return files_info

        def remove_deleted_children(directory_item: Any, sub_files: list[Any]) -> None:
            directory_path = PurePosixPath(str(getattr(directory_item, "path", "") or "/"))
            child_paths = {
                PurePosixPath(str(getattr(sub_file, "path", "") or ""))
                for sub_file in sub_files
                if getattr(sub_file, "path", None)
            }
            for old_file_path in list(files_info):
                try:
                    relative_path = PurePosixPath(old_file_path).relative_to(directory_path)
                except ValueError:
                    continue
                if not relative_path.parts:
                    continue
                direct_child = directory_path / relative_path.parts[0]
                if direct_child not in child_paths:
                    files_info.pop(old_file_path, None)

        def snapshot_item(fileitem: Any, current_depth: int = 0) -> None:
            if getattr(fileitem, "type", None) == "dir":
                if current_depth >= max_depth:
                    return
                if (
                    current_depth > 0
                    and bool(getattr(self, "snapshot_check_folder_modtime", True))
                    and last_snapshot_time
                    and getattr(fileitem, "modify_time", None)
                    and fileitem.modify_time <= last_snapshot_time
                ):
                    return

                try:
                    sub_files = list(strict_list(fileitem) or [])
                except Exception as err:  # noqa: BLE001 - 保留 previous_snapshot 是快照正确性要求
                    logger.warning(
                        "【光鸭云盘助手】【v3.6.10】【存储快照】目录读取失败，保留上一轮子树: %s - %s",
                        getattr(fileitem, "path", ""),
                        err,
                    )
                    return

                # 只有上面的严格读取成功后，空列表才具有“真实空目录”语义。
                remove_deleted_children(fileitem, sub_files)
                for sub_file in sub_files:
                    snapshot_item(sub_file, current_depth + 1)
                return

            file_path = str(getattr(fileitem, "path", "") or "")
            if not file_path:
                return
            files_info[file_path] = {
                "size": int(getattr(fileitem, "size", 0) or 0),
                "modify_time": getattr(fileitem, "modify_time", 0) or 0,
                "fileid": getattr(fileitem, "fileid", None),
                "type": getattr(fileitem, "type", "file") or "file",
            }

        try:
            root_item = api.get_item(Path(path))
        except Exception as err:  # noqa: BLE001 - 根读取失败不能制造空快照
            logger.warning(
                "【光鸭云盘助手】【v3.6.10】【存储快照】根路径读取失败，本轮保留上一快照: %s - %s",
                path,
                err,
            )
            return files_info

        if not root_item:
            # v3.6.9 get_item 只有在完整路径分页明确未找到时才返回 None；此时空快照可信。
            logger.info("【光鸭云盘助手】【v3.6.10】【存储快照】根路径已明确不存在，返回空快照: %s", path)
            return {}

        snapshot_item(root_item)
        return files_info

    V3StorageContractMixin.snapshot_storage = snapshot_storage
    setattr(V3StorageContractMixin, _PATCH_FLAG, True)
    logger.info("【光鸭云盘助手】【v3.6.10】存储快照严格读取保护已启用：网络失败保留上一轮快照")


__all__ = ["install_storage_snapshot_guard_v3610"]
