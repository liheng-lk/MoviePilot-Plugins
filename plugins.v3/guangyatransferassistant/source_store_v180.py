"""多来源订阅的配置与持久化。

Magnet/ED2K 不是交给 MoviePilot 下载器的下载任务，而是光鸭云盘原生“云添加”来源。
本层只负责绑定、去重、状态持久化和用户配置；具体 resolve/create/list 调度由
multisource_v180 执行。
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from .source_types_v180 import (
    SOURCE_SCHEMA_VERSION,
    SOURCE_TYPES,
    normalize_source_uri,
    safe_int,
    source_identity,
)


class GuangYaSourceStoreMixin:
    """保存 Magnet/ED2K 与 MoviePilot 订阅的绑定关系。"""

    _external_auto_dispatch = True
    _source_priority = ("magnet", "ed2k", "guangya")
    _offline_poll_minutes = 2
    _offline_retry_minutes = 15
    _offline_max_attempts = 3

    def init_plugin(self, config: dict = None) -> None:
        config = dict(config or {})
        self._external_auto_dispatch = bool(config.get("external_auto_dispatch", True))

        raw_priority = config.get("source_priority") or "magnet,ed2k,guangya"
        if isinstance(raw_priority, (list, tuple)):
            tokens = [str(value).strip().lower() for value in raw_priority]
        else:
            tokens = [
                value.strip().lower()
                for value in str(raw_priority).replace("，", ",").split(",")
            ]
        ordered = []
        for value in tokens:
            if value in SOURCE_TYPES and value not in ordered:
                ordered.append(value)
        self._source_priority = tuple(ordered or ("magnet", "ed2k", "guangya"))

        self._offline_poll_minutes = max(
            1, min(safe_int(config.get("offline_poll_minutes"), 2, 1), 60)
        )
        self._offline_retry_minutes = max(
            1, min(safe_int(config.get("offline_retry_minutes"), 15, 1), 720)
        )
        self._offline_max_attempts = max(
            1, min(safe_int(config.get("offline_max_attempts"), 3, 1), 20)
        )
        self._ensure_source_store()
        super().init_plugin(config)

    def _source_store(self) -> Dict[str, Any]:
        raw = self.get_data("subscription_sources") or {}
        if not isinstance(raw, dict):
            raw = {}
        items = raw.get("items")
        if not isinstance(items, dict):
            items = {}
        return {
            "schema": SOURCE_SCHEMA_VERSION,
            "items": {
                str(key): dict(value)
                for key, value in items.items()
                if isinstance(value, dict)
            },
            "updated_at": str(raw.get("updated_at") or ""),
        }

    def _ensure_source_store(self) -> None:
        store = self._source_store()
        self._save_source_store(store)

    def _save_source_store(self, store: Dict[str, Any]) -> None:
        store = dict(store or {})
        store["schema"] = SOURCE_SCHEMA_VERSION
        store["updated_at"] = (
            self._now_text()
            if hasattr(self, "_now_text")
            else time.strftime("%Y-%m-%d %H:%M:%S")
        )
        if not isinstance(store.get("items"), dict):
            store["items"] = {}
        self.save_data("subscription_sources", store)

    def _sources_for_subscription(
        self,
        subscribe_id: int,
        *,
        enabled_only: bool = True,
    ) -> List[Dict[str, Any]]:
        sid = int(subscribe_id or 0)
        rows: List[Dict[str, Any]] = []
        for source_id, raw in self._source_store()["items"].items():
            if int(raw.get("subscribe_id") or 0) != sid:
                continue
            if enabled_only and not bool(raw.get("enabled", True)):
                continue
            row = dict(raw)
            row["id"] = str(raw.get("id") or source_id)
            rows.append(row)
        priority = {name: index for index, name in enumerate(self._source_priority)}
        rows.sort(
            key=lambda row: (
                priority.get(str(row.get("type") or ""), 99),
                str(row.get("created_at") or ""),
                str(row.get("id") or ""),
            )
        )
        return rows

    def _upsert_source(
        self,
        subscribe_id: int,
        uri: str,
        *,
        label: str = "",
        origin: str = "manual",
        enabled: bool = True,
        auto_dispatch: Optional[bool] = None,
    ) -> Dict[str, Any]:
        sid = int(subscribe_id or 0)
        subscribe = self._find_subscription(sid) if sid else None
        if not sid or not subscribe:
            raise ValueError("MoviePilot 订阅不存在")

        normalized = normalize_source_uri(uri)
        source_id = source_identity(normalized["type"], normalized["identity"], sid)
        store = self._source_store()
        previous = dict(store["items"].get(source_id) or {})
        now = self._now_text()
        row = {
            **previous,
            **normalized,
            "id": source_id,
            "subscribe_id": sid,
            "label": str(label or previous.get("label") or "").strip()[:120],
            "origin": str(origin or previous.get("origin") or "manual").strip()[:40],
            "enabled": bool(enabled),
            "state": str(previous.get("state") or "new"),
            "attempts": int(previous.get("attempts") or 0),
            "created_at": str(previous.get("created_at") or now),
            "updated_at": now,
            "last_error": str(previous.get("last_error") or ""),
            "task_id": str(previous.get("task_id") or ""),
            "task_status": previous.get("task_status"),
            "progress": int(previous.get("progress") or 0),
            "file_id": str(previous.get("file_id") or ""),
            "resolved_name": str(previous.get("resolved_name") or ""),
            "resolved_url": str(previous.get("resolved_url") or ""),
            "selected_indexes": list(previous.get("selected_indexes") or []),
            "next_retry_at": float(previous.get("next_retry_at") or 0),
            "auto_dispatch": (
                self._external_auto_dispatch
                if auto_dispatch is None
                else bool(auto_dispatch)
            ),
        }
        if not previous:
            row["state"] = "new"

        store["items"][source_id] = row
        self._save_source_store(store)

        # 外部来源一旦绑定，沿用现有固定分流硬门禁；绝不让原生 RSS/搜索重复下载。
        self._add_selected_subscription(sid, persist=True)
        self._record_route_health(
            last_source_added_at=now,
            last_source_added_type=row["type"],
            last_source_added_id=source_id,
        )
        return row

    def _update_source(self, source_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
        source_id = str(source_id or "").strip()
        store = self._source_store()
        row = store["items"].get(source_id)
        if not isinstance(row, dict):
            return None
        updated = dict(row)
        updated.update(fields)
        updated["updated_at"] = self._now_text()
        store["items"][source_id] = updated
        self._save_source_store(store)
        return updated

    def _delete_source(self, source_id: str) -> bool:
        source_id = str(source_id or "").strip()
        store = self._source_store()
        row = store["items"].pop(source_id, None)
        if not row:
            return False
        self._save_source_store(store)
        # 不自动移除固定路线：该订阅可能原本就是光鸭频道路线。
        self._record_route_health(
            last_source_deleted_at=self._now_text(),
            last_source_deleted_id=source_id,
        )
        return True

    def get_form(self):
        form, defaults = super().get_form()
        try:
            content = form[0].get("content") if form else None
            if isinstance(content, list):
                content.append({
                    "component": "VCard",
                    "props": {"variant": "tonal", "class": "mt-3"},
                    "content": [
                        {
                            "component": "VCardTitle",
                            "text": "多来源订阅 · 光鸭原生云添加",
                        },
                        {
                            "component": "VCardText",
                            "text": (
                                "Magnet 与 ED2K 都直接提交光鸭云盘自带的云添加/离线任务，"
                                "不会经过 qBittorrent、Transmission、Aria2 或任何外部 Bridge。"
                                "来源绑定后继续使用固定分流门禁，避免 MoviePilot 原生下载重复获取。"
                            ),
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 3},
                                    "content": [{
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "external_auto_dispatch",
                                            "label": "新增来源自动云添加",
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 5},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "source_priority",
                                            "label": "来源优先级",
                                            "hint": "逗号分隔，如 magnet,ed2k,guangya",
                                            "persistent-hint": True,
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 6, "md": 2},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "offline_poll_minutes",
                                            "label": "任务轮询(分钟)",
                                            "type": "number",
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 6, "md": 2},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "offline_retry_minutes",
                                            "label": "失败重试(分钟)",
                                            "type": "number",
                                        },
                                    }],
                                },
                            ],
                        },
                    ],
                })
        except Exception:
            pass

        defaults.update({
            "external_auto_dispatch": self._external_auto_dispatch,
            "source_priority": ",".join(self._source_priority),
            "offline_poll_minutes": self._offline_poll_minutes,
            "offline_retry_minutes": self._offline_retry_minutes,
            "offline_max_attempts": self._offline_max_attempts,
        })
        return form, defaults


__all__ = ["GuangYaSourceStoreMixin"]
