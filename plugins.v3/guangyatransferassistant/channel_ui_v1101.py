"""v1.10.1 频道资源与配置页补全。

v1.10.0 重做首页时保留了频道索引计数，却误把频道资源明细从控制台裁掉；同时频道源虽然
仍存在于配置模型中，但和外部 Magnet/ED2K 接口挤在同一张“资源来源”卡片里，实际使用时
很容易被误认为配置入口已经消失。本层把频道资源重新提升为一等功能：

- 首页独立展示频道索引、来源、TMDB/集数和 ResourceGroup 可用方式；
- 配置页恢复独立“频道资源”卡片，频道地址与刷新/抓取参数集中管理；
- 提供只读 `/channels/resources` API，公开数据不返回光鸭分享 URL、Magnet/ED2K 原始 URI；
- 不改变频道抓取、资源匹配和自动转存业务逻辑。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Iterable, List, Set


class GuangYaChannelUiV1101Mixin:
    """恢复频道资源可见性，并让频道配置在 MoviePilot 配置页中明确可见。"""

    build_id = "20260901-r12"

    @staticmethod
    def _channel_model(node: Any, model: str) -> bool:
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict) and str(props.get("model") or "") == model:
                return True
            return any(GuangYaChannelUiV1101Mixin._channel_model(value, model) for value in node.values())
        if isinstance(node, list):
            return any(GuangYaChannelUiV1101Mixin._channel_model(value, model) for value in node)
        return False

    @classmethod
    def _strip_channel_model_cols(cls, node: Any, models: Set[str]) -> Any:
        """从 v1.10.0 其它卡片移除重复频道控件，避免同一个 model 在表单出现两次。"""
        if isinstance(node, list):
            cleaned: List[Any] = []
            for value in node:
                if (
                    isinstance(value, dict)
                    and str(value.get("component") or "") == "VCol"
                    and any(cls._channel_model(value, model) for model in models)
                ):
                    continue
                transformed = cls._strip_channel_model_cols(value, models)
                if (
                    isinstance(transformed, dict)
                    and str(transformed.get("component") or "") == "VRow"
                    and not list(transformed.get("content") or [])
                ):
                    continue
                cleaned.append(transformed)
            return cleaned
        if isinstance(node, dict):
            result = dict(node)
            for key, value in list(result.items()):
                if isinstance(value, (dict, list)):
                    result[key] = cls._strip_channel_model_cols(value, models)
            return result
        return node

    @staticmethod
    def _replace_text(node: Any, old: str, new: str) -> None:
        if isinstance(node, dict):
            if str(node.get("text") or "") == old:
                node["text"] = new
            for value in node.values():
                GuangYaChannelUiV1101Mixin._replace_text(value, old, new)
        elif isinstance(node, list):
            for value in node:
                GuangYaChannelUiV1101Mixin._replace_text(value, old, new)

    def _configured_channel_count_v1101(self) -> int:
        try:
            urls = list(self._source_urls() or [])
            if urls:
                return len(urls)
        except Exception:
            pass
        raw = str(getattr(self, "_channel_urls", "") or "")
        return len([line for line in raw.splitlines() if line.strip()])

    @staticmethod
    def _candidate_text(entry: Dict[str, Any]) -> str:
        raw: Iterable[Any] = entry.get("candidate_types") or []
        labels = []
        mapping = {"guangya": "光鸭", "magnet": "Magnet", "ed2k": "ED2K", "xunlei": "迅雷"}
        for item in raw:
            key = str(item or "").strip().lower()
            label = mapping.get(key, key.upper())
            if label and label not in labels:
                labels.append(label)
        if not labels and entry.get("share_url"):
            labels.append("光鸭")
        return " / ".join(labels) or "-"

    @staticmethod
    def _channel_title(entry: Dict[str, Any]) -> str:
        title = str(entry.get("display_title") or entry.get("resolved_name") or "").strip()
        if title:
            return title[:160]
        text = str(entry.get("text") or "").strip()
        if text:
            for line in text.splitlines():
                line = line.strip()
                if line:
                    return line[:160]
        return "未命名频道资源"

    def _public_channel_resources_v1101(self, *, limit: int = 60) -> Dict[str, Any]:
        index = self.get_data("channel_index") or {}
        raw_items = list(index.get("items") or []) if isinstance(index, dict) else []
        rows: List[Dict[str, Any]] = []
        for entry in raw_items[: max(1, int(limit or 60))]:
            if not isinstance(entry, dict):
                continue
            rows.append({
                "title": self._channel_title(entry),
                "tmdb_id": str(entry.get("tmdb_id") or ""),
                "episode": str(entry.get("episode_hint") or entry.get("total_episode_hint") or ""),
                "source": str(entry.get("source_label") or "频道")[:120],
                "message_id": str(entry.get("message_id") or "")[:80],
                "candidates": self._candidate_text(entry),
                "stale": bool(entry.get("stale")),
                "cached": bool(entry.get("cached_index")),
            })
        errors = []
        for raw in list(index.get("errors") or [])[:8] if isinstance(index, dict) else []:
            if isinstance(raw, dict):
                errors.append(str(raw.get("error") or raw.get("message") or raw.get("source") or "频道抓取异常")[:240])
            else:
                errors.append(str(raw)[:240])
        return {
            "success": True,
            "message": f"频道索引 {len(raw_items)} 条",
            "count": len(raw_items),
            "configured_sources": self._configured_channel_count_v1101(),
            "updated_at": str(index.get("time") or "-") if isinstance(index, dict) else "-",
            "errors": errors,
            "items": rows,
        }

    def api_channel_resources(self) -> Dict[str, Any]:
        """返回脱敏后的频道索引，用于页面和排障。"""
        return self._public_channel_resources_v1101(limit=100)

    def get_api(self):
        apis = list(super().get_api() or [])
        if not any(str(item.get("path") or "") == "/channels/resources" for item in apis if isinstance(item, dict)):
            apis.append({
                "path": "/channels/resources",
                "endpoint": self.api_channel_resources,
                "methods": ["GET"],
                "summary": "读取脱敏后的频道资源索引",
            })
        return apis

    def _channel_page_card_v1101(self) -> Dict[str, Any]:
        report = self._public_channel_resources_v1101(limit=24)
        rows = list(report.get("items") or [])
        content: List[Dict[str, Any]] = []

        if report.get("errors"):
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "warning",
                    "variant": "tonal",
                    "density": "compact",
                    "class": "mb-3",
                    "style": "border-radius:14px;",
                    "text": "；".join(list(report.get("errors") or [])[:3]),
                },
            })

        if rows:
            content.append({
                "component": "VDataTable",
                "props": {
                    "density": "compact",
                    "items-per-page": 10,
                    "headers": [
                        {"title": "频道资源", "key": "title"},
                        {"title": "TMDB", "key": "tmdb_id"},
                        {"title": "集数", "key": "episode"},
                        {"title": "来源", "key": "source"},
                        {"title": "可用方式", "key": "candidates"},
                        {"title": "状态", "key": "state"},
                    ],
                    "items": [
                        {
                            **row,
                            "state": "缓存" if row.get("cached") else ("过期" if row.get("stale") else "可用"),
                        }
                        for row in rows
                    ],
                    "style": "border-radius:14px;overflow:hidden;",
                },
            })
        else:
            content.append({
                "component": "VAlert",
                "props": {
                    "type": "info",
                    "variant": "tonal",
                    "density": "compact",
                    "style": "border-radius:14px;",
                    "text": "当前频道索引为空。请先在插件配置的“频道资源”区域确认频道地址，然后点击“刷新频道”。",
                },
            })

        content.append({
            "component": "div",
            "props": {"class": "d-flex flex-wrap mt-3"},
            "content": [
                self._action("刷新频道", "mdi-refresh", "/refresh", color="primary", variant="outlined"),
            ],
        })
        subtitle = (
            f"已配置 {int(report.get('configured_sources') or 0)} 个频道源 · "
            f"索引 {int(report.get('count') or 0)} 条 · 最近更新 {report.get('updated_at') or '-'}。"
            "同一条消息中的光鸭分享、Magnet、ED2K 仍按 ResourceGroup 合并。"
        )
        return self._surface("频道资源", subtitle, content, icon="mdi-rss")

    def get_page(self):
        pages = list(super().get_page() or [])
        channel_card = self._channel_page_card_v1101()
        # v1.10.0 顺序：Hero / KPI / 资源搜索 / 最近搜索 / 异常 / 在途。
        # 频道资源应紧跟资源搜索，避免只剩一个 KPI 数字而没有资源明细。
        insert_at = 3 if len(pages) >= 3 else len(pages)
        pages.insert(insert_at, channel_card)
        return pages

    def _channel_config_card_v1101(self) -> Dict[str, Any]:
        return self._section(
            "频道资源",
            "频道是光鸭分享与同帖 Magnet / ED2K 的基础索引来源。地址、刷新频率和抓取边界集中在这里，不再藏到其它卡片。",
            "mdi-rss",
            [
                {"component": "VRow", "content": [
                    self._textarea(
                        "channel_urls",
                        "Telegram / 频道源（每行一个）",
                        md=12,
                        rows=4,
                        hint="默认包含光鸭热更与资源频道；支持 tgm 镜像地址。保存后可在首页点击“刷新频道”立即重建索引。",
                    ),
                ]},
                {"component": "VRow", "content": [
                    self._switch("proxy", "频道使用代理", md=3, hint="仅影响频道抓取。"),
                    self._switch("channel_external_auto_dispatch", "同帖 Magnet / ED2K", md=3, hint="将同一频道消息里的外部来源并入 ResourceGroup。"),
                    self._switch("auto_transfer_on_refresh", "刷新后自动处理", md=3, hint="刷新索引后自动检查固定订阅缺失。"),
                    self._switch("external_auto_dispatch", "新增来源自动处理", md=3, hint="新发现的外部来源自动进入既有决策链。"),
                ]},
                {"component": "VRow", "content": [
                    self._field("refresh_minutes", "频道刷新(分钟)", md=3, type="number", min="1"),
                    self._field("history_pages", "每频道历史页数", md=3, type="number", min="1"),
                    self._field("max_share_files", "单分享扫描上限", md=3, type="number", min="1"),
                    self._field("max_files_per_run", "单次最多文件", md=3, type="number", min="1"),
                ]},
            ],
        )

    def get_form(self):
        form, defaults = super().get_form()
        form = deepcopy(form or [])
        if not form:
            return form, defaults

        channel_models = {
            "channel_urls",
            "proxy",
            "channel_external_auto_dispatch",
            "auto_transfer_on_refresh",
            "external_auto_dispatch",
            "refresh_minutes",
            "history_pages",
            "max_share_files",
            "max_files_per_run",
        }
        form = self._strip_channel_model_cols(form, channel_models)
        self._replace_text(form, "资源来源", "搜索补源")

        root = form[0] if isinstance(form[0], dict) else None
        content = list((root or {}).get("content") or [])
        if root is not None:
            # Hero(0) / 接管与保存(1) / 原资源来源(2) ...，频道配置独立放在日常配置区最前。
            content.insert(2 if len(content) >= 2 else len(content), self._channel_config_card_v1101())
            root["content"] = content
        return form, defaults


__all__ = ["GuangYaChannelUiV1101Mixin"]
