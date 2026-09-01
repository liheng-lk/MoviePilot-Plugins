"""v1.10.7 持久状态、配置稳定性与观影人工认证入口门禁。

目的不是吞异常，而是在进入旧兼容层前先把 MoviePilot 历史配置/缓存中常见的脏值规范化：
- selected_subscriptions 支持旧字符串、空值、undefined 等输入，Provider API 不再 ValueError；
- provider_timeout/result_limit、观影节点 TTL、迅雷上限等数值配置先安全归一；
- subscription_sources 中 subscribe_id/attempts/progress/next_retry_at/selected_indexes 统一清洗；
- 离线失败处理收到旧坏状态时先修复再进入原有重试状态机；
- provider_test_last 中非 dict 历史项自动剔除，状态页不再被坏缓存拖垮；
- v1.10.7 把观影人工汉字验证码/PoW 连续恢复层放到最终插件 MRO 最外侧，不改旧资源路由。

所有修复只作用于插件自己的配置/持久数据，不改变 MoviePilot 下载器、光鸭转存优先级或资源规则。
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional

from .gying_auth_v1107 import GuangYaGyingAuthV1107Mixin


_INT_CONFIGS = {
    "provider_timeout": (15, 5, 60),
    "provider_result_limit": (20, 1, 100),
    "viewing_node_cache_minutes": (360, 10, 1440),
    "offline_poll_minutes": (2, 1, 60),
    "offline_retry_minutes": (15, 1, 720),
    "offline_max_attempts": (3, 1, 20),
    "xunlei_flash_max_files": (80, 1, 500),
}


def safe_int_v1106(value: Any, default: int = 0, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = int(default)
    if minimum is not None:
        result = max(int(minimum), result)
    if maximum is not None:
        result = min(int(maximum), result)
    return result


def safe_float_v1106(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def selected_ids_v1106(value: Any) -> List[int]:
    if isinstance(value, str):
        raw_values: Iterable[Any] = [part for part in re.split(r"[\s,，;；]+", value.strip()) if part]
    elif isinstance(value, (list, tuple, set)):
        raw_values = value
    elif value in (None, ""):
        raw_values = []
    else:
        raw_values = [value]
    output: List[int] = []
    for raw in raw_values:
        sid = safe_int_v1106(raw, 0, 0)
        if sid > 0 and sid not in output:
            output.append(sid)
    return output


def selected_indexes_v1106(value: Any) -> List[int]:
    if isinstance(value, str):
        raw_values: Iterable[Any] = [part for part in re.split(r"[\s,，;；]+", value.strip()) if part]
    elif isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = []
    output: List[int] = []
    for raw in raw_values:
        index = safe_int_v1106(raw, -1)
        if index >= 0 and index not in output:
            output.append(index)
    return output


def sanitize_source_row_v1106(raw: Any) -> Dict[str, Any]:
    row = dict(raw) if isinstance(raw, dict) else {}
    row["subscribe_id"] = safe_int_v1106(row.get("subscribe_id"), 0, 0)
    row["attempts"] = safe_int_v1106(row.get("attempts"), 0, 0)
    row["progress"] = safe_int_v1106(row.get("progress"), 0, 0, 100)
    row["next_retry_at"] = safe_float_v1106(row.get("next_retry_at"), 0.0)
    row["selected_indexes"] = selected_indexes_v1106(row.get("selected_indexes"))
    return row


class GuangYaStabilityV1106Mixin(GuangYaGyingAuthV1107Mixin):
    """放在插件 MRO 最外层的脏状态修复与 v1.10.7 观影认证门禁。"""

    build_id = "20260902-r18"

    def init_plugin(self, config: dict = None) -> None:
        clean = dict(config or {})
        # MoviePilot 热更新/局部保存时 config 可能不是完整配置；缺失字段必须交给下层保留，
        # 不能因为稳定层清洗而把用户现有固定转存订阅清空。
        if "selected_subscriptions" in clean:
            clean["selected_subscriptions"] = selected_ids_v1106(clean.get("selected_subscriptions"))
        for key, (default, minimum, maximum) in _INT_CONFIGS.items():
            if key in clean:
                clean[key] = safe_int_v1106(clean.get(key), default, minimum, maximum)
        super().init_plugin(clean)
        self._selected_subscriptions = selected_ids_v1106(
            getattr(self, "_selected_subscriptions", [])
        )

    def _heal_selected_subscriptions_v1106(self) -> List[int]:
        before = getattr(self, "_selected_subscriptions", [])
        safe = selected_ids_v1106(before)
        self._selected_subscriptions = safe
        if before != safe:
            try:
                updater = getattr(self, "update_config", None)
                if callable(updater):
                    updater({"selected_subscriptions": safe})
            except Exception:
                pass
        return safe

    def api_provider_test(self) -> Dict[str, Any]:
        self._heal_selected_subscriptions_v1106()
        return dict(super().api_provider_test() or {})

    def api_provider_search_selected(self) -> Dict[str, Any]:
        self._heal_selected_subscriptions_v1106()
        return dict(super().api_provider_search_selected() or {})

    def _source_store(self) -> Dict[str, Any]:
        store = dict(super()._source_store() or {})
        items = store.get("items") or {}
        clean_items: Dict[str, Dict[str, Any]] = {}
        changed = not isinstance(items, dict)
        if isinstance(items, dict):
            for source_id, raw in items.items():
                clean = sanitize_source_row_v1106(raw)
                clean_items[str(source_id)] = clean
                if not isinstance(raw, dict) or clean != raw:
                    changed = True
        store["items"] = clean_items
        if changed:
            try:
                saver = getattr(self, "_save_source_store", None)
                if callable(saver):
                    saver(store)
            except Exception:
                pass
        return store

    def _sources_for_subscription(self, subscribe_id: int, *, enabled_only: bool = True):
        sid = safe_int_v1106(subscribe_id, 0, 0)
        if sid <= 0:
            return []
        return super()._sources_for_subscription(sid, enabled_only=enabled_only)

    def _upsert_source(
        self,
        subscribe_id: int,
        uri: str,
        *,
        label: str = "",
        origin: str = "manual",
        enabled: bool = True,
        auto_dispatch: Optional[bool] = None,
    ):
        sid = safe_int_v1106(subscribe_id, 0, 0)
        if sid <= 0:
            raise ValueError("MoviePilot 订阅不存在")
        return super()._upsert_source(
            sid,
            uri,
            label=label,
            origin=origin,
            enabled=enabled,
            auto_dispatch=auto_dispatch,
        )

    def _mark_offline_failure(
        self,
        source: Dict[str, Any],
        error: Exception | str,
        *,
        attempt_increment: bool = True,
    ):
        return super()._mark_offline_failure(
            sanitize_source_row_v1106(source),
            error,
            attempt_increment=attempt_increment,
        )

    def _runtime_health_rows(self, overview: Dict[str, Any]):
        try:
            raw = self.get_data("provider_test_last") or {}
            if isinstance(raw, dict):
                providers = raw.get("providers") or []
                if isinstance(providers, list):
                    clean = [dict(row) for row in providers if isinstance(row, dict)]
                    if clean != providers:
                        healed = dict(raw)
                        healed["providers"] = clean
                        try:
                            self.save_data("provider_test_last", healed)
                        except Exception:
                            pass
        except Exception:
            pass
        return super()._runtime_health_rows(overview)


__all__ = [
    "GuangYaStabilityV1106Mixin",
    "safe_int_v1106",
    "safe_float_v1106",
    "selected_ids_v1106",
    "selected_indexes_v1106",
    "sanitize_source_row_v1106",
]
