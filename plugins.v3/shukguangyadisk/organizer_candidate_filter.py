"""v3.4+ 自动整理候选过滤与私有队列连续补充。

独立 worker 架构不再需要 ``TransferDispatcher``：它的核心职责是把文件事件提交到
MoviePilot 全局后台整理队列，而 v3.4 明确禁止走这条路径。本模块只读取 MoviePilot
公开运行设置中的媒体/字幕/音频扩展名与临时文件扩展名，用于扫描阶段过滤候选。

v3.4.1 修复私有队列完成一批后可能等待完整扫描周期才继续的问题。
v3.4.2 把资源目录升级为真正的“一个文件夹一个整理任务”。
v3.4.3 清理重启后仍残留的旧光鸭全局任务并自动切换到私有 worker。
v3.4.4 曾增加中文父目录提示保护。
v3.4.6 改为完整资源目录直接走 MoviePilot 路径识别与目录整理，不再由插件提取标题。
v3.4.7 增加 DNS/连接故障熔断、日志降噪和扫描状态保护。
v3.4.9 增加整理前零损失预览校验和逐文件终态确认，阻止同名覆盖导致集数进入回收站。
v3.4.10 增加执行前源目录复核，已搬空/无视频目录不再进入 MoviePilot 识别。
v3.4.11 增加整组样本推荐与多形态集号兼容层，适配 01 4K、EP01、第01集等弱命名。
v3.4.12 使用 MoviePilot 当前 category.yaml 重新核验分类，消除缓存/外部识别源残留分类。
v3.4.13 多级目录改为按实际文件所在目录独立分组，避免第一层分类目录吞并整棵子树。
v3.4.14 对光鸭远端 move/copy 后的重命名做真实可见性确认，拒绝理论目标路径假成功。
v3.5.0 把作品目录身份与单文件集号分离，并改为严格“发现一个→识别一个→整理一个”的单任务流水。
v3.5.1 修复电影容器仍可能整目录预览、热更新交接状态不清和运行状态统计口径错误。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, List, Tuple

from app.runtime.settings import get_runtime_setting
from app.sdk.logging import logger


class _MoviePilotCandidateFilter:
    """只实现 folder-stream 所需的候选判断合同，不持有任何 MP 队列状态。"""

    @staticmethod
    def _list_setting(name: str) -> List[str]:
        value: Any = get_runtime_setting(name)
        if not value:
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [str(item).strip() for item in value if str(item).strip()]

    @classmethod
    def is_transfer_candidate_path(cls, file_path: Path) -> bool:
        suffix = str(file_path.suffix or "").casefold()
        if not suffix:
            return False
        temp_exts = {item.casefold() for item in cls._list_setting("DOWNLOAD_TMPEXT")}
        if suffix in temp_exts:
            return False
        allowed = {
            item.casefold()
            for key in ("RMT_MEDIAEXT", "RMT_SUBEXT", "RMT_AUDIOEXT")
            for item in cls._list_setting(key)
        }
        return suffix in allowed

    @staticmethod
    def retry_pending() -> None:
        """兼容旧 folder-stream 调用点；独立路径没有 dispatcher pending。"""
        return None


class GuangYaCandidateFilterMixin:
    """无 MP 全局队列状态的候选过滤器 + 私有单任务流水补充。"""

    _organize_candidate_filter: _MoviePilotCandidateFilter | None = None

    _monitor_heartbeat = 10
    _isolated_refill_low_watermark = 0
    _isolated_refill_min_gap = 3.0
    _organize_last_fast_refill: float = 0.0

    def _get_organize_dispatcher(self) -> _MoviePilotCandidateFilter:
        if self._organize_candidate_filter is None:
            self._organize_candidate_filter = _MoviePilotCandidateFilter()
        return self._organize_candidate_filter

    def _fast_refill_needed(self) -> Tuple[bool, str]:
        if not getattr(self, "_organize_monitor_enabled", False):
            return False, "disabled"

        snapshot_getter = getattr(self, "_isolated_queue_snapshot", None)
        if not callable(snapshot_getter):
            return False, "no_isolated_queue"
        try:
            isolated = dict(snapshot_getter() or {})
        except Exception:
            return False, "snapshot_error"

        queued = int(isolated.get("queued") or 0)
        running_path = str(isolated.get("running_path") or "")
        if running_path or queued > 0:
            return False, "worker_busy"

        status = dict(self.get_data(self._monitor_status_key) or {})
        capacity_wait = int(status.get("capacity_wait") or 0)
        waiting = int(status.get("waiting") or 0)
        if capacity_wait > 0:
            return True, f"capacity_wait={capacity_wait},queued=0"
        if waiting > 0:
            return True, f"stability_wait={waiting},queued=0"
        return False, "no_backlog"

    def organize_monitor_tick(self) -> None:
        self.init_organizer_monitor()
        if not self._organize_monitor_enabled:
            return

        now = time.monotonic()
        needed, reason = self._fast_refill_needed()
        if needed and now - self._organize_last_fast_refill >= self._isolated_refill_min_gap:
            self._organize_last_fast_refill = now
            self._organize_monitor_last_tick = now
            self._save_monitor_status(
                fast_refill_active=True,
                fast_refill_reason=reason,
                fast_refill_at=time.time(),
            )
            logger.info("【光鸭云盘助手】【单任务流水】【连续补充】触发下一资源扫描: %s", reason)
            try:
                return self.run_organize_monitor_scan(manual=False)
            finally:
                self._save_monitor_status(fast_refill_active=False)

        return super().organize_monitor_tick()


from .guangya_rename_integrity_v3414 import install_rename_integrity_v3414
from .organizer_folder_batch_v342 import install_folder_batch_v342
from .organizer_legacy_queue_cleanup_v343 import install_legacy_queue_cleanup_v343
from .organizer_mp_folder_context_v346 import install_mp_folder_context_v346
from .organizer_deep_folder_stream_v3413 import install_deep_folder_stream_v3413
from .guangya_network_resilience_v347 import install_network_resilience_v347
from .organizer_loss_guard_v349 import install_loss_guard_v349
from .organizer_empty_folder_guard_v3410 import install_empty_folder_guard_v3410
from .organizer_episode_name_adapter_v3411 import install_episode_name_adapter_v3411
from .organizer_episode_sample_bridge_v3411 import install_episode_sample_bridge_v3411
from .organizer_category_consistency_v3412 import install_category_consistency_v3412
from .organizer_folder_identity_v350 import install_folder_identity_v350
from .organizer_rename_diagnostics_v3414 import install_rename_diagnostics_v3414
from .organizer_single_flight_v350 import install_single_flight_v350
from .organizer_single_flight_refill_v350 import install_single_flight_refill_v350
from .organizer_orchestrator_v351 import install_orchestrator_v351

# 存储层补丁必须最先安装，确保 MoviePilot 真正执行 move/copy 时拿到的是强确认接口。
install_rename_integrity_v3414()
install_folder_batch_v342()
install_legacy_queue_cleanup_v343()
install_mp_folder_context_v346()
install_deep_folder_stream_v3413()
install_network_resilience_v347()
install_loss_guard_v349()
install_empty_folder_guard_v3410()
install_episode_name_adapter_v3411()
install_episode_sample_bridge_v3411()
install_category_consistency_v3412()
# v3.5.0：先让作品目录身份覆盖错误文件名，再输出最终 MP 重命名诊断。
install_folder_identity_v350()
install_rename_diagnostics_v3414()
# 最后收口调度：运行中绝不预排第二个资源；worker 真正空闲后立即续跑。
install_single_flight_v350()
install_single_flight_refill_v350()
# v3.5.1 在单任务闭包安装后覆盖结构判断，并投影真实 worker 运行态。
install_orchestrator_v351()


__all__ = ["GuangYaCandidateFilterMixin"]
