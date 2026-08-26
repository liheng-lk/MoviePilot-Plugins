"""v3.4.14：光鸭同盘整理的重命名终态确认。

MoviePilot 在同一网盘 move/copy 时会把计算好的目标文件名作为 ``new_name`` 传给存储层。
旧 GuangYaApi 的流程是“先移动/复制 -> 再 rename”，但 rename 接口只要返回 success 就立即
返回 True，并没有确认新名字已经在远端真实可见。MoviePilot 随后在目标元数据暂不可见时
还会按“理论目标路径”构造成功结果，因此可能出现：日志/历史显示已按规则重命名，
远端实际文件却仍保留源文件名。

本补丁不生成任何媒体命名规则。目标文件名仍完全来自 MoviePilot；这里只把存储操作改为
“成功必须可验证”，并实现 MoviePilot 新版优先使用的 ``move_item/copy_item``，返回真实远端
FileItem，避免理论路径冒充整理成功。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from app import schemas
from app.log import logger

from .guangya_api_v112 import GuangYaApi


_CONFIRM_TRIES = 30
_CONFIRM_INTERVAL = 0.5


def _same_identity(expected: schemas.FileItem, actual: schemas.FileItem) -> bool:
    """优先按 fileId 确认，同步接口缺少 fileId 时再使用大小兜底。"""
    expected_id = str(getattr(expected, "fileid", "") or "")
    actual_id = str(getattr(actual, "fileid", "") or "")
    if expected_id and actual_id:
        return expected_id == actual_id
    expected_size = getattr(expected, "size", None)
    actual_size = getattr(actual, "size", None)
    if expected_size not in (None, 0) and actual_size not in (None, 0):
        return int(expected_size) == int(actual_size)
    return True


def _confirmed_named_item(
    api: GuangYaApi,
    *,
    parent_path: str,
    target_name: str,
    source_item: schemas.FileItem,
    compare_fileid: bool = True,
    max_try: int = _CONFIRM_TRIES,
    interval: float = _CONFIRM_INTERVAL,
) -> Optional[schemas.FileItem]:
    """确认目标目录中出现指定名字，并按条件核对文件身份。"""
    normalized_parent = api._normalize_path(parent_path)
    for index in range(max_try):
        try:
            item = api._find_item_in_parent(
                parent_path=normalized_parent,
                name=target_name,
                expected_type=getattr(source_item, "type", None),
            )
        except Exception as err:  # noqa: BLE001 - 远端可见性边界
            logger.debug(
                "【光鸭云盘助手】【重命名确认】查询目标暂时失败 %s/%s: %s/%s - %s",
                index + 1,
                max_try,
                normalized_parent,
                target_name,
                err,
            )
            item = None
        if item:
            if not compare_fileid:
                expected_size = getattr(source_item, "size", None)
                actual_size = getattr(item, "size", None)
                if expected_size in (None, 0) or actual_size in (None, 0) or int(expected_size) == int(actual_size):
                    api._cache_item(item)
                    return item
            elif _same_identity(source_item, item):
                api._cache_item(item)
                return item
        if index < max_try - 1:
            time.sleep(interval)
    return None


def install_rename_integrity_v3414() -> None:
    """安装一次性运行时补丁；真实目标名仍由 MoviePilot 提供。"""
    if getattr(GuangYaApi, "_guangya_rename_integrity_v3414", False):
        return

    original_rename = GuangYaApi.rename
    original_move = GuangYaApi.move
    original_copy = GuangYaApi.copy

    def rename(self: GuangYaApi, fileitem: schemas.FileItem, name: str) -> bool:
        """调用原 rename 后必须确认真实远端名称，不再只相信接口 success。"""
        old_path = self._normalize_path(str(getattr(fileitem, "path", "") or ""))
        parent_path = self._normalize_path(str(Path(old_path).parent))
        current_name = str(getattr(fileitem, "name", "") or Path(old_path).name)
        target_name = str(name or current_name).strip()
        if not target_name:
            return False
        if target_name == current_name:
            return True

        if not original_rename(self, fileitem, target_name):
            return False

        # legacy rename 会写入“理论缓存”；确认前必须丢弃，以免缓存被误当远端终态。
        expected_path = self._normalize_path(str(Path(parent_path) / target_name))
        self._invalidate_path_cache(old_path)
        self._invalidate_path_cache(expected_path)

        confirmed = _confirmed_named_item(
            self,
            parent_path=parent_path,
            target_name=target_name,
            source_item=fileitem,
            compare_fileid=True,
        )
        if confirmed:
            logger.info(
                "【光鸭云盘助手】【重命名确认】已确认远端新文件名: %s -> %s",
                current_name,
                target_name,
            )
            return True

        try:
            old_item = self._find_item_in_parent(
                parent_path=parent_path,
                name=current_name,
                expected_type=getattr(fileitem, "type", None),
            )
        except Exception:  # noqa: BLE001
            old_item = None
        logger.error(
            "【光鸭云盘助手】【重命名确认】远端重命名未确认，拒绝向 MoviePilot 返回成功: %s -> %s；旧名仍存在=%s",
            old_path,
            expected_path,
            bool(old_item),
        )
        return False

    def _final_item(
        self: GuangYaApi,
        fileitem: schemas.FileItem,
        path: Path,
        new_name: str,
        *,
        compare_fileid: bool,
    ) -> Optional[schemas.FileItem]:
        target_parent = self._normalize_path(str(path))
        target_name = str(new_name or getattr(fileitem, "name", "") or "")
        target_path = self._normalize_path(str(Path(target_parent) / target_name))
        self._invalidate_path_cache(target_path)
        item = _confirmed_named_item(
            self,
            parent_path=target_parent,
            target_name=target_name,
            source_item=fileitem,
            compare_fileid=compare_fileid,
        )
        if not item:
            logger.error(
                "【光鸭云盘助手】【整理终态】操作返回成功但目标文件未按 MoviePilot 目标名确认: %s",
                target_path,
            )
        return item

    def move_item(
        self: GuangYaApi,
        fileitem: schemas.FileItem,
        path: Path,
        new_name: str,
    ) -> Optional[schemas.FileItem]:
        """MoviePilot 同盘 move 强确认：只有真实目标 FileItem 可见才成功。"""
        if not original_move(self, fileitem, path, new_name):
            return None
        return _final_item(
            self,
            fileitem,
            path,
            new_name,
            compare_fileid=True,
        )

    def copy_item(
        self: GuangYaApi,
        fileitem: schemas.FileItem,
        path: Path,
        new_name: str,
    ) -> Optional[schemas.FileItem]:
        """MoviePilot 同盘 copy 强确认：只有真实目标 FileItem 可见才成功。"""
        if not original_copy(self, fileitem, path, new_name):
            return None
        # copy 后 fileId 必然变化，所以按 MoviePilot 目标名 + 文件大小确认。
        return _final_item(
            self,
            fileitem,
            path,
            new_name,
            compare_fileid=False,
        )

    GuangYaApi.rename = rename
    GuangYaApi.move_item = move_item
    GuangYaApi.copy_item = copy_item
    GuangYaApi._guangya_rename_integrity_v3414 = True


__all__ = ["install_rename_integrity_v3414"]
