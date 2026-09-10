"""v3.6.0+：统一执行边界。

该层显式位于插件 MRO 前部：
1. 导入阶段先安装 v3.6.9 光鸭路径分页/严格读取基础补丁；
2. monitor 初始化时安装 v3.6.9 连续发现/状态回收，再安装 v3.7.6 双通道扫描、v3.8.0
   部分 ready 调度、持续目录观察流水和全量策略，最后安装 v3.8.2 运行存活保护与
   v3.6.0/v3.6.4 move 安全补丁；
3. 弱命名 folder envelope 内部逐文件执行时，最终状态统一回到 v3.6 fallback；
4. 状态 API 最后投影 v3.6 Worker/discovery 事实，屏蔽旧 v3.5.9 cursor/sticky 的展示残留。

普通 MoviePilot 原生目录任务继续走旧安全预览/冲突/season 等 MoviePilot 安全链，不在这里
重写业务规则。v3.6.9 只修远端路径查询、发现调度和持久状态回收。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.sdk.logging import logger

from .guangya_move_confirmation_v360 import install_move_confirmation_v360
from .guangya_move_transaction_guard_v364 import install_move_transaction_guard_v364
from .guangya_path_resolution_v369 import install_path_resolution_v369
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin, _PAGE_DIR_LIMIT
from .organizer_folder_batch_v342 import _FolderBatchEnvelope


# 存储路径能力必须在插件实例开始 browse/monitor 之前生效；该 installer 只 patch 当前 V3 API，
# 并且自身幂等，不需要等待 organizer MRO 全部加载完成。
install_path_resolution_v369()


class GuangYaOrganizerExecutionV360Mixin(GuangYaOrganizerEngineV360Mixin):
    """3.6 统一 worker 执行、最终状态回写与运行态展示边界。"""

    _v360_storage_patch_ready: bool = False
    _v369_monitor_patch_ready: bool = False
    _v376_dual_scan_patch_ready: bool = False
    _v380_partial_scheduler_patch_ready: bool = False
    _v380_watch_pipeline_patch_ready: bool = False
    _v380_watch_policy_patch_ready: bool = False
    _v382_runtime_survival_patch_ready: bool = False

    def init_organizer_monitor(self) -> None:
        if not self._v369_monitor_patch_ready:
            from .organizer_hardening_v369 import install_organizer_hardening_v369

            install_organizer_hardening_v369()
            self._v369_monitor_patch_ready = True
        if not self._v376_dual_scan_patch_ready:
            from .organizer_dual_scan_v376 import install_dual_scan_v376

            install_dual_scan_v376()
            self._v376_dual_scan_patch_ready = True
        if not self._v380_partial_scheduler_patch_ready:
            from .organizer_partial_scheduler_v380 import install_partial_scheduler_v380

            install_partial_scheduler_v380()
            self._v380_partial_scheduler_patch_ready = True
        if not self._v380_watch_pipeline_patch_ready:
            from .organizer_watch_pipeline_v380 import install_watch_pipeline_v380

            install_watch_pipeline_v380()
            self._v380_watch_pipeline_patch_ready = True
        if not self._v380_watch_policy_patch_ready:
            from .organizer_watch_policy_v380 import install_watch_policy_v380

            install_watch_policy_v380()
            self._v380_watch_policy_patch_ready = True
        if not self._v382_runtime_survival_patch_ready:
            # 必须最后包住最终 tick/status：任何远端扫描异常只能伤到本轮监控，不能冒泡到
            # APScheduler/MoviePilot 插件生命周期；同时为刚安装/热更新提供 180s 自动全量保护期。
            from .organizer_runtime_survival_v382 import install_runtime_survival_v382

            install_runtime_survival_v382()
            self._v382_runtime_survival_patch_ready = True
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
