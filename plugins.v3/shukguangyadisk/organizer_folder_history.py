"""光鸭自动整理的子目录历史聚合层。

本模块只负责把文件级流水整理成适合 UI 展示的“目录批次视图”。它不参与媒体识别、
分类、目标目录、命名或实际整理；这些业务规则仍全部由 MoviePilot 原生整理链负责。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List


class GuangYaFolderHistoryMixin:
    """为目录流式调度提供持久历史保留和按子目录折叠的状态视图。"""

    # 一个短剧/整季目录可能一次产生几十到上百条文件级事件。100 条历史很容易让一个
    # 批次还没结束就丢失开头，因此 v3.4.0 提高保留量，但 API 只返回压缩后的目录视图。
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
        """将最近文件流水按监控根直接子目录聚合。

        计数采用“每个源文件最近一条有效事件”，因此一个文件从 queued -> completed
        不会被重复统计。folder_batch 仅作为目录批次摘要，不计入文件状态。
        """
        raw_history = list(self.get_data(self._monitor_history_key) or [])
        history = raw_history[-self._monitor_history_limit :]
        groups: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

        # 最新记录优先，便于确定每个源文件的当前/最近结果。
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
            else:
                if not group["latest_batch_id"] and row.get("batch_id"):
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

        # 用持久状态机补充“当前”视角。历史计数用于看批次结果，current 用于看此刻队列。
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

        # 仅存在状态但最近还没有流水的目录，也应能在 UI 中看到。
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
        """在兼容原状态 API 的基础上增加 folder_history。"""
        response = super().api_organize_monitor_status()
        if not isinstance(response, dict) or not response.get("success"):
            return response
        data = response.setdefault("data", {})
        raw_history = list(self.get_data(self._monitor_history_key) or [])
        data["folder_history"] = self._folder_history_groups()
        data["history_retained"] = len(raw_history)
        # 保留原 flat history 兼容旧前端，但比旧版 20 条多给一些，便于降级排查。
        data["history"] = raw_history[-40:][::-1]
        return response


__all__ = ["GuangYaFolderHistoryMixin"]
