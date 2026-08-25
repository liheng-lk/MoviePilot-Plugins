"""光鸭自动整理的 MoviePilot 队列隔离、背压与卡顿保护层。

MoviePilot 的 ``TransferChain`` 是全局共享队列。远程光鸭任务如果一次塞入几十/上百个，
或者某个远程任务长时间占住 worker，会连带影响本地下载、手工整理等其它任务。
本层因此只管理“光鸭自动整理允许占用多少个 MP 未终态任务”，不触碰 MoviePilot worker
生命周期，也不清理/重启宿主队列。
"""

from __future__ import annotations

import datetime
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List

from app.sdk.logging import logger


class GuangYaBackpressureMixin:
    """为目录流式调度增加小并发、目录优先和卡顿熔断。"""

    # MoviePilot 当前默认 TRANSFER_THREADS=1。插件默认只允许 1 个未终态任务，
    # 防止再次出现一次向全局队列灌入 100 个任务。宿主线程数 >=2 时还会自动至少
    # 给其它 MoviePilot 整理任务保留 1 个 worker 的容量。
    _monitor_default_max_inflight = 1
    _monitor_default_stall_timeout = 900
    # 不再用 30 分钟 lease 自动把仍可能留在 MP 全局队列的任务重新提交，避免重复排队。
    # 卡顿先由 stall breaker 停止新增。极长时间无回执保持“需要人工确认”而不是自动重放。
    _monitor_inflight_lease = 86400 * 365

    _organize_monitor_max_inflight: int = _monitor_default_max_inflight
    _organize_monitor_stall_timeout: int = _monitor_default_stall_timeout

    def _default_monitor_config(self) -> Dict[str, Any]:
        config = dict(super()._default_monitor_config())
        config.setdefault("max_inflight", self._monitor_default_max_inflight)
        config.setdefault("stall_timeout", self._monitor_default_stall_timeout)
        return config

    def _load_monitor_config(self) -> Dict[str, Any]:
        config = dict(super()._load_monitor_config())
        config["max_inflight"] = self._bounded_int(
            config.get("max_inflight"),
            self._monitor_default_max_inflight,
            1,
            8,
        )
        config["stall_timeout"] = self._bounded_int(
            config.get("stall_timeout"),
            self._monitor_default_stall_timeout,
            120,
            7200,
        )
        return config

    def init_organizer_monitor(self, force: bool = False) -> None:
        super().init_organizer_monitor(force=force)
        config = self._load_monitor_config()
        self._organize_monitor_max_inflight = int(config["max_inflight"])
        self._organize_monitor_stall_timeout = int(config["stall_timeout"])

    def _monitor_config_payload(self) -> Dict[str, Any]:
        payload = dict(super()._monitor_config_payload())
        payload.update({
            "max_inflight": int(self._organize_monitor_max_inflight),
            "stall_timeout": int(self._organize_monitor_stall_timeout),
        })
        return payload

    def _moviepilot_transfer_threads(self) -> int:
        """读取宿主公开运行设置；失败时按当前 MoviePilot 默认 1 个 worker 保守处理。"""
        try:
            from app.runtime.settings import get_runtime_setting

            return max(int(get_runtime_setting("TRANSFER_THREADS") or 1), 1)
        except Exception:
            return 1

    def api_organize_monitor_save(self, payload: dict) -> Dict[str, Any]:
        """保存基础扫描参数后，再持久化与扫描批次独立的 MP 占用上限。"""
        payload = payload or {}
        response = super().api_organize_monitor_save(payload)
        if not isinstance(response, dict) or not response.get("success"):
            return response

        max_inflight = self._bounded_int(
            payload.get("max_inflight", self._organize_monitor_max_inflight),
            self._monitor_default_max_inflight,
            1,
            8,
        )
        stall_timeout = self._bounded_int(
            payload.get("stall_timeout", self._organize_monitor_stall_timeout),
            self._monitor_default_stall_timeout,
            120,
            7200,
        )
        config = dict(self.get_data(self._monitor_config_key) or {})
        config["max_inflight"] = max_inflight
        config["stall_timeout"] = stall_timeout
        self.save_data(self._monitor_config_key, config)
        self._organize_monitor_max_inflight = max_inflight
        self._organize_monitor_stall_timeout = stall_timeout

        snapshot = self._backpressure_snapshot()
        data = response.setdefault("data", {})
        data["config"] = self._monitor_config_payload()
        response["message"] = (
            "自动整理设置已保存；扫描批次与 MoviePilot 占用上限已分离。"
            f"配置上限 {max_inflight}，当前宿主 {snapshot['host_transfer_threads']} 个整理 worker，"
            f"实际光鸭并发上限 {snapshot['max_inflight']}"
        )
        return response

    def _backpressure_snapshot(self, now: float | None = None) -> Dict[str, Any]:
        """读取插件自身 inflight，不窥探或控制 MoviePilot 私有 worker/queue。"""
        now = float(now or time.time())
        try:
            inflight = dict(self._state().load().get("inflight") or {})
        except Exception as err:
            logger.warning("【光鸭云盘助手】【自动整理】【背压】读取 inflight 状态失败: %s", err)
            inflight = {}

        host_threads = self._moviepilot_transfer_threads()
        configured_max = max(int(self._organize_monitor_max_inflight), 1)
        # >=2 worker 时始终至少给非光鸭任务留 1 个 worker；只有 1 worker 时无法做到真正
        # 的 worker 隔离，只能把插件本身限制为最多 1 个任务，避免形成长队列。
        effective_max = min(configured_max, max(host_threads - 1, 1))
        strict_isolation = host_threads >= 2

        oldest_path = ""
        oldest_submitted_at = 0.0
        for path, row in inflight.items():
            submitted_at = float((row or {}).get("submitted_at") or 0)
            if not submitted_at:
                continue
            if not oldest_submitted_at or submitted_at < oldest_submitted_at:
                oldest_submitted_at = submitted_at
                oldest_path = str(path)

        oldest_age = max(now - oldest_submitted_at, 0.0) if oldest_submitted_at else 0.0
        stalled = bool(
            inflight
            and oldest_submitted_at
            and oldest_age >= float(self._organize_monitor_stall_timeout)
        )
        slots = 0 if stalled else max(effective_max - len(inflight), 0)
        return {
            "configured_max_inflight": configured_max,
            "max_inflight": effective_max,
            "host_transfer_threads": host_threads,
            "strict_isolation": strict_isolation,
            "inflight": len(inflight),
            "slots": slots,
            "stalled": stalled,
            "stall_timeout": int(self._organize_monitor_stall_timeout),
            "oldest_path": oldest_path,
            "oldest_age_seconds": int(oldest_age),
            "mode": "bounded_shared_queue",
        }

    def _save_monitor_status(self, **kwargs: Any) -> Dict[str, Any]:
        """所有状态写入都附带真实的光鸭 MP 占用，而不是把 batch_size 当队列容量。"""
        snapshot = self._backpressure_snapshot()
        kwargs.update({
            "queue_limit": snapshot["max_inflight"],
            "queue_slots": snapshot["slots"],
            "dispatch_configured_max_inflight": snapshot["configured_max_inflight"],
            "dispatch_inflight": snapshot["inflight"],
            "dispatch_stalled": snapshot["stalled"],
            "dispatch_stall_timeout": snapshot["stall_timeout"],
            "dispatch_oldest_path": snapshot["oldest_path"],
            "dispatch_oldest_age_seconds": snapshot["oldest_age_seconds"],
            "dispatch_host_transfer_threads": snapshot["host_transfer_threads"],
            "dispatch_strict_isolation": snapshot["strict_isolation"],
        })
        return super()._save_monitor_status(**kwargs)

    def _read_pending_groups(self) -> List[str]:
        status = dict(self.get_data(self._monitor_status_key) or {})
        raw = status.get("pending_groups") or []
        if not isinstance(raw, list):
            raw = []
        result: List[str] = []
        seen = set()
        for value in raw:
            try:
                group_path = self._organize_normalize_path(value)
            except Exception:
                continue
            if group_path in seen:
                continue
            seen.add(group_path)
            result.append(group_path)
        return result[:100]

    def _write_pending_groups(self, groups: List[str]) -> None:
        normalized: List[str] = []
        seen = set()
        for value in groups:
            try:
                group_path = self._organize_normalize_path(value)
            except Exception:
                continue
            if group_path in seen:
                continue
            seen.add(group_path)
            normalized.append(group_path)
        normalized = normalized[:100]
        self._save_monitor_status(
            pending_groups=normalized,
            pending_group=normalized[0] if normalized else "",
            pending_group_count=len(normalized),
        )

    def _process_folder_group(self, **kwargs: Any) -> Dict[str, int]:
        """只给当前优先目录分配少量 MP 槽位，其余目录保持 ready 等待。"""
        group_path = self._organize_normalize_path(kwargs.get("group_path") or "/")
        submit_budget = kwargs["submit_budget"]
        pending_groups = self._read_pending_groups()
        priority_group = pending_groups[0] if pending_groups else ""
        snapshot = self._backpressure_snapshot()

        allowed_group = not priority_group or priority_group == group_path
        effective_slots = min(
            int(submit_budget.get("remaining") or 0),
            int(snapshot.get("slots") or 0),
        ) if allowed_group else 0
        local_budget = {"remaining": effective_slots}
        kwargs = dict(kwargs)
        kwargs["submit_budget"] = local_budget

        result = dict(super()._process_folder_group(**kwargs) or {})
        used = max(effective_slots - int(local_budget.get("remaining") or 0), 0)
        submit_budget["remaining"] = max(int(submit_budget.get("remaining") or 0) - used, 0)

        capacity_wait = int(result.get("capacity_wait") or 0)
        if capacity_wait > 0:
            if group_path not in pending_groups:
                pending_groups.append(group_path)
        else:
            pending_groups = [path for path in pending_groups if path != group_path]
        self._write_pending_groups(pending_groups)

        result["backpressure_wait"] = capacity_wait
        result["dispatch_slots_before"] = effective_slots
        if snapshot.get("stalled"):
            result["dispatch_stalled"] = 1
        return result

    def _load_pending_group_files(self, group_path: str) -> List[Any]:
        """只重扫待补槽的单个目录，不为每释放一个槽位重新遍历整个媒体树。"""
        if not self._guangya_api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")
        group_path = self._organize_normalize_path(group_path)
        root_path = self._organize_normalize_path(self._organize_monitor_path)
        group = self._guangya_api.get_item(Path(group_path))
        if not group or group.type != "dir":
            return []

        files: List[Any] = []
        if group_path == root_path:
            # 监控根批次只代表直接放在根目录的文件，不能把子目录重新混进来。
            for child in self._guangya_api.list(group) or []:
                if str(getattr(child, "name", "") or "").startswith("."):
                    continue
                if child.type == "file":
                    files.append(child)
        else:
            queue = deque([group])
            visited = 0
            while queue:
                current = queue.popleft()
                for child in self._guangya_api.list(current) or []:
                    visited += 1
                    if visited > self._monitor_inventory_cap:
                        raise RuntimeError(f"待补槽目录超过 inventory cap: {group_path}")
                    if str(getattr(child, "name", "") or "").startswith("."):
                        continue
                    if child.type == "dir":
                        queue.append(child)
                    elif child.type == "file":
                        files.append(child)
        files.sort(key=self._file_sort_key)
        return files

    def _pump_pending_group(self) -> bool:
        """心跳期间只给当前目录补充释放出来的 MP 槽位。"""
        pending_groups = self._read_pending_groups()
        snapshot = self._backpressure_snapshot()
        if not pending_groups or snapshot["stalled"] or snapshot["slots"] <= 0:
            return False

        lock = self._organize_scan_lock
        if lock is None or not lock.acquire(blocking=False):
            return False
        group_path = pending_groups[0]
        try:
            files = self._load_pending_group_files(group_path)
            if not files:
                self._write_pending_groups(pending_groups[1:])
                return True

            now_text = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            budget = {
                "remaining": min(
                    int(self._organize_monitor_batch_size),
                    int(snapshot["slots"]),
                )
            }
            result = self._process_folder_group(
                group_path=group_path,
                files=files,
                dispatcher=self._get_organize_dispatcher(),
                state=self._state(),
                submit_budget=budget,
                now_text=now_text,
                scan_started=time.time(),
            )
            self._save_monitor_status(
                running=self._organize_monitor_enabled,
                pump_only=True,
                current_group=group_path,
                current_group_name=self._group_name(group_path),
                current_group_files=len(files),
                current_group_submitted=int(result.get("submitted") or 0),
                capacity_wait=int(result.get("capacity_wait") or 0),
                last_pump=now_text,
            )
            logger.info(
                "【光鸭云盘助手】【自动整理】【背压补槽】目录=%s 文件=%s 入队=%s 等待容量=%s",
                group_path,
                len(files),
                int(result.get("submitted") or 0),
                int(result.get("capacity_wait") or 0),
            )
            return True
        except Exception as err:
            logger.warning("【光鸭云盘助手】【自动整理】【背压补槽】失败: %s - %s", group_path, err)
            self._save_monitor_status(
                pump_only=True,
                current_group=group_path,
                errors=[str(err)],
            )
            return True
        finally:
            lock.release()

    def organize_monitor_tick(self) -> None:
        """30 秒心跳优先补当前目录槽位；队列拥塞时不重复全树扫描。"""
        self.init_organizer_monitor()
        if not self._organize_monitor_enabled:
            return

        snapshot = self._backpressure_snapshot()
        if snapshot["stalled"]:
            self._save_monitor_status(
                running=True,
                dispatch_paused=True,
                dispatch_pause_reason=(
                    f"最老光鸭任务 {snapshot['oldest_age_seconds']} 秒未收到最终回执，"
                    "已停止新增任务，等待 MoviePilot 消化；若长期不恢复请人工检查 MP 整理历史/队列"
                ),
            )
            return

        pending_groups = self._read_pending_groups()
        if pending_groups:
            # 有目录批次积压时只补槽，不重复扫描全部媒体库；即使暂时没有槽位也直接返回。
            if snapshot["slots"] > 0:
                self._pump_pending_group()
            return

        self._save_monitor_status(dispatch_paused=False, dispatch_pause_reason="")
        return super().organize_monitor_tick()

    def _organizer_selfcheck(self) -> Dict[str, Any]:
        report = dict(super()._organizer_selfcheck())
        checks = dict(report.get("checks") or {})
        snapshot = self._backpressure_snapshot()
        checks.update({
            "dispatch_configured_max_inflight": snapshot["configured_max_inflight"],
            "dispatch_max_inflight": snapshot["max_inflight"],
            "dispatch_inflight": snapshot["inflight"],
            "dispatch_slots": snapshot["slots"],
            "dispatch_stalled": snapshot["stalled"],
            "dispatch_oldest_age_seconds": snapshot["oldest_age_seconds"],
            "dispatch_host_transfer_threads": snapshot["host_transfer_threads"],
            "dispatch_strict_isolation": snapshot["strict_isolation"],
            "pending_group_count": len(self._read_pending_groups()),
        })
        report["checks"] = checks
        report["degraded"] = bool(snapshot["stalled"])
        report["isolation_limited"] = not bool(snapshot["strict_isolation"])
        if snapshot["stalled"]:
            report["healthy"] = False
        return report


__all__ = ["GuangYaBackpressureMixin"]
