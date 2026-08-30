"""v3.6.0：统一执行边界。

该层显式位于插件 MRO 最前面：
1. 最后安装 move 终态修复，覆盖 v3.4.14 跨目录 move 的旧 fileId 强匹配；
2. 弱命名 folder envelope 内部逐文件执行时，最终状态统一回到 v3.6 fallback；
3. 状态 API 最后投影 v3.6 Worker/discovery 事实，屏蔽旧 v3.5.9 cursor/sticky 的展示残留。

普通 MoviePilot 原生目录任务继续走旧安全预览/冲突/season 兼容链，不在这里重写业务规则。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.sdk.logging import logger

from .guangya_move_confirmation_v360 import install_move_confirmation_v360
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin, _PAGE_DIR_LIMIT
from .organizer_folder_batch_v342 import _FolderBatchEnvelope


class GuangYaOrganizerExecutionV360Mixin(GuangYaOrganizerEngineV360Mixin):
    """3.6 统一 worker 执行、最终状态回写与运行态展示边界。"""

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
            # 必须调用 self 的 v3.6 fallback。TransferComplete/TransferFailed 如果已经先到，
            # fallback 会看到成员不再 inflight 并保持幂等，不覆盖真实 MP 最终事件。
            self._fallback_terminal_state(member, success=bool(success), message=str(message or ""))
            all_success = all_success and bool(success)
            if message:
                messages.append(str(message))

        return all_success, "；".join(messages[:3])

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        """旧兼容层先补历史，最后由 3.6 用真实 Worker/cursor 事实覆盖调度展示。"""
        response = super().api_organize_monitor_status()
        if not isinstance(response, dict) or not response.get("success"):
            return response

        data = response.setdefault("data", {})
        status = data.setdefault("status", {})
        try:
            snapshot = dict(self._isolated_queue_snapshot() or {})
        except Exception:
            snapshot = {}
        running_path = str(snapshot.get("running_path") or "")
        handoff = bool(status.get("worker_handoff_waiting"))

        # 3.6 不再以 sticky 作为调度状态。即使旧 v3.5.2/v3.5.9 API wrapper 仍存在，
        # 最终响应也必须明确归零，避免 UI 再显示“当前剧集=/”。
        status.update({
            "organizer_engine": "v3.6.0",
            "scheduler_mode": "single_resource_worker",
            "discovery_page_size": _PAGE_DIR_LIMIT,
            "sticky_tv_group_path": "",
            "sticky_tv_group_active": False,
            "sticky_tv_group_since": 0,
            "active_resource_tasks": 1 if running_path else 0,
            "worker_queue_depth": int(snapshot.get("queued") or 0),
        })

        if running_path:
            status["current_task_path"] = running_path
            status["runtime_phase"] = "running"
            status["runtime_label"] = "当前资源整理中"
        elif not handoff and str(status.get("runtime_phase") or "") not in {"stopped", "draining"}:
            status["current_task_path"] = ""

        try:
            root = self._v360_norm(self._organize_monitor_path)
            cursor = self._v360_load_cursor(root)
            status.update({
                "scan_cursor_cycle": int(cursor.get("cycle") or 1),
                "scan_cursor_page": int(cursor.get("page") or 0),
                "scan_cursor_remaining_dirs": len(cursor.get("queue") or []),
            })
        except Exception as err:  # noqa: BLE001 - status must remain observable
            status["scan_cursor_error"] = str(err)

        return response


__all__ = ["GuangYaOrganizerExecutionV360Mixin"]
