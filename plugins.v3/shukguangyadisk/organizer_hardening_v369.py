"""v3.6.9：自动监控连续发现、远端读取故障隔离与状态局部回收。

v3.6.6 引入 known-resource 增量索引后，已完成基线的日常 tick 只检查旧资源目录；新创建、
从未进入 known 索引的资源只能等 30 分钟 full discovery。这让“60 秒监控”并不等价于
“60 秒内发现新资源”，同时每轮最多检查 500 个旧目录会产生大量远端 API 请求。

本层保持严格单任务流水与 MoviePilot 业务边界，只修发现/状态基础设施：
- known-resource 每轮预算收敛到 24 个目录；
- known 检查没有提交任务时，同一个 monitor tick 继续推进一页 50 目录 discovery 游标，
  因而新目录发现真正跟随用户配置 interval；
- v3.6 engine 目录读取改用 GuangYaApi.list_strict；网络/API 失败必须传播为扫描错误，绝不能
  伪装成“目录为空”；若怀疑 fileId 缓存陈旧，只刷新当前目录一次后重试；
- 每次成功完整读取一个目录后，只对该目录直属源文件做状态回收，清理已经搬走的
  completed/blocked/retry/stabilizing/inflight/ignored，避免长期运行状态 JSON 无界增长；
- 局部回收严格按直属 parent 匹配，不以祖先/子树推断，避免部分扫描误删未枚举状态。
"""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Sequence, Tuple

from app.sdk.logging import logger

from . import organizer_monitor_v366 as _v366
from .organizer_engine_v360 import GuangYaOrganizerEngineV360Mixin
from .organizer_monitor_v366 import GuangYaOrganizerMonitorV366Mixin


_KNOWN_SCAN_BUDGET = 24
_PATCH_FLAG = "_v369_runtime_hardening_ready"
_STATE_NAMES = ("completed", "ignored", "blocked", "stabilizing", "inflight", "retry")


def _network_status(plugin: Any) -> Dict[str, Any]:
    api = getattr(plugin, "_guangya_api", None)
    client = getattr(api, "client", None) or getattr(plugin, "_client", None)
    getter = getattr(client, "get_network_status", None)
    if not callable(getter):
        return {"available": True, "hosts": {}}
    try:
        return dict(getter() or {})
    except Exception:
        return {"available": True, "hosts": {}}


def _direct_parent(plugin: Any, raw_path: str) -> str:
    try:
        return plugin._v360_norm(PurePosixPath(str(raw_path or "")).parent.as_posix())
    except Exception:
        return ""


def _reconcile_direct_state(plugin: Any, group_path: str, direct_files: Sequence[Any]) -> int:
    """成功列出一个目录后，仅回收该目录直属且已经不存在的状态记录。"""
    group = plugin._v360_norm(group_path)
    if not group:
        return 0
    present = {
        plugin._v360_norm(getattr(item, "path", ""))
        for item in direct_files
        if getattr(item, "path", None)
    }

    def apply(state: Dict[str, Any]) -> int:
        removed = 0
        for name in _STATE_NAMES:
            mapping = dict(state.get(name) or {})
            for raw_path in list(mapping):
                path = plugin._v360_norm(raw_path)
                if _direct_parent(plugin, path) != group:
                    continue
                if path in present:
                    continue
                mapping.pop(raw_path, None)
                removed += 1
            state[name] = mapping
        return removed

    return int(plugin._state().mutate(apply) or 0)


def _split_children(plugin: Any, children: Sequence[Any]) -> Tuple[List[Any], List[Any]]:
    dirs: List[Any] = []
    files: List[Any] = []
    for child in children:
        name = str(getattr(child, "name", "") or "")
        if not name or name.startswith("."):
            continue
        kind = str(getattr(child, "type", "") or "")
        if kind == "dir":
            if getattr(plugin, "_organize_monitor_recursive", False):
                dirs.append(child)
        elif kind == "file":
            files.append(child)
    dirs.sort(key=plugin._group_sort_key)
    files.sort(key=plugin._file_sort_key)
    return dirs, files


