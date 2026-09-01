"""v1.9.2 紧凑配置页（v1.9.3 增加观影迅雷秒传配置）。

旧配置页由多个 mixin 逐层 append 卡片和提示，导致配置项重复、解释文字过多。
本层只借用旧表单动态生成的订阅/目录选项和 defaults，最终返回重新分组后的单一配置页。
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


class GuangYaConfigUiMixin:
    """最终配置页展示层；放在运行类 MRO 第一位。"""

    build_id = "20260901-r4"

    @classmethod
    def _find_model_props(cls, node: Any, model: str) -> Optional[Dict[str, Any]]:
        if isinstance(node, dict):
            props = node.get("props")
            if isinstance(props, dict) and str(props.get("model") or "") == model:
                return deepcopy(props)
            for value in node.values():
                found = cls._find_model_props(value, model)
                if found:
                    return found
        elif isinstance(node, list):
            for value in node:
                found = cls._find_model_props(value, model)
                if found:
                    return found
        return None

    @staticmethod
    def _field(model: str, label: str, *, cols: int = 12, md: int = 4, **props: Any) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": cols, "md": md},
            "content": [{
                "component": "VTextField",
                "props": {"model": model, "label": label, **props},
            }],
        }

    @staticmethod
    def _switch(model: str, label: str, *, md: int = 3) -> Dict[str, Any]:
        return {
            "component": "VCol",
            "props": {"cols": 12, "sm": 6, "md": md},
            "content": [{"component": "VSwitch", "props": {"model": model, "label": label, "density": "compact"}}],
        }

    @staticmethod
    def _textarea(model: str, label: str, *, rows: int = 3, hint: str = "", md: int = 12) -> Dict[str, Any]:
        props: Dict[str, Any] = {"model": model, "label": label, "rows": rows, "auto-grow": True}
        if hint:
            props.update({"hint": hint, "persistent-hint": True})
        return {
            "component": "VCol",
            "props": {"cols": 12, "md": md},
            "content": [{"component": "VTextarea", "props": props}],
        }

    @staticmethod
    def _card(title: str, subtitle: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        content: List[Dict[str, Any]] = [{"component": "VCardTitle", "text": title}]
        if subtitle:
            content.append({"component": "VCardSubtitle", "text": subtitle})
        content.extend(rows)
        return {
            "component": "VCard",
            "props": {"variant": "tonal", "class": "mb-3"},
            "content": content,
        }

    def get_form(self):
        old_form, defaults = super().get_form()
        defaults = dict(defaults or {})

        selected = self._find_model_props(old_form, "selected_subscriptions") or {
            "model": "selected_subscriptions",
            "items": [],
            "multiple": True,
            "chips": True,
        }
        selected.update({
            "model": "selected_subscriptions",
            "label": "固定走光鸭的订阅",
            "multiple": True,
            "chips": True,
            "closable-chips": True,
            "clearable": True,
            "prepend-inner-icon": "mdi-magnify",
            "hint": "支持按剧名、年份、季、类型或订阅 ID 搜索",
            "persistent-hint": True,
        })

        save_path = self._find_model_props(old_form, "save_path") or {"model": "save_path", "label": "光鸭目标文件夹"}
        save_path.update({"model": "save_path", "label": "光鸭目标文件夹", "hint": "可选择已有目录，也可直接输入完整路径", "persistent-hint": True})

        basic = self._card(
            "基础",
            "只决定哪些订阅由光鸭接管，以及文件最终保存到哪里。",
            [
                {"component": "VRow", "content": [
                    self._switch("enabled", "启用插件", md=3),
                    self._switch("notify", "任务通知", md=3),
                    self._switch("proxy", "频道使用代理", md=3),
                    self._switch("protect_ongoing", "连载保护", md=3),
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12}, "content": [{"component": "VAutocomplete", "props": selected}]},
                ]},
                {"component": "VRow", "content": [
                    {"component": "VCol", "props": {"cols": 12, "md": 7}, "content": [{"component": "VCombobox", "props": save_path}]},
                    self._switch("create_media_folder", "媒体名字文件夹", md=2),
                    self._switch("media_only", "仅媒体/字幕", md=3),
                ]},
                {"component": "VRow", "content": [
                    self._switch("sync_subscription_progress", "同步剧集进度", md=3),
                    self._switch("strict_subscription_rules", "遵循订阅质量规则", md=3),
                    self._switch("auto_transfer_on_refresh", "刷新后自动转存", md=3),
                    self._switch("daily_summary", "每日摘要", md=3),
                ]},
            ],
        )

        sources = self._card(
            "资源来源",
            "观影中的迅雷分享先尝试光鸭秒传；未命中才继续频道、Magnet 和 ED2K。",
            [
                {"component": "VRow", "content": [
                    self._textarea("channel_urls", "Telegram / 频道源（每行一个）", rows=4, md=6),
                    self._textarea(
                        "magnet_api_sources",
                        "磁力 / ED2K 搜索接口（每行一个）",
                        rows=4,
                        md=6,
                        hint="格式：名称|类型|地址|密钥；类型支持 tgsearch、limitless、json、torznab",
                    ),
                ]},
                {"component": "VRow", "content": [
                    self._switch("viewing_enabled", "启用观影 GYING", md=3),
                    self._switch("provider_auto_search", "缺资源时自动搜索", md=3),
                    self._switch("provider_proxy", "外部资源源使用代理", md=3),
                    self._field("provider_timeout", "搜索超时(秒)", cols=12, md=3, type="number"),
                ]},
                {"component": "VRow", "content": [
                    self._field("viewing_base_url", "观影地址", cols=12, md=6, placeholder="https://www.gying.org"),
                    self._field("viewing_login_path", "登录路径", cols=12, md=6, placeholder="/login"),
                ]},
                {"component": "VRow", "content": [
                    self._field("viewing_username", "观影用户名 / 邮箱", cols=12, md=6, autocomplete="username"),
                    self._field("viewing_password", "观影密码", cols=12, md=6, type="password", autocomplete="current-password"),
                ]},
                {"component": "VRow", "content": [
                    self._textarea(
                        "viewing_cookie",
                        "观影 Cookie（推荐）",
                        rows=2,
                        hint="站点需要验证码或非标准登录时直接填写 Cookie；配置 Cookie 后优先使用 Cookie，不在状态页或 API 中回显。",
                    ),
                ]},
                {"component": "VRow", "content": [
                    self._switch("xunlei_flash_enabled", "观影迅雷秒传（最高优先级）", md=6),
                    self._field("xunlei_flash_max_files", "单分享最多读取文件", cols=12, md=3, type="number", min="1", max="500"),
                    self._field("xunlei_client_id", "迅雷 Client ID", cols=12, md=3),
                ]},
                {"component": "VRow", "content": [
                    self._field("xunlei_device_id", "迅雷 Device ID", cols=12, md=6, placeholder="与 captcha_token 对应的 device_id"),
                    self._field("xunlei_captcha_token", "迅雷 captcha_token", cols=12, md=6, type="password", autocomplete="off", hint="可直接填写当前浏览器捕获的 token；不会在状态 API 中回显", **{"persistent-hint": True}),
                ]},
                {"component": "VRow", "content": [
                    self._textarea(
                        "xunlei_captcha_init_json",
                        "迅雷 shield/captcha/init 请求体（推荐，用于 token 失效后自动刷新）",
                        rows=3,
                        hint="从浏览器开发者工具复制该请求的 JSON 请求体。插件仅复用验证码/设备参数，不保存迅雷分享文件到本地，也不会回显此内容。",
                    ),
                ]},
            ],
        )

        decision = self._card(
            "资源决策与云添加",
            "固定优先级：观影迅雷秒传 > 光鸭分享 > Magnet > ED2K；剧集按真实缺集拆包，秒传未命中自动回退。",
            [
                {"component": "VRow", "content": [
                    self._switch("external_auto_dispatch", "新增来源自动云添加", md=3),
                    self._switch("channel_external_auto_dispatch", "频道 Magnet/ED2K 自动候选", md=3),
                    self._field("source_priority", "后续来源优先级", cols=12, md=6, hint="迅雷秒传固定为 priority=0；此处默认 guangya,magnet,ed2k", **{"persistent-hint": True}),
                ]},
                {"component": "VRow", "content": [
                    self._field("episode_auto_confidence", "自动拆包置信度", cols=6, md=3, type="number", step="0.01", min="0.80", max="1.00"),
                    self._field("offline_poll_minutes", "云任务轮询(分钟)", cols=6, md=3, type="number"),
                    self._field("offline_retry_minutes", "云任务重试(分钟)", cols=6, md=3, type="number"),
                    self._field("offline_max_attempts", "最大重试次数", cols=6, md=3, type="number"),
                ]},
            ],
        )

        advanced = self._card(
            "高级",
            "一般保持默认即可。这里仅保留影响抓取范围、重试和连载保护的参数。",
            [
                {"component": "VRow", "content": [
                    self._field("history_pages", "每频道历史页数", cols=6, md=3, type="number"),
                    self._field("max_files_per_run", "单次最多文件", cols=6, md=3, type="number"),
                    self._field("retry_minutes", "转存失败重试(分钟)", cols=6, md=3, type="number"),
                    self._field("refresh_minutes", "频道刷新(分钟)", cols=6, md=3, type="number"),
                ]},
                {"component": "VRow", "content": [
                    self._field("max_share_files", "单分享最多扫描文件", cols=6, md=3, type="number"),
                    self._field("ongoing_guard_days", "无完结标记等待(天)", cols=6, md=3, type="number"),
                    self._field("summary_cron", "每日摘要 Cron", cols=12, md=3),
                    self._field("provider_result_limit", "外部候选上限", cols=6, md=3, type="number"),
                ]},
                {"component": "VRow", "content": [self._switch("clear_inventory", "保存时清空去重记录（一次性）", md=4)]},
            ],
        )

        defaults.update({
            "provider_auto_search": bool(getattr(self, "_provider_auto_search", True)),
            "provider_timeout": int(getattr(self, "_provider_timeout", 15) or 15),
            "provider_result_limit": int(getattr(self, "_provider_result_limit", 20) or 20),
            "provider_proxy": bool(getattr(self, "_provider_proxy", False)),
            "viewing_enabled": bool(getattr(self, "_viewing_enabled", False)),
            "viewing_base_url": str(getattr(self, "_viewing_base_url", "https://www.gying.org") or ""),
            "viewing_login_path": str(getattr(self, "_viewing_login_path", "/login") or "/login"),
            "viewing_username": str(getattr(self, "_viewing_username", "") or ""),
            "viewing_password": str(getattr(self, "_viewing_password", "") or ""),
            "viewing_cookie": str(getattr(self, "_viewing_cookie", "") or ""),
            "magnet_api_sources": str(getattr(self, "_magnet_api_sources", "") or ""),
            "xunlei_flash_enabled": bool(getattr(self, "_xunlei_flash_enabled", True)),
            "xunlei_flash_max_files": int(getattr(self, "_xunlei_flash_max_files", 80) or 80),
            "xunlei_client_id": str(getattr(self, "_xunlei_client_id", "Xqp0kJBXWhwaTpB6") or ""),
            "xunlei_device_id": str(getattr(self, "_xunlei_device_id", "") or ""),
            "xunlei_captcha_token": str(getattr(self, "_xunlei_captcha_token", "") or ""),
            "xunlei_captcha_init_json": str(getattr(self, "_xunlei_captcha_init_json", "") or ""),
        })
        return [{"component": "VForm", "content": [basic, sources, decision, advanced]}], defaults


__all__ = ["GuangYaConfigUiMixin"]
