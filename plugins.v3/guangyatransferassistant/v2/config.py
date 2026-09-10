"""2.0 配置键与默认值。字段名与 1.x 兼容，升级不丢配置。"""

from __future__ import annotations

from typing import Any, Dict, List


# 持久化状态键：迁移时只读增补，不删除。
STATE_KEYS_V2 = (
    "channel_index",
    "channel_cursors",
    "processed_entries",
    "subscription_sources",
    "media_facts",
    "transfer_jobs",
    "transfer_inventory",
    "transfer_history",
    "resource_plans",
    "last_run",
    "airing_calendar_v1110",
    "airing_check_state_v1110",
    "airing_week_view_v1121",
    "viewing_session_state",
    "xunlei_flash_state",
    "xunlei_share_season_claims_v11210",
    "decision_traces",
    "plugin_schema_v2",
)

CONFIG_DEFAULTS_V2: Dict[str, Any] = {
    "enabled": False,
    "notify": True,
    "sync_subscription_progress": True,
    "protect_ongoing": True,
    "selected_subscriptions": [],
    "save_path": "/光鸭转存",
    "create_media_folder": False,
    "media_only": True,
    "strict_subscription_rules": True,
    "auto_transfer_on_refresh": True,
    "daily_summary": False,
    "summary_cron": "30 22 * * *",
    "channel_urls": "",
    "refresh_minutes": 5,
    "history_pages": 3,
    "proxy": False,
    "max_files_per_run": 50,
    "max_share_files": 5000,
    "retry_minutes": 30,
    "ongoing_guard_days": 10,
    "calendar_default_hour": 20,
    "calendar_early_hours": 6,
    "viewing_enabled": True,
    "xunlei_flash_enabled": True,
    "magnet_api_sources": "",
    "provider_auto_search": True,
    "clear_inventory": False,
    "ui_v2": True,
}


def merge_config_defaults(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    merged = dict(CONFIG_DEFAULTS_V2)
    if isinstance(raw, dict):
        for key, value in raw.items():
            merged[key] = value
    if not str(merged.get("channel_urls") or "").strip():
        # 保留空串含义：由 legacy 回退到 DEFAULT_CHANNEL_URLS
        merged["channel_urls"] = str(raw.get("channel_urls") if isinstance(raw, dict) else "") or ""
    return merged


def config_field_names() -> List[str]:
    return sorted(CONFIG_DEFAULTS_V2.keys())