def install_organizer_hardening_v369() -> None:
    """幂等包裹 v3.6 engine/monitor，不改变识别、分类、命名或整理策略。"""
    if getattr(GuangYaOrganizerMonitorV366Mixin, _PATCH_FLAG, False):
        return

    # 旧实现每 tick 最多读 500 个历史资源目录；先收敛远端请求预算，再持续推进 discovery。
    _v366._KNOWN_SCAN_LIMIT = min(int(getattr(_v366, "_KNOWN_SCAN_LIMIT", 500) or 500), _KNOWN_SCAN_BUDGET)

    previous_list_directory = GuangYaOrganizerEngineV360Mixin._v360_list_directory
    previous_monitor_scan = GuangYaOrganizerMonitorV366Mixin.run_organize_monitor_scan

    def list_directory(plugin: Any, path: str):
        api = getattr(plugin, "_guangya_api", None)
        if not api:
            raise RuntimeError("光鸭云盘尚未登录或存储未初始化")

        current = api.get_item(Path(path))
        if not current:
            # get_item 明确完成远端解析并返回不存在，此时该目录直属状态可安全回收。
            pruned = _reconcile_direct_state(plugin, path, [])
            if pruned:
                logger.info(
                    "【光鸭云盘助手】【v3.6.9】【状态回收】目录已不存在，清理直属陈旧状态=%s: %s",
                    pruned,
                    path,
                )
            return [], []
        if str(getattr(current, "type", "") or "") != "dir":
            return [], []

        strict_list = getattr(api, "list_strict", None)
        if not callable(strict_list):
            # 安装顺序异常时宁可保留旧语义，不在这里重写整个存储层。
            return previous_list_directory(plugin, path)

        try:
            children = list(strict_list(current) or [])
        except Exception as first_error:
            refresher = getattr(api, "refresh_item", None)
            if not callable(refresher):
                raise
            try:
                refreshed = refresher(Path(path))
            except Exception:
                raise first_error
            if not refreshed:
                # 首次 list 失败后，重新按路径解析确认目录确实消失，才允许按空目录收口。
                pruned = _reconcile_direct_state(plugin, path, [])
                if pruned:
                    logger.info(
                        "【光鸭云盘助手】【v3.6.9】【状态回收】刷新确认目录已消失，清理直属状态=%s: %s",
                        pruned,
                        path,
                    )
                return [], []
            try:
                children = list(strict_list(refreshed) or [])
            except Exception as retry_error:
                raise RuntimeError(
                    f"严格读取目录失败，已刷新 fileId 仍不可用: {path} - {retry_error}"
                ) from retry_error

        dirs, files = _split_children(plugin, children)
        pruned = _reconcile_direct_state(plugin, path, files)
        if pruned:
            plugin._save_monitor_status(
                state_direct_pruned=pruned,
                state_direct_pruned_at=time.time(),
                state_direct_pruned_path=plugin._v360_norm(path),
            )
            logger.info(
                "【光鸭云盘助手】【v3.6.9】【状态回收】成功读取目录后清理已消失直属状态=%s: %s",
                pruned,
                path,
            )
        return dirs, files

    def run_monitor_scan(plugin: Any, manual: bool = False) -> Dict[str, Any]:
        # 先保留 v3.6.7 的 owner / pending / known / manual-safe 全部语义。
        result = previous_monitor_scan(plugin, manual=manual)
        if manual or not isinstance(result, dict):
            return result

        data = dict(result.get("data") or {})
        if any(
            data.get(key)
            for key in ("scheduled", "busy", "handoff", "disabled", "scan_busy")
        ):
            return result
        # 只有 v3.6.7 日常 known scan 正常结束后才补推进 discovery；初始/周期 baseline 已经
        # 自己调用了 engine，不能重复扫描第二页。
        if not data.get("known_scan"):
            return result

        network = _network_status(plugin)
        if not network.get("available", True):
            plugin._save_monitor_status(
                network_deferred=True,
                network_message="光鸭文件 API 暂不可用；已知资源/连续发现均保留状态等待下轮",
            )
            return {
                "success": True,
                "message": "光鸭网络/API暂不可用，本轮保留状态并延后连续发现",
                "data": {
                    **data,
                    "continuous_discovery": False,
                    "network_deferred": True,
                },
            }

        # 直接进入唯一 v3.6 engine 的一页 discovery。动态 self._v360_schedule_resource 仍会
        # 落回 v3.6.7 最终准入层，因此不会绕过手动筛选、history gate 或 admission guard。
        discovery = GuangYaOrganizerEngineV360Mixin.run_organize_monitor_scan(plugin, manual=False)
        if not isinstance(discovery, dict):
            return result
        discovery_data = discovery.setdefault("data", {})
        if not isinstance(discovery_data, dict):
            discovery_data = {}
            discovery["data"] = discovery_data
        discovery_data["continuous_discovery"] = True
        discovery_data["known_scan_summary"] = {
            "known_total": data.get("known_total", 0),
            "known_checked": data.get("known_checked", 0),
            "known_changed": data.get("known_changed", 0),
            "known_removed": data.get("known_removed", 0),
            "known_errors": data.get("known_errors", 0),
        }
        if discovery_data.get("cycle_complete"):
            marker = getattr(plugin, "_v366_mark_baseline_complete", None)
            if callable(marker):
                marker()
            plugin._save_monitor_status(full_discovery_completed_at=time.time())

        after_network = _network_status(plugin)
        if not after_network.get("available", True):
            discovery["success"] = True
            discovery["message"] = "连续发现期间网络/API中断，游标已停在断点并保留全部状态"
            discovery_data["network_deferred"] = True
        else:
            plugin._save_monitor_status(network_deferred=False, network_message="")
        logger.info(
            "【光鸭云盘助手】【v3.6.9】【连续发现】known检查=%s/%s，随后推进discovery目录=%s，提交=%s，剩余=%s",
            data.get("known_checked", 0),
            data.get("known_total", 0),
            discovery_data.get("dirs_scanned", 0),
            1 if discovery_data.get("scheduled") else 0,
            discovery_data.get("remaining_dirs", 0),
        )
        return discovery

    GuangYaOrganizerEngineV360Mixin._v360_list_directory = list_directory
    GuangYaOrganizerMonitorV366Mixin.run_organize_monitor_scan = run_monitor_scan
    setattr(GuangYaOrganizerMonitorV366Mixin, _PATCH_FLAG, True)
    logger.info(
        "【光鸭云盘助手】【v3.6.9】监控硬化已启用：known预算=%s + 每周期连续50目录discovery + 严格远端读取 + 状态局部回收",
        _v366._KNOWN_SCAN_LIMIT,
    )


__all__ = ["install_organizer_hardening_v369"]
