"""光鸭转存助手 v1.12.0：逐集日历配置 UI 与持久化保护。"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple


class GuangYaAiringUiV1120Mixin:
    """把日期估算时刻与提前检查窗口暴露给配置页，并防止旧异步保存覆盖。"""

    build_id = "20260903-r44"

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        form, defaults = super().get_form()
        defaults = dict(defaults or {})
        defaults.setdefault("calendar_default_hour", 20)
        defaults.setdefault("calendar_early_hours", 12)

        section_builder = getattr(self, "_section", None)
        field_builder = getattr(self, "_field", None)
        if not callable(section_builder) or not callable(field_builder):
            return form, defaults

        calendar = section_builder(
            "更新日历",
            "按每集上映日期计算当前应补集；未来集不再每轮访问频道、迅雷和观影。TMDB 只有日期时使用本地估算时刻。",
            "mdi-calendar-clock-outline",
            [{
                "component": "VRow",
                "content": [
                    field_builder(
                        "calendar_default_hour",
                        "日期默认更新时间（本地小时）",
                        md=6,
                        type="number",
                        min="0",
                        max="23",
                        hint="TMDB 只有 air_date 没有具体时刻时使用；默认 20:00。",
                        **{"persistent-hint": True},
                    ),
                    field_builder(
                        "calendar_early_hours",
                        "提前检查窗口（小时）",
                        md=6,
                        type="number",
                        min="0",
                        max="72",
                        hint="默认提前 12 小时允许搜索，兼顾资源提前放出；未来更远的集直接跳过。",
                        **{"persistent-hint": True},
                    ),
                ],
            }],
        )

        # ConfigUi v1.10 的最终结构为 VForm.content；放在接管设置之后、资源来源之前。
        try:
            content = form[0]["content"]
            if not any(
                isinstance(row, dict)
                and any(
                    isinstance(child, dict) and child.get("text") == "更新日历"
                    for child in ((row.get("content") or [{}])[0].get("content") or [])
                )
                for row in content
            ):
                content.insert(2 if len(content) >= 2 else len(content), calendar)
        except (IndexError, KeyError, TypeError):
            pass
        return form, defaults

    def _save_config(self) -> None:
        """旧 planner 先完整保存，再把 v1.12.0 两个日历字段 merge 回整份配置。"""
        super()._save_config()
        config = self.get_config() or {}
        config = dict(config) if isinstance(config, dict) else {}
        config.update({
            "calendar_default_hour": int(getattr(self, "_calendar_default_hour_v1120", 20) or 20),
            "calendar_early_hours": int(getattr(self, "_calendar_early_hours_v1120", 12) or 12),
        })
        self.update_config(config)


__all__ = ["GuangYaAiringUiV1120Mixin"]
