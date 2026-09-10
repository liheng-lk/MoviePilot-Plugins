"""v3.6.0+：统一执行边界。

v3.9.0 起，目录监控由最终 MRO 第一层 ``GuangYaFinalMonitorV390Mixin`` 静态实现。
本层只保留已经验证的底层安全能力：
1. 导入阶段安装 v3.6.9 光鸭路径分页/严格路径解析基础补丁；
2. monitor 真正开始运行时再安装 v3.6.9 远端读取硬化与 move 安全补丁；
3. 不再安装 v3.7.6/v3.8.x monitor monkey-patch 栈，避免 MoviePilot 安装注册阶段产生副作用；
4. 弱命名 folder envelope 内部逐文件执行时，最终状态统一回到 v3.6 fallback；
5. 状态 API继续投影 v3.6 Worker/discovery 事实。

普通 MoviePilot 原生目录任务继续走既有安全预览/冲突/season 等链，不在这里重写业务规则。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.sdk.logging import logger

from .guangya_move_confirmation_v360 import install_move_confirmation_v360
from .guangya_move_transaction_guard_v364 import install_move_transaction_guard_v364
from .guangya_path_resolution_v369 import install_path_resolution_v369
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin, _PAGE_DIR_LIMIT
from .organizer_folder_batch_v342 import _FolderBatchEnvelope


# 路径解析是存储基础能力，并非 monitor 调度；保持导入期幂等安装。
install_path_resolution_v369()


class GuangYaOrganizerExecutionV360Mixin(GuangYaOrganizerEngineV360Mixin):
    """3.6 统一 worker 执行、最终状态回写与运行态展示边界。"""

    _v360_storage_patch_ready: bool = False
    _v369_monitor_patch_ready: bool = False

    def init_organizer_monitor(self) -> None:
        """仅在真正运行监控时装配底层读取/移动安全能力。"""
        if not self._v369_monitor_patch_ready:
            from .organizer_hardening_v369 import install_organizer_hardening_v369

            install_organizer_hardening_v369()
            self._v369_monitor_patch_ready = True
        if not self._v360_storage_patch_ready:
            install_move_confirmation_v360()
            install_move_transaction_guard_v364()
            self._v360_storage_patch_ready = True
        return super().init_organizer_monitor()

    def _execute_isolated_transfer(self, item: Any) -> Tuple[bool, str]:
        if not isinstance(item, _FolderBatchEnvelope) or item.directory_mode:
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
            # TransferComplete/TransferFailed 若已经先到，成员终态保持幂等；fallback 仅补宿主未回执边界。
            self._fallback_terminal_state(member, success=bool(success), message=str(message or ""))
            all_success = all_success and bool(success)
            if message:
                messages.append(str(message))

        return all_success, "；".join(messages[:3])

    def _fallback_terminal_state(self, item: Any, success: bool, message: str) -> None:
        if isinstance(item, _FolderBatchEnvelope) and not item.directory_mode:
            logger.debug(
                "【光鸭云盘助手】【v3.6.0】【最终结果】弱命名 envelope 已逐成员收口，跳过聚合 fallback: %s",
                item.path,
            )
            return
        return super()._fallback_terminal_state(item, success=success, message=message)

    def api_organize_monitor_status(self) -> Dict[str, Any]:
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

        status.update({
            "organizer_engine": "v3.6.0",
            "scheduler_mode": "single_resource_worker",
            "discovery_page_size": _PAGE_DIR_LIMIT,
            "sticky_tv_group_path": "",
            "sticky_tv_group_active": False,
            "sticky_tv_group_since": 0,
            "active_resource_tasks": 1 if running_path else 0,
            "worker_queue_depth": int(snapshot.get("queued") or 0),
            "runtime_hardening": "v3.6.9",
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
        except Exception as err:  # noqa: BLE001
            status["scan_cursor_error"] = str(err)

        return response


__all__ = ["GuangYaOrganizerExecutionV360Mixin"]
