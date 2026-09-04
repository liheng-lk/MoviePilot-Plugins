"""v1.10.15 频道事件严格游标判定层。

资源缓存解决“以后还能直接匹配什么”，消息游标解决“这一轮到底新增了什么”。
两者不得混用，否则 7 天缓存过期后仍停留在频道首页的旧消息可能被再次误判为新资源。

- 有数字 Telegram message_id：只把 message_id > 刷新前 last_message_id 的条目作为新事件；
- 首次建立游标只做缓存 bootstrap，不把整页历史当新资源；
- 无数字 message_id 的镜像使用轻量指纹 seen 集合作为兼容兜底，不保存链接正文；
- seen 元数据保留 30 天、每周清理，仅用于事件去重，不影响 7 天资源缓存策略。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List

from .channel_event_guard_v1115 import GuangYaChannelEventGuardV1115Mixin
from .channel_event_v1115 import _entry_key_v1115


_CHANNEL_EVENT_SEEN_KEY_V1115 = "channel_event_seen_v1115"
_CHANNEL_EVENT_SEEN_RETENTION_V1115 = 30 * 24 * 60 * 60
_CHANNEL_EVENT_SEEN_CLEANUP_V1115 = 7 * 24 * 60 * 60
_CHANNEL_EVENT_SEEN_MAX_V1115 = 20000


class GuangYaChannelCursorEventV1115Mixin(GuangYaChannelEventGuardV1115Mixin):
    """最终频道新资源判定：游标是事件真相，缓存只是资源仓库。"""

    build_id = "20260902-r26"

    @staticmethod
    def _cursor_snapshot_v1115(raw: Any) -> Dict[str, int]:
        result: Dict[str, int] = {}
        if not isinstance(raw, dict):
            return result
        for source, row in raw.items():
            if isinstance(row, dict):
                value = row.get("last_message_id")
            else:
                value = row
            try:
                cursor = int(value or 0)
            except (TypeError, ValueError):
                cursor = 0
            result[str(source or "").strip()] = max(0, cursor)
        return result

    def _channel_event_seen_v1115(self) -> Dict[str, Any]:
        raw = self.get_data(_CHANNEL_EVENT_SEEN_KEY_V1115) or {}
        if not isinstance(raw, dict):
            raw = {}
        items = raw.get("items")
        return {
            "items": dict(items) if isinstance(items, dict) else {},
            "last_cleanup_at": float(raw.get("last_cleanup_at") or 0),
        }

    def _save_channel_event_seen_v1115(self, rows: Iterable[Dict[str, Any]]) -> set[str]:
        state = self._channel_event_seen_v1115()
        items = dict(state.get("items") or {})
        before = set(items)
        now = time.time()
        for row in rows or []:
            if not isinstance(row, dict) or row.get("stale"):
                continue
            message_id = str(row.get("message_id") or "").strip()
            if message_id.isdigit():
                continue
            key = _entry_key_v1115(row)
            if key:
                items[key] = now

        last_cleanup = float(state.get("last_cleanup_at") or 0)
        if not last_cleanup or now - last_cleanup >= _CHANNEL_EVENT_SEEN_CLEANUP_V1115:
            cutoff = now - _CHANNEL_EVENT_SEEN_RETENTION_V1115
            items = {
                key: stamp for key, stamp in items.items()
                if float(stamp or 0) >= cutoff
            }
            last_cleanup = now
        if len(items) > _CHANNEL_EVENT_SEEN_MAX_V1115:
            items = dict(sorted(items.items(), key=lambda pair: float(pair[1] or 0), reverse=True)[:_CHANNEL_EVENT_SEEN_MAX_V1115])
        self.save_data(_CHANNEL_EVENT_SEEN_KEY_V1115, {
            "items": items,
            "last_cleanup_at": last_cleanup,
            "updated_at": now,
        })
        return before

    def refresh_channels(self, force: bool = False):
        # 先快照刷新前游标；super 才允许推进 channel_cursors。
        before_cursors = self._cursor_snapshot_v1115(self.get_data("channel_cursors") or {})
        rows = list(super().refresh_channels(force=force) or [])

        # 主动 Pull 的 super 已明确只读本地缓存，不产生频道事件。
        if self._route_source_mode_value_v1115() in {"viewing_poll", "airing_pull", "daily_repair_pull"} and not force:
            self._channel_new_entries_v1115 = []
            return rows

        old_fallback_candidates = list(getattr(self, "_channel_new_entries_v1115", []) or [])
        fallback_keys = {
            _entry_key_v1115(row)
            for row in old_fallback_candidates
            if isinstance(row, dict)
        }
        seen_before = self._save_channel_event_seen_v1115(rows)
        strict_new: List[Dict[str, Any]] = []
        emitted = set()

        for raw in rows:
            if not isinstance(raw, dict) or raw.get("stale") or raw.get("cached_index"):
                continue
            row = dict(raw)
            source = str(row.get("source_url") or "").strip()
            message_id = str(row.get("message_id") or "").strip()
            key = _entry_key_v1115(row)
            if not key or key in emitted:
                continue

            if message_id.isdigit():
                old_cursor = int(before_cursors.get(source, 0) or 0)
                # old_cursor=0 表示首次建立该频道游标，只做缓存 bootstrap；不把整页历史当事件。
                if old_cursor > 0 and int(message_id) > old_cursor:
                    strict_new.append(row)
                    emitted.add(key)
                continue

            # 没有数字 message_id 时，仅接受底层本轮增量候选且此前没有见过该指纹。
            if key in fallback_keys and key not in seen_before:
                strict_new.append(row)
                emitted.add(key)

        self._channel_new_entries_v1115 = strict_new
        if strict_new:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【频道事件】严格游标确认本轮新增 %s 条资源；仅这些条目参与订阅匹配",
                len(strict_new),
            )
        return rows


__all__ = ["GuangYaChannelCursorEventV1115Mixin"]