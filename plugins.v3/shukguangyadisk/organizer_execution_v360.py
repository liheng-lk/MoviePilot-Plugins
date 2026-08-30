"""v3.6.0：统一执行边界。

该层位于 OrganizerEngineV360 与旧 WorkerGuard/QueueRecovery 之间，只做两件事：
1. 插件运行时最后安装 move 终态修复，确保覆盖 v3.4.14 的旧 fileId 强匹配；
2. 弱命名 folder envelope 内部逐文件执行时，最终状态统一回到 v3.6 fallback，避免 v3.4.2
   捕获旧 fallback 后直接把同步 True 当 completed。

普通 MoviePilot 原生目录任务继续走旧安全预览/冲突/season 兼容链，不在这里重写业务规则。
"""

from __future__ import annotations

from typing import Any, List, Tuple

from app.sdk.logging import logger

from .guangya_move_confirmation_v360 import install_move_confirmation_v360
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin
from .organizer_folder_batch_v342 import _FolderBatchEnvelope


class GuangYaOrganizerExecutionV360Mixin(GuangYaOrganizerEngineV360Mixin):
    """3.6 统一 worker 执行与最终状态回写边界。"""

    _v360_storage_patch_ready: bool = False

    def init_organizer_monitor(self) -> None:
        if not self._v360_storage_patch_ready:
            install_move_confirmation_v360()
            self._v360_storage_patch_ready = True
        return super().init_organizer_monitor()

    def _execute_isolated_transfer(self, item: Any) -> Tuple[bool, str]:
        if not isinstance(item, _FolderBatchEnvelope) or item.directory_mode:
            # 原生目录模式继续经过现有 loss-guard / conflict / season 等 MoviePilot 安全链。
            return super()._execute_isolated_transfer(item)

        all_success = True
        messages: List[str] = []
        logger.info(
            "【光鸭云盘助手】【v3.6.0】【执行】弱命名资源按同一 folder task 逐文件交给 MoviePilot: %s，成员=%s",
            item.path,
            len(item.members),
        )
        for member in item.members:
            try:
                success, message = super()._execute_isolated_transfer(member)
            except Exception as err:  # noqa: BLE001
                success, message = False, str(err)
            # 关键：必须调用 self 的 v3.6 fallback。TransferComplete/TransferFailed 如果已经先到，
            # fallback 会看到成员不再 inflight 并保持幂等；不会覆盖真实 MP 最终事件。
            self._fallback_terminal_state(member, success=bool(success), message=str(message or ""))
            all_success = all_success and bool(success)
            if message:
                messages.append(str(message))

        return all_success, "；".join(messages[:3])


__all__ = ["GuangYaOrganizerExecutionV360Mixin"]
