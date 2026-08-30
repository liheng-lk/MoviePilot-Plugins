"""光鸭自动整理的子目录历史聚合层。

本模块只负责把文件级流水整理成适合 UI 展示的“目录批次视图”。它不参与媒体识别、
分类、目标目录、命名或实际整理；这些业务规则仍全部由 MoviePilot 原生整理链负责。

v3.6.0：历史层作为插件 MRO 的第一层，将统一 v3.6 execution/engine 放在旧 WorkerGuard /
QueueRecovery / CandidateFilter / FolderStream 之前。这样新引擎直接拥有 scan/tick/fallback 的
唯一调度权，旧 3.5.x 兼容层仍可提供识别与安全能力，但不能再改写主状态机语义。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List

from .organizer_execution_v360 import GuangYaOrganizerExecutionV360Mixin


class GuangYaFolderHistoryMixin(GuangYaOrganizerExecutionV360Mixin):
    """为目录流式调度提供持久历史保留和按子目录折叠的状态视图。"""

    _monitor_history_limit = 1000
    _folder_history_group_limit = 40
    _folder_history_detail_limit = 80

    _result_bucket = {
        "completed": "completed",
        "history_completed": "completed",
        "queued": "inflight",
        "submitted": "inflight",
        "failed": "retry",
        "deferred": "retry",
        "blocked": "blocked",
        "gated": "blocked",
        "ignored": "ignored",
    }

    _isolated_message_replacements = (
        ("已进入 MoviePilot 整理链，等待最终回执", "已进入光鸭私有整理队列，等待独立 worker 执行"),
        ("MoviePilot 暂未接收入队", "光鸭私有整理队列暂未接收"),
        ("提交 MP 失败", "提交私有整理队列失败"),
    )

    def _append_monitor_history(self, row: Dict[str, Any]) -> None:
        normalized = dict(row or {})
        message = str(normalized.get("message") or "")
        for old, new in self._isolated_message_replacements:
            message = message.replace(old, new)
        if message:
            normalized["message"] = message
        return super()._append_monitor_history(normalized)

    @staticmethod
    def _empty_folder_counts() -> Dict[str, int]:
        return {
            "completed": 0,
            "inflight": 0,
            "retry": 0,
            "blocked": 0,
            "ignored": 0,
            "stabilizing": 0,
            "other": 0,
        }

    def _folder_history_groups(self) -> List[Dict[str, Any]]:
        raw_history = list(self.get_data(self._monitor_history_key) or [])
        history = raw_history[-self._monitor_history_limit :]
        groups: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

        for row in reversed(history):
            if not isinstance(row, dict):
                continue
            raw_path = str(row.get("path") or "")
            group_path = str(row.get("group_path") or "")
            if not group_path and raw_path:
                try:
                    group_path = self._group_path_for_file(raw_path)
                except Exception:
                    group_path = ""
            if not group_path:
                continue

            group = groups.get(group_path)
            if group is None:
                group = {
                    "group_path": group_path,
                    "group_name": str(row.get("group_name") or self._group_name(group_path)),
                    "latest_time": str(row.get("time") or ""),
                    "latest_batch_id": str(row.get("batch_id") or ""),
                    "summary_message": "",
                    "counts": self._empty_folder_counts(),
                    "total_files": 0,
                    "rows": [],
                    "_seen_paths": set(),
                }
                groups[group_path] = group
            elif not group["latest_batch_id"] and row.get("batch_id"):
                group["latest_batch_id"] = str(row.get("batch_id") or "")

            result = str(row.get("result") or "")
            if result == "folder_batch":
                if not group["summary_message"]:
                    group["summary_message"] = str(row.get("message") or "")
                continue

            if len(group["rows"]) < self._folder_history_detail_limit:
                group["rows"].append(dict(row))

            path_key = raw_path or f"__row__:{row.get('time')}:{row.get('name')}:{result}"
            if path_key in group["_seen_paths"]:
                continue
            group["_seen_paths"].add(path_key)
            bucket = self._result_bucket.get(result, "other")
            group["counts"][bucket] += 1
            group["total_files"] += 1

        state_current: Dict[str, Dict[str, int]] = {}
        try:
            state = self._state().load()
            mapping_names = (
                ("completed", "completed"),
                ("inflight", "inflight"),
                ("retry", "retry"),
                ("blocked", "blocked"),
                ("ignored", "ignored"),
                ("stabilizing", "stabilizing"),
            )
            for state_name, bucket in mapping_names:
                for path in dict(state.get(state_name) or {}):
                    try:
                        group_path = self._group_path_for_file(path)
                    except Exception:
                        continue
                    current = state_current.setdefault(group_path, self._empty_folder_counts())
                    current[bucket] += 1
        except Exception:
            state_current = {}

        for group_path, current in state_current.items():
            if group_path not in groups:
                groups[group_path] = {
                    "group_path": group_path,
                    "group_name": self._group_name(group_path),
                    "latest_time": "",
                    "latest_batch_id": "",
                    "summary_message": "当前状态来自自动整理状态机，尚无最近文件流水",
                    "counts": self._empty_folder_counts(),
                    "total_files": sum(current.values()),
                    "rows": [],
                    "_seen_paths": set(),
                }
            groups[group_path]["current"] = current

        result_groups: List[Dict[str, Any]] = []
        for group in groups.values():
            group.setdefault("current", self._empty_folder_counts())
            group.pop("_seen_paths", None)
            result_groups.append(group)
            if len(result_groups) >= self._folder_history_group_limit:
                break
        return result_groups

    def api_organize_monitor_status(self) -> Dict[str, Any]:
        response = super().api_organize_monitor_status()
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        raw_history = list(self.get_data(self._monitor_history_key) or [])
        data["folder_history"] = self._folder_history_groups()
        data["history_retained"] = len(raw_history)
        data["history"] = raw_history[-40:][::-1]
        return response


__all__ = ["GuangYaFolderHistoryMixin"]
