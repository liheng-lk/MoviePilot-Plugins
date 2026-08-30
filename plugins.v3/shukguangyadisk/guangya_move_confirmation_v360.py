"""v3.6.0：同盘 move 终态确认按 MoviePilot 目标名 + 大小收口。

v3.4.14 在 move_item 的最终查询里仍拿“源 fileId”与目标文件比较。光鸭跨目录 move 后 fileId
并不保证保持不变，因此会出现 rename 已经确认新名字可见，随后 move_item 又因为旧 fileId
不一致返回 None，最终被 MoviePilot 判成“移动文件失败”。

3.6.0 保留安全边界：目标必须真实可见、名字必须等于 MoviePilot 给出的 new_name，且文件大小
一致；只是取消跨目录 move 后不可靠的旧 fileId 强匹配。copy 逻辑不改。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from app import schemas
from app.log import logger

from .guangya_api_v112 import GuangYaApi
from .guangya_rename_integrity_v3414 import _confirmed_named_item


def install_move_confirmation_v360() -> None:
    if getattr(GuangYaApi, "_guangya_move_confirmation_v360", False):
        return

    def move_item(
        self: GuangYaApi,
        fileitem: schemas.FileItem,
        path: Path,
        new_name: str,
    ) -> Optional[schemas.FileItem]:
        target_parent = self._normalize_path(str(path))
        target_name = str(new_name or getattr(fileitem, "name", "") or "").strip()
        if not target_name:
            return None

        # GuangYaApi.move 内部仍使用 v3.4.14 已安装的强 rename：rename 返回 True 前已经确认
        # MoviePilot 目标名真实可见。这里再取得目标 FileItem 时按名字 + 大小确认，不使用源 fileId。
        if not self.move(fileitem, path, target_name):
            return None

        target_path = self._normalize_path(str(Path(target_parent) / target_name))
        self._invalidate_path_cache(target_path)
        item = _confirmed_named_item(
            self,
            parent_path=target_parent,
            target_name=target_name,
            source_item=fileitem,
            compare_fileid=False,
        )
        if item:
            logger.info(
                "【光鸭云盘助手】【v3.6.0】【移动终态】已按 MoviePilot 目标名+大小确认: %s",
                target_path,
            )
            return item

        logger.error(
            "【光鸭云盘助手】【v3.6.0】【移动终态】目标名在确认窗口内仍不可见: %s",
            target_path,
        )
        return None

    GuangYaApi.move_item = move_item
    GuangYaApi._guangya_move_confirmation_v360 = True
    logger.info("【光鸭云盘助手】【v3.6.0】同盘 move 终态改为 MoviePilot 目标名+大小确认")


__all__ = ["install_move_confirmation_v360"]
