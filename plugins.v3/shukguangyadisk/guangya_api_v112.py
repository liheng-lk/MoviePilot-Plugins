"""光鸭云盘助手 v1.1.2 回收站稳定性适配层。

只覆盖彻底删除链路：区分“回收站查询失败”和“查询成功但目标已不存在”，
避免网络/DNS异常时误判成功，也避免目标已被清理时持续输出假失败告警。
"""

from __future__ import annotations

import time
from typing import List, Optional, Tuple

from app import schemas
from app.log import logger

from .guangya_api import GuangYaApi as _GuangYaApi


class GuangYaApi(_GuangYaApi):
    """在 v1.1.1 API 上增加回收站幂等彻底删除保护。"""

    def _iter_recycle_items_checked(self) -> Tuple[List[schemas.FileItem], bool]:
        """读取完整回收站并返回 ``(items, query_ok)``。

        ``query_ok=False`` 表示至少一页请求本身失败，此时绝不能把“空列表”解释为
        “目标已经不存在”。只有查询明确成功时，空列表才是可信终态。
        """
        results: List[schemas.FileItem] = []
        page = 1
        while True:
            response = self.client.get_file_list(
                parent_id="",
                page_size=self._page_size,
                order_by=10,
                sort_type=0,
                file_types=[],
                page=page,
                dir_type=4,
            )
            if response.get("code", -1) != 0 and response.get("msg") != "success":
                return results, False

            data = response.get("data", {}) or {}
            item_list = data.get("list", []) or []
            if not item_list:
                return results, True

            for item in item_list:
                recycle_item = self._build_file_item_from_api("/", item)
                recycle_item.path = self._build_path(
                    "/.recycle_bin",
                    recycle_item.name,
                    recycle_item.type == "dir",
                )
                results.append(recycle_item)

            total = data.get("total") or 0
            if len(item_list) < self._page_size or (total and len(results) >= total):
                return results, True
            page += 1

    def _match_recycle_item_checked(
        self,
        fileitem: schemas.FileItem,
    ) -> Tuple[Optional[schemas.FileItem], bool]:
        """优先按 fileId 匹配回收站项目，并保留查询成功状态。"""
        candidates, query_ok = self._iter_recycle_items_checked()
        if not query_ok:
            return None, False

        target_fileid = str(fileitem.fileid or "")
        target_name = str(fileitem.name or "")
        target_size = fileitem.size

        if target_fileid:
            for item in candidates:
                if str(item.fileid or "") == target_fileid:
                    return item, True

        same_name_items = [item for item in candidates if item.name == target_name]
        if len(same_name_items) == 1:
            return same_name_items[0], True

        if target_size is not None:
            sized_items = [item for item in same_name_items if item.size == target_size]
            if len(sized_items) == 1:
                return sized_items[0], True

        return None, True

    def _purge_from_recycle(
        self,
        fileitem: schemas.FileItem,
        max_try: int = 8,
        interval: float = 1.0,
    ) -> bool:
        """幂等彻底删除。

        查询失败与目标不存在必须分开处理：
        - 查询失败：不做成功推断；
        - 查询成功且目标持续不存在：认为已经被其它流程清理，按成功终态返回；
        - 找到目标：执行永久删除并确认任务。
        """
        recycle_item: Optional[schemas.FileItem] = None
        last_query_ok = False

        for index in range(max_try):
            recycle_item, query_ok = self._match_recycle_item_checked(fileitem)
            last_query_ok = query_ok
            if recycle_item:
                break

            if not query_ok:
                logger.debug(
                    "【光鸭云盘助手】回收站查询暂时失败，第 %d/%d 次: %s",
                    index + 1,
                    max_try,
                    fileitem.name,
                )

            if index < max_try - 1:
                time.sleep(interval)

        if not recycle_item:
            if last_query_ok:
                logger.info(
                    "【光鸭云盘助手】回收站查询正常且目标已不存在，按已彻底清理处理: %s",
                    fileitem.name,
                )
                return True

            logger.warning(
                "【光鸭云盘助手】回收站查询连续失败，无法确认彻底删除状态，保留后续重试: %s",
                fileitem.name,
            )
            return False

        response = self.client.delete_file([recycle_item.fileid])
        if response.get("msg") != "success" and response.get("code") != 0:
            # 删除接口若明确表示目标不存在，也符合幂等删除语义。
            if self._is_task_missing(response) or response.get("code") in (142, 145, 147):
                logger.info(
                    "【光鸭云盘助手】回收站目标在彻底删除阶段已不存在，按成功处理: %s",
                    fileitem.name,
                )
                return True
            logger.warning("【光鸭云盘助手】回收站彻底删除失败: %s", response)
            return False

        task_id = (response.get("data", {}) or {}).get("taskId", "")
        if task_id and not self._wait_task_done(task_id, allow_missing=True):
            return False
        return True


__all__ = ["GuangYaApi"]
