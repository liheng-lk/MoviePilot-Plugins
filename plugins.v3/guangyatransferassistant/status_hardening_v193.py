"""v1.9.3 状态页最终信息收口。

保持 v1.9.1 五区单屏结构，只补充观影当前节点和迅雷秒传摘要，避免为了新来源重新
堆叠独立诊断卡。
"""

from __future__ import annotations

from typing import Any, Dict

from .status_ui_v191 import GuangYaStatusUiMixin


class GuangYaStatusHardeningMixin:
    """给紧凑首页补 GYING / 迅雷摘要，不恢复历史信息墙。"""

    build_id = "20260901-r8"

    def _status_overview_v191(self) -> Dict[str, Any]:
        overview = dict(super()._status_overview_v191() or {})
        viewing = self.get_data("viewing_session_state") or {}
        if not isinstance(viewing, dict):
            viewing = {}
        active_node = str(viewing.get("active_node") or "")
        node_row = dict(((viewing.get("nodes") or {}).get(active_node) or {})) if active_node else {}
        overview["viewing"] = {
            "enabled": bool(getattr(self, "_viewing_enabled", False)),
            "active_node": active_node,
            "status": str(node_row.get("status") or ("waiting" if getattr(self, "_viewing_enabled", False) else "disabled")),
            "verified": bool(node_row.get("verified")),
            "login_mode": str(node_row.get("login_mode") or ""),
        }

        xunlei = self.get_data("xunlei_flash_state") or {}
        items = (xunlei.get("items") or {}).values() if isinstance(xunlei, dict) and isinstance(xunlei.get("items"), dict) else []
        completed = failed = 0
        for raw in items:
            if not isinstance(raw, dict):
                continue
            state = str(raw.get("state") or "")
            if state == "completed":
                completed += 1
            elif state == "failed":
                failed += 1
        overview["xunlei_flash"] = {
            "enabled": bool(getattr(self, "_xunlei_flash_enabled", True)),
            "completed": completed,
            "failed": failed,
        }
        return overview

    def get_page(self):
        pages = GuangYaStatusUiMixin.get_page(self)
        overview = self._status_overview_v191()
        viewing = dict(overview.get("viewing") or {})
        xunlei = dict(overview.get("xunlei_flash") or {})
        active_node = str(viewing.get("active_node") or "-")
        viewing_state = str(viewing.get("status") or "-")

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                text = node.get("text")
                if isinstance(text, str) and "资源策略：光鸭直接转存 > Magnet > ED2K" in text:
                    node["text"] = text.replace(
                        "资源策略：光鸭直接转存 > Magnet > ED2K",
                        "资源策略：观影迅雷秒传 > 光鸭直接转存 > Magnet > ED2K",
                    )
                if isinstance(text, str) and "详细诊断通过“运行自检”" in text:
                    node["text"] = (
                        text
                        + f"\n观影：{viewing_state} · 当前节点 {active_node} · "
                        f"迅雷秒传：完成 {int(xunlei.get('completed') or 0)} / 失败 {int(xunlei.get('failed') or 0)}。"
                    )
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(pages)
        return pages


__all__ = ["GuangYaStatusHardeningMixin"]
