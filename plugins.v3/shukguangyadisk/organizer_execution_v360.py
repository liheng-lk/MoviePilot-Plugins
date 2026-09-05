"""v3.6.0+：统一执行边界。

该层显式位于插件 MRO 前部：
1. 导入阶段先安装 v3.6.9 光鸭路径分页/严格读取，以及 v3.6.10 MoviePilot 存储快照保护；
2. monitor 初始化时安装 v3.6.9/v3.6.13 连续发现与状态可达性回收，随后安装 v3.6.19
   终态索引收口，再安装 v3.6.11 durable retry、v3.6.12 pending 真等待门禁与 v3.6.15
   pending 公平调度，最后安装 v3.6.0 move 终态修复与 v3.6.4 move 失败事务保护；
   v3.6.17 只读投影 blocked 诊断；
3. v3.6.18 在私有 Worker 调 MoviePilot 前强制刷新源路径，已明确消失的源直接终态清理，
   并在“预检后刚好被搬走”的失败竞态里再次复核，禁止把不存在路径重新写入 retry；
4. v3.6.19 在 v3.6.13 已严格确认目录/子树消失时，同步清理 known-resource 与
   pending-resource 调度索引，避免已搬走历史路径仍被后续增量扫描触碰；
5. 弱命名 folder envelope 内部逐文件执行时，最终状态统一回到 v3.6 fallback；
6. 状态 API 最后投影 v3.6 Worker/discovery/blocked 事实，屏蔽旧 v3.5.9 cursor/sticky 的展示残留。

普通 MoviePilot 原生目录任务继续走旧安全预览/冲突/season 等 MoviePilot 安全链，不在这里
重写业务规则。v3.6.9~v3.6.19 只修远端查询、发现调度、状态/快照可靠性、durable 任务身份
衔接、pending 等待态语义、公平性、长期状态回收效率与 Worker 执行边界终态。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.sdk.logging import logger

from .guangya_move_confirmation_v360 import install_move_confirmation_v360
from .guangya_move_transaction_guard_v364 import install_move_transaction_guard_v364
from .guangya_path_resolution_v369 import install_path_resolution_v369
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin, _PAGE_DIR_LIMIT
from .organizer_folder_batch_v342 import _FolderBatchEnvelope
from .organizer_source_terminal_v3618 import (
    SOURCE_MISSING_TERMINAL_V3618,
    confirm_source_missing_v3618,
    retire_missing_source_v3618,
    source_missing_hint_v3618,
)
from .storage_snapshot_guard_v3610 import install_storage_snapshot_guard_v3610


# 存储查询/快照能力必须在插件实例开始 browse/snapshot/monitor 之前生效；installer 均幂等。
install_path_resolution_v369()
install_storage_snapshot_guard_v3610()


class GuangYaOrganizerExecutionV360Mixin(GuangYaOrganizerEngineV360Mixin):
    """3.6 统一 worker 执行、最终状态回写与运行态展示边界。"""

    _v360_storage_patch_ready: bool = False
    _v369_monitor_patch_ready: bool = False
    _v3619_index_gc_ready: bool = False
    _v3611_retry_patch_ready: bool = False
    _v3612_pending_patch_ready: bool = False
    _v3615_fairness_patch_ready: bool = False
    _v3617_blocked_diag_logged: bool = False

    def init_organizer_monitor(self) -> None:
        if not self._v369_monitor_patch_ready:
            # 延迟到运行期导入，避免插件 __init__ 尚在装配 MRO 时让 v3.6.9 反向提前导入
            # organizer_monitor_v366。此时所有类已经定义完成，patch 安装安全且可重复。
            from .organizer_hardening_v369 import install_organizer_hardening_v369

            install_organizer_hardening_v369()
            self._v369_monitor_patch_ready = True
        if not self._v3619_index_gc_ready:
            # v3.6.19 必须在 v3.6.13 hardening 已安装后包裹其 reachability helper，
            # 才能复用同一次 list_strict 的完整直属目录事实，不增加第二次远端读取。
            from .organizer_terminal_index_gc_v3619 import install_terminal_index_gc_v3619

            install_terminal_index_gc_v3619()
            self._v3619_index_gc_ready = True
        if not self._v3611_retry_patch_ready:
            # durable retry bridge 必须在 v3.6.9/v3.6.13 monitor patch 之后安装：它包裹最终
            # _v360_prepare_member / admission fallback，避免失败历史重新生成 planning_input。
            from .organizer_durable_retry_v3611 import install_durable_retry_v3611

            install_durable_retry_v3611()
            self._v3611_retry_patch_ready = True
        if not self._v3612_pending_patch_ready:
            # pending 门禁放在最终 monitor/durable patch 之后：所有 scheduler 都可以继续返回
            # 兼容 reason，但真正写 pending 前必须由最终 phases 证明存在真实等待态。
            from .organizer_pending_truth_v3612 import install_pending_truth_v3612

            install_pending_truth_v3612()
            self._v3612_pending_patch_ready = True
        if not self._v3615_fairness_patch_ready:
            # 公平层必须最后包住 v3.6.9 monitor wrapper，并复用 v3.6.12 已收紧的真实 pending；
            # 只有无活动执行的等待态才让出本 tick，inflight/durable 仍保持单资源阻断。
            from .organizer_pending_fairness_v3615 import install_pending_fairness_v3615

            install_pending_fairness_v3615()
            self._v3615_fairness_patch_ready = True
        if not self._v360_storage_patch_ready:
            # 安装顺序不可交换：v3.6.4 必须包在 v3.6.0 最终 move_item 外层，才能在
            # MoviePilot 收到失败前进行延长确认、回滚和 delete/purge 保护。
            install_move_confirmation_v360()
            install_move_transaction_guard_v364()
            self._v360_storage_patch_ready = True

        result = super().init_organizer_monitor()
        if not self._v3617_blocked_diag_logged:
            self._v3617_blocked_diag_logged = True
            try:
                from .organizer_blocked_diagnostics_v3617 import log_blocked_diagnostics

                log_blocked_diagnostics(self)
            except Exception as err:  # noqa: BLE001 - diagnostics can never fail plugin init
                logger.debug("【光鸭云盘助手】【v3.6.17】【blocked诊断】启动诊断失败但不影响监控: %s", err)
        return result

    def _execute_isolated_transfer(self, item: Any) -> Tuple[bool, str]:
        if not isinstance(item, _FolderBatchEnvelope):
            if confirm_source_missing_v3618(self, item):
                retire_missing_source_v3618(self, item)
                return True, SOURCE_MISSING_TERMINAL_V3618
            return super()._execute_isolated_transfer(item)

        if item.directory_mode:
            if confirm_source_missing_v3618(self, item):
                retire_missing_source_v3618(self, item, subtree=True)
                return True, SOURCE_MISSING_TERMINAL_V3618
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
                if confirm_source_missing_v3618(self, member):
                    retire_missing_source_v3618(self, member)
                    success, message = True, SOURCE_MISSING_TERMINAL_V3618
                else:
                    success, message = super()._execute_isolated_transfer(member)
            except Exception as err:  # noqa: BLE001
                success, message = False, str(err)
            # 每个成员在这里独立收口。TransferComplete/TransferFailed 如果已经先到，v3.6
            # fallback 会看到成员不再 inflight 并保持幂等，不覆盖真实 MP 最终事件。
            self._fallback_terminal_state(member, success=bool(success), message=str(message or ""))
            all_success = all_success and bool(success)
            if message and message != SOURCE_MISSING_TERMINAL_V3618:
                messages.append(str(message))

        return all_success, "；".join(messages[:3])

    def _fallback_terminal_state(self, item: Any, success: bool, message: str) -> None:
        """统一收口弱命名成员与执行期间刚消失的源，缺失源绝不重新写 retry。"""
        if str(message or "") == SOURCE_MISSING_TERMINAL_V3618:
            return

        # 预检时源仍存在，但在进入 MoviePilot 后刚好被其它流程搬走时，MoviePilot 会返回
        # “没有找到可整理的媒体文件”。只有再次强制刷新确认真的不存在，才终态清理；
        # 网络/API失败或媒体过滤仍沿用原失败语义。
        if not success and source_missing_hint_v3618(message) and confirm_source_missing_v3618(self, item):
            subtree = bool(isinstance(item, _FolderBatchEnvelope) and item.directory_mode)
            retire_missing_source_v3618(self, item, subtree=subtree)
            return

        # 弱命名 envelope 已逐成员收口，禁止 Worker 外层再用聚合 True/False 覆盖成员结果。
        if isinstance(item, _FolderBatchEnvelope) and not item.directory_mode:
            logger.debug(
                "【光鸭云盘助手】【v3.6.0】【最终结果】弱命名 envelope 已逐成员收口，跳过聚合 fallback: %s",
                item.path,
            )
            return
        return super()._fallback_terminal_state(item, success=success, message=message)

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        """旧兼容层先补历史，最后由 3.6 用真实 Worker/cursor/blocked 事实覆盖调度展示。"""
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
            "runtime_hardening": "v3.6.19",
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

        try:
            from .organizer_blocked_diagnostics_v3617 import blocked_diagnostics

            blocked_diag = blocked_diagnostics(self)
            status["blocked_diagnostics"] = blocked_diag
            status["blocked_persistent"] = int(blocked_diag.get("persistent") or 0)
            status["blocked_due"] = int(blocked_diag.get("due") or 0)
            status["blocked_timed"] = int(blocked_diag.get("timed") or 0)
        except Exception as err:  # noqa: BLE001 - read-only diagnostics must never break status
            status["blocked_diagnostics"] = {"rows": [], "error": str(err)[:240]}

        return response


__all__ = ["GuangYaOrganizerExecutionV360Mixin"]
