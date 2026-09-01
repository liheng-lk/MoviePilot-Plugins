"""v1.9.0 ResourceGroup 运行安全收口。

补足两类容易在真实环境中出现的问题：
- 路由名单异步持久化会调用 legacy._save_config，因此必须把 v1.8/v1.9 新配置一起写回，
  否则绑定 Magnet/ED2K 后热重载可能丢失多来源设置；
- Magnet 的真实画质/发布名通常只有 resolve_res 后才能确认，不能仅凭帖子文本在 resolve 前
  判定“不满足订阅规则”。规则校验延后到解析文件列表之后、create_task 之前执行。
"""

from __future__ import annotations

from typing import Any, Dict, Tuple


_RULE_MISMATCH_PREFIX = "RESOURCE_RULE_MISMATCH:"


class GuangYaPlannerSafetyMixin:
    """放在 ResourcePlannerMixin 之前，负责配置完整持久化和解析后规则校验。"""

    def _save_config(self) -> None:
        """一次性保存完整配置，避免 legacy 延迟写盘覆盖 v1.8/v1.9 字段。"""
        self.update_config({
            "enabled": self._enabled,
            "channel_urls": self._channel_urls,
            "selected_subscriptions": self._selected_subscriptions,
            "save_path": self._save_path,
            "create_media_folder": self._create_media_folder,
            "notify": self._notify,
            "daily_summary": self._daily_summary,
            "summary_cron": self._summary_cron,
            "auto_transfer_on_refresh": self._auto_transfer_on_refresh,
            "strict_subscription_rules": self._strict_subscription_rules,
            "media_only": self._media_only,
            "sync_subscription_progress": self._sync_subscription_progress,
            "history_pages": self._history_pages,
            "retry_minutes": self._retry_minutes,
            "max_files_per_run": self._max_files_per_run,
            "refresh_minutes": self._refresh_minutes,
            "proxy": self._proxy,
            "max_share_files": self._max_share_files,
            "protect_ongoing": self._protect_ongoing,
            "ongoing_guard_days": self._ongoing_guard_days,
            "clear_inventory": False,
            # v1.8 原生云添加。
            "external_auto_dispatch": self._external_auto_dispatch,
            "source_priority": ",".join(self._source_priority),
            "offline_poll_minutes": self._offline_poll_minutes,
            "offline_retry_minutes": self._offline_retry_minutes,
            "offline_max_attempts": self._offline_max_attempts,
            # v1.9 ResourceGroup / Episode Resolver。
            "channel_external_auto_dispatch": self._channel_external_auto_dispatch,
            "episode_auto_confidence": self._episode_auto_confidence,
        })

    def _external_resource_allowed(
        self,
        subscribe: Any,
        entry: Dict[str, Any],
        source: Dict[str, Any],
    ) -> Tuple[bool, str]:
        """Magnet/ED2K 在 resolve 前只做候选，不用帖子噪声提前淘汰真实可用资源。"""
        return True, "外部候选待光鸭解析后校验订阅规则"

    @staticmethod
    def _resolved_probe(resolve_data: Dict[str, Any]) -> Dict[str, Any]:
        bt_info = resolve_data.get("btResInfo") or {}
        rows = []
        if isinstance(bt_info, dict):
            top_name = str(bt_info.get("fileName") or "").strip()
            if top_name:
                rows.append({"relative_path": top_name, "name": top_name})
            subfiles = bt_info.get("subfiles") or []
            if isinstance(subfiles, list):
                for raw in subfiles[:1000]:
                    if not isinstance(raw, dict):
                        continue
                    name = str(raw.get("fileName") or "").strip()
                    if name:
                        rows.append({"relative_path": name, "name": name})
        return {"files": rows}

    def _resolve_offline_source(self, source: Dict[str, Any], subscribe: Any) -> Dict[str, Any]:
        resolved = super()._resolve_offline_source(source, subscribe)
        resolve_data = dict(resolved.get("resolve_data") or {})
        descriptor = "\n".join(
            value for value in (
                str(source.get("name") or "").strip(),
                str(source.get("label") or "").strip(),
                str(resolved.get("resolved_name") or "").strip(),
            ) if value
        )
        entry = {"text": descriptor}
        allowed, reason = self._subscription_resource_allowed(
            subscribe,
            entry,
            self._resolved_probe(resolve_data),
        )
        if not allowed:
            raise RuntimeError(f"{_RULE_MISMATCH_PREFIX}{reason}")
        return resolved

    def _mark_offline_failure(
        self,
        source: Dict[str, Any],
        error: Exception | str,
        *,
        attempt_increment: bool = True,
    ) -> Dict[str, Any]:
        message = str(error or "")
        if message.startswith(_RULE_MISMATCH_PREFIX):
            detail = message[len(_RULE_MISMATCH_PREFIX):].strip() or "不满足订阅规则"
            updated = self._update_source(
                str(source.get("id") or ""),
                state="failed",
                last_error=f"订阅规则不匹配：{detail}"[:500],
                next_retry_at=0,
            ) or source
            self._plugin_log(
                "INFO",
                "【光鸭转存助手】【候选过滤】来源 %s resolve 后不满足订阅规则，转向下一候选：%s",
                str(source.get("id") or ""),
                detail,
            )
            return updated
        return super()._mark_offline_failure(
            source,
            error,
            attempt_increment=attempt_increment,
        )

    def get_page(self):
        pages = list(super().get_page() or [])
        review = sum(
            1 for row in self._source_store()["items"].values()
            if isinstance(row, dict) and str(row.get("state") or "") == "needs_review"
        )
        if review:
            pages.insert(0, {
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "title": "有资源需要人工确认",
                    "text": f"{review} 个 Magnet/ED2K 候选因集号置信度不足未创建云添加任务；不会整包误存。",
                },
            })
        return pages


__all__ = ["GuangYaPlannerSafetyMixin"]
