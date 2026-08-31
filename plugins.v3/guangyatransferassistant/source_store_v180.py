"""多来源订阅的配置与持久化。"""

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
    _ed2k_dispatch_url = ""
    _ed2k_dispatch_token = ""
    _ed2k_dispatch_timeout = 15

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

        self._ed2k_dispatch_url = str(config.get("ed2k_dispatch_url") or "").strip()
        self._ed2k_dispatch_token = str(config.get("ed2k_dispatch_token") or "").strip()
        self._ed2k_dispatch_timeout = max(
            3, min(safe_int(config.get("ed2k_dispatch_timeout"), 15, 3), 60)
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
            "task_hash": str(previous.get("task_hash") or ""),
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
        # 不自动移除固定路线：该订阅可能原本就是光鸭路线。
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
                            "text": "多来源订阅 · Magnet / ED2K / 观影接入",
                        },
                        {
                            "component": "VCardText",
                            "text": (
                                "Magnet 直接提交 MoviePilot 下载器；ED2K 通过可选 HTTP Bridge。"
                                "观影/第三方可调用 /viewing/ingest 创建或复用订阅并绑定来源。"
                            ),
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 4},
                                    "content": [{
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "external_auto_dispatch",
                                            "label": "外部来源自动提交",
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 8},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "source_priority",
                                            "label": "来源优先级",
                                            "hint": "逗号分隔，如 magnet,ed2k,guangya；删除 guangya 即关闭失败后光鸭后备",
                                            "persistent-hint": True,
                                        },
                                    }],
                                },
                            ],
                        },
                        {
                            "component": "VRow",
                            "content": [
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 7},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ed2k_dispatch_url",
                                            "label": "ED2K HTTP Bridge URL",
                                            "hint": "留空时 ED2K 安全进入 waiting，不消耗重试次数",
                                            "persistent-hint": True,
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 3},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ed2k_dispatch_token",
                                            "label": "Bridge Bearer Token",
                                            "type": "password",
                                        },
                                    }],
                                },
                                {
                                    "component": "VCol",
                                    "props": {"cols": 12, "md": 2},
                                    "content": [{
                                        "component": "VTextField",
                                        "props": {
                                            "model": "ed2k_dispatch_timeout",
                                            "label": "超时(秒)",
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
            "ed2k_dispatch_url": self._ed2k_dispatch_url,
            "ed2k_dispatch_token": self._ed2k_dispatch_token,
            "ed2k_dispatch_timeout": self._ed2k_dispatch_timeout,
        })
        return form, defaults


__all__ = ["GuangYaSourceStoreMixin"]
