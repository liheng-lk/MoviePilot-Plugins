"""光鸭自动整理到 MoviePilot 的唯一任务提交边界。

媒体识别模块只负责构造高置信度上下文；本模块才允许真正调用
``TransferDispatcher`` / ``TransferChain``。这样扫描、识别、背压和任务提交不会
彼此耦合，也便于以后统一做限流、熔断和运行时诊断。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.chain.transfer import TransferChain
from app.sdk.logging import logger

from .organizer import GuangYaOrganizerMixin as _MonitorOrganizerMixin


class GuangYaDispatchMixin:
    """把所有自动整理任务统一收口到同一个 MoviePilot 提交适配层。"""

    def _dispatch_to_moviepilot(self, item: Any) -> bool:
        """提交一个文件到 MoviePilot。

        - 没有高置信度上下文时，走 MoviePilot 原生 ``TransferDispatcher``；
        - 有明确剧集/目录类型上下文时，只在本层调用 ``TransferChain.do_transfer``；
        - 返回值仅表示 MoviePilot 是否接受本次计划/入队，不代表最终整理成功。
        """
        event_path = Path(str(getattr(item, "path", "") or ""))
        contextual_builder = getattr(self, "_build_context_meta", None)
        contextual = contextual_builder(event_path) if callable(contextual_builder) else None
        if not contextual:
            return bool(_MonitorOrganizerMixin._dispatch_to_moviepilot(self, item))

        meta, media_type, reason = contextual
        fileitem_builder = getattr(self, "_fileitem_from_cloud_item", None)
        if not callable(fileitem_builder):
            raise RuntimeError("自动整理识别上下文已生成，但 FileItem 构造器不可用")
        fileitem = fileitem_builder(item, event_path, self._disk_name)

        logger.info(
            "【光鸭云盘助手】【自动整理】【识别上下文】%s -> type=%s meta=%s；依据=%s；"
            "后续目录/命名/整理仍由 MoviePilot 处理",
            event_path,
            media_type.value,
            getattr(meta, "title", event_path.stem),
            reason,
        )
        result = TransferChain().do_transfer(
            fileitem=fileitem,
            meta=meta,
            mtype=media_type,
        )
        if isinstance(result, tuple):
            return bool(result[0])
        return bool(result)


__all__ = ["GuangYaDispatchMixin"]
