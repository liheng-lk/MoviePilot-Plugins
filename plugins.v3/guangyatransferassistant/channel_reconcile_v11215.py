"""v1.12.15 候选：频道缓存被动补偿触发。

严格频道游标只回答“这一轮是不是新消息”，7 天频道缓存回答“资源现在是否已经存在”。
旧实现只把严格新消息送入 channel_event，因此在首次建立游标、插件重启/bootstrap、
或事件触发被后台合并等情况下，会出现“频道缓存明明已有可用资源，但已有订阅没有再进入转存”的空窗。

本层不把频道变成主动搜索器，也不重新消费所有历史消息。它只补偿满足以下条件的订阅：
1. 仍是光鸭固定分流的活跃订阅；
2. 仍有真实未覆盖缺口（TV 已扣 reservation/source claim；电影仍未完成且不在途）；
3. 7 天频道缓存中存在已经通过媒体匹配、且实际包含 GuangYa / Xunlei / Magnet / ED2K
   任一可执行载荷的条目；
4. 条目仍可能覆盖当前缺集。

补偿得到的订阅仍复用既有 ``频道新增资源`` -> ``channel_event`` 路径，因此：
- 不访问 GYING，不消耗外部检索冷却；
- 不绕过媒体身份、质量、MoviePilot library missing、reservation/source claim；
- 不绕过 v1.12.14 物理文件 episodes ⊆ allowed missing；
- 不改变来源优先级和 Magnet/ED2K 的光鸭 cloudcollection 路线。

候选阶段故意不修改最终 ``plugin_version/build_id``；只有行为测试与标准 CI 全绿后，
才把公开版本从 v1.12.14/r60 迁移为 v1.12.15/r61。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set, Tuple

from .channel_event_v1115 import _entry_key_v1115
from .core_pipeline_final_v11214 import GuangYaCorePipelineFinalV11214Mixin


class GuangYaChannelReconcileV11215Mixin(GuangYaCorePipelineFinalV11214Mixin):
    """让“频道已有资源”本身成为可恢复的被动事实，而不是一次性事件。"""

    @staticmethod
    def _channel_entry_actionable_v11215(entry: Dict[str, Any]) -> bool:
        row = dict(entry or {})
        if row.get("stale"):
            return False
        if str(row.get("share_url") or "").strip():
            return True
        for raw in row.get("xunlei_sources") or []:
            if not isinstance(raw, dict):
                continue
            if str(raw.get("share_id") or raw.get("identity") or raw.get("uri") or "").strip():
                return True
        for raw in row.get("external_sources") or []:
            if not isinstance(raw, dict):
                continue
            source_type = str(raw.get("type") or "").strip().lower()
            if source_type not in {"magnet", "ed2k", "xunlei"}:
                continue
            if str(raw.get("identity") or raw.get("uri") or "").strip():
                return True
        return False

    def _channel_passive_gap_v11215(self, subscribe: Any) -> Tuple[Any, ...]:
        """仅用于决定要不要进入 channel_event；最终写盘仍由既有硬栅栏决定。"""
        try:
            if self._is_movie_subscription(subscribe):
                return ("movie",) if bool(self._movie_needs_pull_v1125(subscribe)) else tuple()
            values = self._uncovered_missing_v1125(subscribe) or set()
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【频道补偿v1.12.15】#%s %s 读取真实未覆盖缺口失败，补偿触发 fail closed：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(err)[:220],
            )
            return tuple()
        result: Set[int] = set()
        for raw in values:
            try:
                value = int(raw or 0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                result.add(value)
        return tuple(sorted(result))

    def _cached_actionable_channel_matches_v11215(self, subscribe: Any) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        seen: Set[str] = set()
        try:
            pairs: Iterable[Any] = self._cached_matches_for_subscription(subscribe) or []
        except Exception as err:
            self._plugin_log(
                "WARNING",
                "【光鸭转存助手】【频道补偿v1.12.15】#%s %s 读取频道缓存匹配失败：%s",
                int(getattr(subscribe, "id", 0) or 0),
                str(getattr(subscribe, "name", "") or ""),
                str(err)[:220],
            )
            return []

        for item in pairs:
            if isinstance(item, (tuple, list)) and item:
                raw = item[0]
            else:
                raw = item
            if not isinstance(raw, dict):
                continue
            row = dict(raw)
            if not self._channel_entry_actionable_v11215(row):
                continue
            try:
                if not bool(self._entry_can_cover_missing_v1115(row, subscribe)):
                    continue
            except Exception:
                continue
            key = _entry_key_v1115(row)
            if not key:
                key = str(row.get("resource_group_id") or row.get("message_id") or row.get("share_url") or "").strip()
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            matches.append(row)
        return matches

    def _subscriptions_for_new_channel_entries_v1115(self) -> List[int]:
        """严格新事件优先，再补回缓存中已经存在但尚未消费成功的真实资源。"""
        immediate = {
            int(value) for value in (super()._subscriptions_for_new_channel_entries_v1115() or [])
            if str(value).isdigit() and int(value) > 0
        }
        reconciled: Set[int] = set()
        diagnostics: List[str] = []

        try:
            subscriptions = list(self._active_selected_subscriptions_v1125() or [])
        except Exception:
            subscriptions = []

        for subscribe in subscriptions:
            sid = int(getattr(subscribe, "id", 0) or 0)
            if sid <= 0 or sid in immediate:
                continue
            gap = self._channel_passive_gap_v11215(subscribe)
            if not gap:
                continue
            matches = self._cached_actionable_channel_matches_v11215(subscribe)
            if not matches:
                continue
            reconciled.add(sid)
            diagnostics.append(
                f"#{sid}:{str(getattr(subscribe, 'name', '') or '')[:80]} gap={list(gap)} cache={len(matches)}"
            )

        if reconciled:
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【频道补偿v1.12.15】频道缓存已有可执行资源但未形成新事件，补偿触发 %s 个仍有真实缺口的订阅：%s",
                len(reconciled),
                "；".join(diagnostics[:12]),
            )
        return sorted(immediate | reconciled)


__all__ = ["GuangYaChannelReconcileV11215Mixin"]
