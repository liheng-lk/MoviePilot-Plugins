"""配置与状态模式迁移：只增补，不丢旧键。"""

from __future__ import annotations

from typing import Any, Dict

from .config import CONFIG_DEFAULTS_V2, STATE_KEYS_V2


SCHEMA_KEY = "plugin_schema_v2"
TARGET_SCHEMA = 2


class ConfigMigratorV2:
    """把 1.x 运行态平滑升级到 2.0 模式标记。"""

    def __init__(self, plugin: Any):
        self.plugin = plugin

    def migrate(self) -> Dict[str, Any]:
        report: Dict[str, Any] = {
            "from_schema": 0,
            "to_schema": TARGET_SCHEMA,
            "touched_state": [],
            "config_filled": [],
        }
        meta = dict(self.plugin.get_data(SCHEMA_KEY) or {})
        try:
            current = int(meta.get("schema") or 0)
        except (TypeError, ValueError):
            current = 0
        report["from_schema"] = current
        if current >= TARGET_SCHEMA:
            report["skipped"] = True
            return report

        # 确保关键状态桶存在，避免 UI/轨迹读取 KeyError。
        for key in STATE_KEYS_V2:
            raw = self.plugin.get_data(key)
            if raw is None:
                if key in {"channel_index"}:
                    self.plugin.save_data(key, {"time": "", "items": [], "errors": [], "source_status": {}})
                elif key in {"subscription_sources"}:
                    self.plugin.save_data(key, {"schema": 2, "items": {}, "updated_at": ""})
                elif key == "decision_traces":
                    self.plugin.save_data(key, {"items": [], "updated_at": ""})
                else:
                    self.plugin.save_data(key, {} if key != "plugin_logs" else [])
                report["touched_state"].append(key)

        # 配置缺省补齐：不覆盖用户已有值。
        cfg = dict(getattr(self.plugin, "_config_cache", None) or {})
        # MoviePilot 插件通常没有 _config_cache；从属性回填常见键即可。
        filled = []
        for key, default in CONFIG_DEFAULTS_V2.items():
            attr = f"_{key}" if not key.startswith("_") else key
            if key == "selected_subscriptions":
                attr = "_selected_subscriptions"
            if key == "save_path":
                attr = "_save_path"
            if key == "channel_urls":
                attr = "_channel_urls"
            if hasattr(self.plugin, attr):
                continue
            # 仅记录可迁移概念；真实赋值由 init_plugin 读。
            filled.append(key)
        report["config_filled"] = filled

        meta.update({
            "schema": TARGET_SCHEMA,
            "migrated_from": current,
            "version": str(getattr(self.plugin, "plugin_version", "2.0.0")),
        })
        self.plugin.save_data(SCHEMA_KEY, meta)
        return report
